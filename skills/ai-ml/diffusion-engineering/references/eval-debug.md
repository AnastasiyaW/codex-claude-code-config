# Оценка, траблшутинг и юридика

## Table of contents
1. Метрики качества
2. Типовые поломки и фиксы
3. Диагностика по симптому
4. Лицензии и данные
5. Production чеклист

---

## 1. Метрики качества

| Метрика | Что измеряет | Ограничения |
|---|---|---|
| **FID** | Расстояние Фреше между реальным и сгенерированным распределением (через Inception фичи) | Чувствителен к числу семплов; не гарантирует соблюдение промптов |
| **IS (Inception Score)** | Качество + разнообразие через предсказания Inception | Плохо коррелирует с human preference; не учитывает reference |
| **CLIPScore** | Text↔image согласованность через CLIP cosine sim | Reference-free; не заменяет human eval для мелких деталей и текста на изображении |
| **LPIPS** | Перцептивное сходство патчей (коррелирует с human preference) | Нужен reference; не подходит для T2I без парных данных |
| **Human rating** | Прямая оценка людьми | Дорого, медленно, нужна стандартизация |

**Выбор по задаче:** FID сравнивает распределения, CLIPScore — соответствие текста и изображения, LPIPS — перцептивную разницу с reference. Ни одна из них сама по себе не доказывает качество ретуши, сохранность личности или отсутствие швов. Зафиксировать набор данных, preprocessing, версии метрик и принятую границу качества до сравнения кандидатов. Размер выборки обосновывать стабильностью оценки и риском решения, не универсальным порогом.

### Быстрая оценка через torchmetrics

```python
import torch
from torchmetrics.image.fid import FrechetInceptionDistance
from torchmetrics.multimodal import CLIPScore

device = "cuda" if torch.cuda.is_available() else "cpu"

# API illustration only: random tensors below are not a quality evaluation.
# A real FID comparison needs a justified sample size and matched preprocessing.
fid = FrechetInceptionDistance(feature=2048, normalize=True).to(device)

# Добавляем реальные и сгенерированные изображения
real_images = torch.rand(8, 3, 299, 299).to(device)   # float32, [0,1]
fake_images = torch.rand(8, 3, 299, 299).to(device)

fid.update(real_images, real=True)
fid.update(fake_images, real=False)
print(f"FID: {fid.compute():.2f}")  # ниже = лучше

# CLIPScore
clip_score = CLIPScore(model_name_or_path="openai/clip-vit-base-patch32").to(device)

prompts = ["a red car at night", "a white cat on a table"]
images_uint8 = (fake_images[:2] * 255).to(torch.uint8)  # CLIPScore ожидает uint8
score = clip_score(images_uint8, prompts)
print(f"CLIPScore: {float(score):.3f}")  # выше = лучше
```

### «Дневник промптов» для overfitting

```python
# Фиксированный набор промптов для мониторинга в процессе FT
EVAL_PROMPTS = [
    "a photo of sks person smiling",        # target subject
    "a photo of sks person in the park",    # generalization
    "a photo of a random person smiling",   # prior preservation
]

# Запускать каждые N шагов, сохранять с одинаковым seed
generator = torch.Generator(device="cpu").manual_seed(42)
```

---

## 2. Типовые поломки и фиксы

### NaN / взрыв loss

```python
# Симптом: loss = nan или inf после нескольких шагов

# Диагностика — добавить hook для поиска первого NaN
def check_nan_hook(module, input, output):
    if isinstance(output, torch.Tensor) and torch.isnan(output).any():
        raise RuntimeError(f"NaN in {module.__class__.__name__}")

# Регистрировать на подозрительных слоях:
# model.some_layer.register_forward_hook(check_nan_hook)

# Типичные причины и фиксы:
# 1. Слишком высокий LR → снизить в 5–10×
# 2. FP16 underflow → переключиться на BF16 или проверить GradScaler
# 3. Нормализация входа → убедиться что латенты умножены на scaling_factor
# 4. gradient clipping отсутствует → добавить max_norm=1.0

scaler = torch.amp.GradScaler("cuda")
with torch.autocast("cuda", torch.float16):
    loss = model(batch)
scaler.scale(loss).backward()
scaler.unscale_(optimizer)
torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
scaler.step(optimizer)
scaler.update()
```

