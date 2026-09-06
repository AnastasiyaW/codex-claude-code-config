# Текст-энкодеры, замена и дата-пайплайн

## Table of contents
1. Роль текст-энкодера в диффузионном пайплайне
2. CLIP — как работает и почему frozen
3. SDXL multi-encoder fusion
4. Flux.2 [klein] с Qwen3 embedder
5. Замена энкодера: три проблемы
6. Минимальный скелет Qwen-адаптера
7. Дата-пайплайн: стриминг, шардинг, кэш

---

## 1. Роль текст-энкодера

В LDM/SD-классе текст-энкодер — не просто «какой-то вектор», а последовательность токен-эмбеддингов, **под которую обучены все cross-attention слои денойзера**.

```
Промпт → Токенизатор → Text Encoder → encoder_hidden_states (B, L, D)
                                              ↓
                                    Cross-attention в UNet/DiT
```

Размерности для SD1.x:
- `encoder_hidden_states`: `(B, 77, 768)` — CLIP ViT-L/14
- `cross_attention_dim` в UNet: `768`

---

## 2. CLIP — как работает и почему frozen

CLIP обучается контрастивной задачей «текст↔картинка» на больших web-парах. В SD-классе text encoder типично **заморожен** (frozen) — денойзер обучается под фиксированные эмбеддинги.

```python
import torch
from diffusers import StableDiffusionPipeline

device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if device == "cuda" else torch.float32

pipe = StableDiffusionPipeline.from_pretrained(
    "stable-diffusion-v1-5/stable-diffusion-v1-5",
    torch_dtype=dtype,
).to(device)

prompt = "фотореалистичный портрет, мягкий свет, 35mm"
tokens = pipe.tokenizer(
    [prompt],
    padding="max_length",
    max_length=pipe.tokenizer.model_max_length,  # 77 для CLIP
    truncation=True,
    return_tensors="pt",
).to(device)

with torch.no_grad():
    text_emb = pipe.text_encoder(**tokens).last_hidden_state  # (1, 77, 768)

print(text_emb.shape)  # torch.Size([1, 77, 768])

# Прямой вызов UNet с этими эмбеддингами
latents = torch.randn((1, 4, 64, 64), device=device, dtype=dtype)
timestep = torch.tensor([pipe.scheduler.timesteps[0]], device=device)
noise_pred = pipe.unet(latents, timestep, encoder_hidden_states=text_emb).sample
print(noise_pred.shape)  # (1, 4, 64, 64)
```

**Почему frozen важно:** если дообучать денойзер при незамороженном энкодере без тщательной настройки, энкодер деградирует и text alignment разрушается.

---

## 3. SDXL — multi-encoder fusion

SDXL использует **два** text encoder одновременно:
- OpenCLIP ViT/G (`hidden_size=1280`)
- CLIP ViT/L (`hidden_size=768`)

Эмбеддинги конкатенируются в `(B, 77, 2048)` для cross-attention. Refiner использует только OpenCLIP.

```python
from diffusers import StableDiffusionXLPipeline
import torch

pipe = StableDiffusionXLPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    torch_dtype=torch.float16,
).to("cuda")

# Под капотом pipe кодирует один промпт через оба энкодера
# и конкатенирует результаты перед подачей в UNet
image = pipe(
    prompt="professional photo of a red sports car",
    negative_prompt="blurry, low quality",
    num_inference_steps=30,
    guidance_scale=7.5,
).images[0]
```

**Паттерны multi-encoder fusion:**
- Конкатенация/слияние эмбеддингов → `(B, L, D1+D2)`
- Раздельные проекции K/V для cross-attention слоёв
- Смесь экспертов (MoE) на стороне conditioning

---

## 4. Flux.2 [klein] — Qwen3 embedder

Flux.2 [klein] 9B **построен** с Qwen3 text embedder как частью архитектуры — это не замена постфактум, а изначальный дизайн.

| Модель | Энкодер | Лицензия | Особенности |
|---|---|---|---|
| Flux.2 [klein] 4B | — | Apache 2.0 | Distilled, быстрее |
| Flux.2 [klein] 9B | Qwen3 8B | Non-commercial | Base, гибче, Qwen3-нативный |

```python
# Flux через Diffusers
from diffusers import FluxPipeline
import torch

pipe = FluxPipeline.from_pretrained(
    "black-forest-labs/FLUX.2-klein-4B",
    torch_dtype=torch.bfloat16,
).to("cuda")

image = pipe(
    prompt="A photo of a cat sitting on a red chair",
    num_inference_steps=4,   # distilled — мало шагов
    guidance_scale=3.5,
).images[0]
```

**Важно для 9B Base:** использовать рекомендованный scheduler из model card; Base-вариант лучше реагирует на изменение `guidance_scale` и числа шагов, чем distilled.

---

## 5. Замена энкодера: три проблемы

Если хочется заменить CLIP → другой (Qwen, T5, и т.п.) в уже обученной модели:

| Проблема | Симптом | Решение |
|---|---|---|
| **Размерность** | `cross_attention_dim` не совпадает с `hidden_size` нового энкодера | Projection head |
| **Семантика** | Денойзер обучен под CLIP-пространство; другая семантика → «текст игнорируется» | Дообучение cross-attention / LoRA-адаптер |
| **Токенизация** | Разные BPE/SentencePiece, разные max_length | Проверить токенизатор, пересчитать padding |

**Что реально работает:**
1. Multi-encoder fusion (SDXL-паттерн) — оба энкодера параллельно
2. Новый энкодер + projection + дообучение cross-attention/LoRA
3. Брать модель, где нужный энкодер **изначально** «вшит» (Flux.2 [klein] 9B с Qwen3)

