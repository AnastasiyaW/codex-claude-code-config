# Обучение и дообучение диффузионных моделей

## Table of contents
1. Цели обучения: DDPM, improved, EDM, flow
2. CFG-обучение (conditional dropout)
3. Ключевые гиперпараметры
4. Методы дообучения: сравнительная таблица
5. Код: один training step (epsilon-prediction)
6. Код: LoRA-инъекция вручную
7. Код: activation checkpointing + AMP

---

## 1. Цели обучения

### DDPM (baseline)
```
L = E[||ε − ε_θ(x_t, t)||²]
```
Денойзер предсказывает добавленный шум `ε` для зашумлённого `x_t` на случайном шаге `t`.

### Improved DDPM (Nichol & Dhariwal, 2021)
- Обучение дисперсий обратного процесса (вместо фиксированных)
- Гибридный objective: `L_simple + λ · L_vlb`
- Позволяет ускорять сэмплинг при малой потере качества

### EDM design space (Karras et al., 2022)
Разделяет choices явно: preconditioning, noise schedule, sampling/training. Полезно для инженера — видно, какие ручки реально дают выигрыш.

### Flow matching / rectified flow
Учится предсказывать **скорость** (velocity) ODE-траектории вместо шума. `prediction_type = "flow_prediction"`.

---

## 2. CFG-обучение

Одна модель, два режима. Кондиция случайно обнуляется с вероятностью `p_uncond` (обычно 0.1):

```python
# Пример с dropout кондиции
def apply_cfg_dropout(encoder_hidden_states, p_uncond=0.1):
    batch_size = encoder_hidden_states.shape[0]
    # Случайные индексы для обнуления
    mask = torch.rand(batch_size) > p_uncond
    mask = mask.to(encoder_hidden_states.device)
    # Заменяем на unconditional (нулевой/пустой эмбеддинг)
    uncond_emb = torch.zeros_like(encoder_hidden_states)
    return torch.where(mask.view(-1, 1, 1), encoder_hidden_states, uncond_emb)
```

---

## 3. Ключевые гиперпараметры

### Инференс — самые «рычажные»
1. **scheduler + num_inference_steps** — разные schedulers дают разные траектории
2. **guidance_scale** — adherence к промпту; слишком высоко = артефакты и потеря diversity
3. **prediction_type** — что предсказывает модель/солвер

### Обучение — самые «рычажные»
1. **LR и batch режим** — сильнее влияют на стабильность, чем большинство трюков
2. **Noise/sigma schedule** — один из центральных design choices (EDM, Improved DDPM)
3. **p_uncond** — вероятность dropout кондиции для CFG-обучения

---

## 4. Методы дообучения

| Метод | Что меняется | Сильные стороны | Типичные риски |
|---|---|---|---|
| **Full fine-tune** | Все веса денойзера | Максимальная адаптация | Дорого; легко переобучить |
| **LoRA** | Low-rank матрицы в attention | Мало параметров, быстрый цикл | Нужен аккуратный выбор целевых слоёв и ранга |
| **DreamBooth** | FT на 3–5 фото субъекта + prior preservation | Сильная «привязка» субъекта | Риск overfitting на тренировочных видах |
| **Textual Inversion** | Новый токен-вектор в text embedding | Очень лёгко (3–5 изображений) | Ограниченная выразительность |
| **Prompt/Prefix tuning** | «Мягкие промпты» для LLM-энкодера | Когда text encoder доминирует | Для денойзера часто недостаточно |
| **Adapter layers** | Малые модули в слоях | Хороший компромисс quality/size | Сложнее внедрение |

**Практическое правило:** начинать с LoRA → при необходимости → full fine-tune.

---

## 5. Код: один training step (epsilon-prediction)