### «Модель игнорирует текст»

```python
# Симптом: генерации не соответствуют промпту при любом guidance_scale

# Причина 1: слишком низкий guidance_scale (≤1.0)
image = pipe(prompt, guidance_scale=7.5, ...)  # поднять до 5–10

# Причина 2: несогласованный text encoder после замены
# Симптом + замена энкодера → нужен projection + дообучение cross-attention
# Решение: сначала проверить что CLIP-эмбеддинги работают корректно

# Диагностика: visualize attention maps
from diffusers.utils import get_attention_store

# Причина 3: text encoder заморожен некорректно, веса деградировали
# Проверить: pipe.text_encoder.training должен быть False
print(pipe.text_encoder.training)  # должно быть False
```

### Потеря разнообразия / «пережог»

```python
# Симптом: все генерации похожи, цвета «кричащие», артефакты при высоком CFG

# Фиксы:
# 1. Снизить guidance_scale
for gs in [3.5, 5.0, 6.5, 7.5, 9.0]:
    img = pipe(prompt, guidance_scale=gs, generator=torch.Generator().manual_seed(42)).images[0]
    img.save(f"gs_{gs}.png")

# 2. Сменить scheduler / увеличить шаги
from diffusers import DPMSolverMultistepScheduler
pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
img = pipe(prompt, num_inference_steps=20, guidance_scale=6.0).images[0]
```

### Шум / «грязь» за мало шагов

```python
# Симптом: артефакты и шум при num_inference_steps < 15

# Для distilled моделей (Flux klein distilled) — мало шагов это норма
# Для base моделей — нужно больше шагов

# Переключение с distilled → base для гибкости
# Или: выбрать DPM-Solver++ — хорошее качество за 10–20 шагов
from diffusers import DPMSolverMultistepScheduler
pipe.scheduler = DPMSolverMultistepScheduler.from_config(
    pipe.scheduler.config,
    algorithm_type="dpmsolver++",
    solver_order=2,
)
img = pipe(prompt, num_inference_steps=15).images[0]
```

### OOM (Out of Memory)

```python
# Порядок включения оптимизаций по нарастающей:
# 1. BF16/FP16
pipe = pipe.to(torch.bfloat16)

# 2. Enable attention slicing
pipe.enable_attention_slicing()

# 3. xFormers
pipe.enable_xformers_memory_efficient_attention()

# 4. Тiled VAE (для высоких разрешений)
pipe.vae.enable_tiling()
pipe.vae.enable_slicing()

# 5. CPU offload (медленнее)
pipe.enable_sequential_cpu_offload()  # максимальная экономия
# или
pipe.enable_model_cpu_offload()       # баланс speed/memory

# 6. 4-bit quantization
from diffusers import BitsAndBytesConfig
bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16)
```

---

## 3. Диагностика по симптому

| Симптом | Первое что проверить | Быстрый фикс |
|---|---|---|
| loss = NaN | LR слишком высокий / FP16 underflow | LR ÷10; переключить BF16; добавить grad clip |
| Текст игнорируется | guidance_scale ≤ 1; несовместимый энкодер | guidance_scale → 6–8; проверить frozen encoder |
| Все картинки похожи | guidance_scale слишком высокий | guidance_scale → 4–6; смена scheduler |
| Артефакты при малых шагах | Неподходящий scheduler | DPM-Solver++ или Euler 20–25 шагов |
| OOM при обучении | Нет AMP / batch слишком большой | BF16 + grad_accum + checkpointing |
| OOM при инференсе | Нет оптимизации памяти | attention_slicing + CPU offload |
| Overfitting при FT | Слишком много шагов / высокий LR | LoRA с меньшим rank; prior preservation loss |
| Slow dataloader | Замер I/O, decode, RAM и GPU idle; baseline `num_workers=0` | A/B числа workers/prefetch на данном runtime; persistence только при workers > 0, проверить отсутствие дублей iterable dataset |