---

## 6. Минимальный скелет Qwen-адаптера

Показывает механику projection без дообучения — для понимания «куда втыкается» адаптер.

```python
import torch
import torch.nn as nn
from transformers import AutoTokenizer, AutoModel
from diffusers import StableDiffusionPipeline

device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if device == "cuda" else torch.float32

pipe = StableDiffusionPipeline.from_pretrained(
    "stable-diffusion-v1-5/stable-diffusion-v1-5",
    torch_dtype=dtype,
).to(device)
pipe.unet.eval()

# Небольшой Qwen как источник hidden states
qwen_id = "Qwen/Qwen2.5-0.5B-Instruct"
qtok = AutoTokenizer.from_pretrained(qwen_id)
qmodel = AutoModel.from_pretrained(qwen_id, torch_dtype=dtype).to(device).eval()

# Проекция: Qwen hidden_size → SD cross_attention_dim
q_hidden = qmodel.config.hidden_size          # 896 для 0.5B
sd_dim = pipe.unet.config.cross_attention_dim  # 768 для SD1.x
proj = nn.Linear(q_hidden, sd_dim, bias=False).to(device, dtype=dtype)
# В продакшне: proj обучается вместе с LoRA-адаптерами cross-attention

prompt = "белая кружка на деревянном столе, мягкий свет"
qt = qtok([prompt], return_tensors="pt", padding=True, truncation=True).to(device)

with torch.no_grad():
    q_h = qmodel(**qt).last_hidden_state   # (1, L, q_hidden)
    enc_h = proj(q_h)                      # (1, L, sd_dim)

    latents = torch.randn((1, 4, 64, 64), device=device, dtype=dtype)
    t = torch.tensor([pipe.scheduler.timesteps[0]], device=device)
    noise_pred = pipe.unet(latents, t, encoder_hidden_states=enc_h).sample
    print(noise_pred.shape)
# Без дообучения качества не будет — только скелет для понимания
```

---

## 7. Дата-пайплайн

### Стриминг (HF Datasets)

```python
from datasets import load_dataset
import torch
from torch.utils.data import DataLoader

# Стриминг — не скачивает весь датасет
ds = load_dataset("laion/laion-high-resolution", split="train", streaming=True)

# Перемешивание буфером (shuffle на лету)
ds = ds.shuffle(seed=42, buffer_size=10_000)

# Фильтрация и маппинг
ds = ds.filter(lambda x: x["width"] >= 512 and x["height"] >= 512)
ds = ds.map(lambda x: {"text": x["caption"], "url": x["url"]})

# Start with one process.  Before raising this above zero, shard the iterable
# per worker and measure throughput/RAM on the target OS; Windows uses spawn.
num_workers = 0
loader_kwargs = {
    "batch_size": 8,
    "num_workers": num_workers,
    "pin_memory": torch.cuda.is_available(),
}
if num_workers > 0:
    loader_kwargs.update(prefetch_factor=2, persistent_workers=True)
loader = DataLoader(ds.with_format("torch"), **loader_kwargs)
```

### WebDataset — TAR-шарды для больших корпусов

```python
import webdataset as wds
from torchvision import transforms

# Список шардов (URL или локальные пути)
shards = "s3://my-bucket/dataset/shard-{000000..000999}.tar"

transform = transforms.Compose([
    transforms.Resize(512),
    transforms.CenterCrop(512),
    transforms.ToTensor(),
    transforms.Normalize([0.5], [0.5]),
])

dataset = (
    wds.WebDataset(shards, resampled=True)  # бесконечный, с ресемплингом
    .shuffle(1000)
    .decode("pil")
    .to_tuple("jpg", "txt")
    .map_tuple(transform, lambda x: x)
    .batched(8, partial=False)
)

# Profile workers and pinning on the target runtime; this is the safe baseline.
loader = wds.WebLoader(dataset, num_workers=0, pin_memory=torch.cuda.is_available())
```

### Кэширование text embeddings

При замороженном text encoder можно предвычислить эмбеддинги один раз:

```python
import torch
from pathlib import Path

def cache_text_embeddings(pipe, captions: list[str], cache_dir: str):
    """Кэширует CLIP-эмбеддинги в .pt файлы."""
    cache_path = Path(cache_dir)
    cache_path.mkdir(exist_ok=True)

    pipe.text_encoder.eval()
    for i, cap in enumerate(captions):
        out_file = cache_path / f"{i:08d}.pt"
        if out_file.exists():
            continue
        tokens = pipe.tokenizer(
            [cap], padding="max_length",
            max_length=pipe.tokenizer.model_max_length,
            truncation=True, return_tensors="pt",
        ).to(pipe.device)
        with torch.no_grad():
            emb = pipe.text_encoder(**tokens).last_hidden_state.cpu()
        torch.save(emb, out_file)
```

**Когда кэшировать:** энкодер заморожен + датасет фиксированный. Не кэшировать если есть caption augmentation или CFG-dropout кондиций.

---

**Ссылки:**
- HF Datasets streaming: https://huggingface.co/docs/datasets/en/stream
- WebDataset: https://github.com/webdataset/webdataset
- SDXL card (dual encoder): https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0
- FLUX.2 [klein] 4B: https://huggingface.co/black-forest-labs/FLUX.2-klein-4B
- FLUX.2 [klein] 9B: https://huggingface.co/black-forest-labs/FLUX.2-klein-9B
- Qwen3 Embedding: https://huggingface.co/Qwen/Qwen3-Embedding-8B