```python
import torch
import torch.nn.functional as F
from diffusers import StableDiffusionPipeline

device = "cuda" if torch.cuda.is_available() else "cpu"
pipe = StableDiffusionPipeline.from_pretrained(
    "stable-diffusion-v1-5/stable-diffusion-v1-5",
    torch_dtype=torch.float16 if device == "cuda" else torch.float32,
).to(device)

pipe.unet.train()
pipe.text_encoder.eval()
pipe.vae.eval()

# Пример данных: случайные картинки → латенты через VAE
images = torch.rand((2, 3, 512, 512), device=device, dtype=pipe.unet.dtype) * 2 - 1
with torch.no_grad():
    latents = pipe.vae.encode(images).latent_dist.sample()
    latents = latents * pipe.vae.config.scaling_factor

    prompts = ["a photo of a dog", "a photo of a cat"]
    tokens = pipe.tokenizer(prompts, padding="max_length", truncation=True,
                             return_tensors="pt").to(device)
    text_emb = pipe.text_encoder(**tokens).last_hidden_state

# Семплируем timestep и шум
t = torch.randint(0, pipe.scheduler.config.num_train_timesteps,
                  (latents.size(0),), device=device).long()
noise = torch.randn_like(latents)
noisy_latents = pipe.scheduler.add_noise(latents, noise, t)

# Epsilon-prediction.  The CPU fallback stays out of CUDA autocast.
with torch.autocast(
    device_type=device,
    dtype=torch.float16 if device == "cuda" else torch.bfloat16,
    enabled=device == "cuda",
):
    noise_pred = pipe.unet(noisy_latents, t, encoder_hidden_states=text_emb).sample
    loss = F.mse_loss(noise_pred.float(), noise.float())

print("loss:", float(loss))
```

---

## 6. Код: LoRA-инъекция вручную (без PEFT)

LoRA вводит low-rank обновление `W' = W + B·A·(alpha/r)`, базовые веса заморожены.

```python
import math
import torch
from torch import nn

class LoRALinear(nn.Module):
    def __init__(self, base: nn.Linear, r: int = 8, alpha: float = 16.0):
        super().__init__()
        self.base = base
        for p in self.base.parameters():
            p.requires_grad = False

        self.r = r
        self.scaling = alpha / r

        self.A = nn.Linear(base.in_features, r, bias=False)
        self.B = nn.Linear(r, base.out_features, bias=False)

        nn.init.kaiming_uniform_(self.A.weight, a=math.sqrt(5))
        nn.init.zeros_(self.B.weight)  # инициализация нулями → нет эффекта в начале

    def forward(self, x):
        return self.base(x) + self.B(self.A(x)) * self.scaling


def inject_lora_into_model(model: nn.Module,
                            name_keywords=("to_q", "to_k", "to_v", "to_out"),
                            r: int = 8, alpha: float = 16.0):
    """Заменяет целевые Linear слои на LoRALinear in-place."""
    for name, module in list(model.named_modules()):
        if isinstance(module, nn.Linear) and any(k in name for k in name_keywords):
            parent = model
            parts = name.split(".")
            for p in parts[:-1]:
                parent = getattr(parent, p)
            setattr(parent, parts[-1], LoRALinear(module, r=r, alpha=alpha))


# Использование:
# inject_lora_into_model(pipe.unet, r=8, alpha=16.0)
# Обучать только LoRA-параметры:
# trainable = [p for p in pipe.unet.parameters() if p.requires_grad]
```

**Целевые слои для LoRA в UNet:** `to_q`, `to_k`, `to_v`, `to_out` (projection'ы attention).

---

## 7. Код: Activation Checkpointing + AMP

```python
import torch
from torch import nn
from torch.utils.checkpoint import checkpoint

class BigBlock(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, 4 * dim),
            nn.GELU(),
            nn.Linear(4 * dim, dim),
        )
    def forward(self, x):
        return self.net(x)

block = BigBlock(4096).cuda()
opt = torch.optim.AdamW(block.parameters(), lr=1e-4)

x = torch.randn(8, 4096, device="cuda")
target = torch.randn(8, 4096, device="cuda")

scaler = torch.amp.GradScaler("cuda")

for step in range(10):
    opt.zero_grad(set_to_none=True)
    with torch.autocast(device_type="cuda", dtype=torch.float16):
        # checkpoint пересчитывает forward на backward → экономит память активаций
        y = checkpoint(block, x, use_reentrant=False)
        loss = torch.mean((y - target) ** 2)
    scaler.scale(loss).backward()
    scaler.step(opt)
    scaler.update()
    print(f"step {step}: loss={float(loss):.4f}")
```

**Трейдофф:** меньше VRAM ↔ больше compute (forward пересчитывается частично).

---

**Ссылки:**
- DDPM: https://arxiv.org/abs/2006.11239
- Improved DDPM: https://arxiv.org/abs/2102.09672
- EDM: https://arxiv.org/abs/2206.00364
- CFG: https://arxiv.org/abs/2207.12598
- LoRA (Diffusers): https://huggingface.co/docs/diffusers/en/training/lora
- PyTorch checkpointing: https://docs.pytorch.org/docs/stable/checkpoint.html