---

## 4. Лицензии и данные

### Модели — проверять перед продакшном

| Модель | Лицензия | Ключевые ограничения |
|---|---|---|
| SD v1.5 | CreativeML OpenRAIL-M | Ограничения на вредоносный контент; attribution required |
| SDXL | OpenRAIL++-M | Аналогично; проверить условия коммерческого использования |
| Flux.2 [klein] 4B | Apache 2.0 | Свободное коммерческое использование |
| Flux.2 [klein] 9B Base | Non-commercial | Только исследования/некоммерческое |

### Данные — provenance обязательна

- SD-класс обучался на подмножестве LAION-корпусов
- Для production: **документированная provenance данных**
- Фильтрация: безопасность контента, авторские права, PII
- Политика удаления проблемных примеров (не опция, а часть production)

```python
# Проверить лицензию модели программно
from huggingface_hub import model_info

info = model_info("stable-diffusion-v1-5/stable-diffusion-v1-5")
print(info.card_data.license)  # creativeml-openrail-m
```

---

## 5. Production чеклист

### Качество
- [ ] Каждая проверка связана с принятым требованием: distribution, prompt alignment, paired fidelity или конкретный дефект; нерелевантные метрики не обязательны
- [ ] Для edit/ретуши: фиксированные пары и проверки нужных деталей, границ, личности/геометрии/цвета, где это требуется задачей
- [ ] Объём и протокол A/B/визуальной приёмки обоснованы риском; нет универсального минимума пар или семплов
- [ ] Фиксированные данные/промпты + seed позволяют сравнение; held-out набор не используется для подбора кандидата

### Стабильность обучения
- [ ] AMP (BF16 предпочтительно) включён
- [ ] Gradient clipping: `max_norm=1.0`
- [ ] LR schedule задан (cosine / constant with warmup)
- [ ] EMA весов для инференса (если full FT)
- [ ] Checkpoint сохраняется каждые N шагов с eval метриками

### Данные
- [ ] Стриминг/шардинг для больших корпусов
- [ ] DataLoader измерен на целевой ОС/данных: выбрать workers и pinning по throughput/RAM; `num_workers=0` допустим. При multiprocessing проверить Windows spawn и шардирование iterable dataset; persistence/prefetch требуют подходящего режима
- [ ] Text embeddings кэшированы (если frozen encoder)
- [ ] Validation split отделён до начала обучения

### Инференс
- [ ] Scheduler выбран через A/B на фиксированных seed
- [ ] `guidance_scale` подобран (5–8 для большинства задач)
- [ ] Memory optimizations включены по нужде
- [ ] NSFW/safety фильтры применены (если публичный продукт)

### Лицензии
- [ ] Лицензия базовой модели проверена для целевого use case
- [ ] Provenance обучающих данных задокументирована
- [ ] Политика удаления примеров описана

---

**Ссылки:**
- FID: https://arxiv.org/abs/1706.08500
- IS: https://arxiv.org/abs/1606.03498
- CLIPScore: https://arxiv.org/abs/2104.08718
- LPIPS: https://arxiv.org/abs/1801.03924
- torchmetrics FID: https://torchmetrics.readthedocs.io/en/stable/image/frechet_inception_distance.html
- Diffusers memory optimization: https://huggingface.co/docs/diffusers/en/optimization/memory
- PyTorch DataLoader (profile, multiprocessing, Windows): https://docs.pytorch.org/docs/2.14/data.html (checked 2026-09-06; use the installed version's docs when implementing)
- SD v1.5 license: https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5
- SDXL license: https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0
