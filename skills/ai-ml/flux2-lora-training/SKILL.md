---
name: flux2-lora-training
description: Plan or review LoRA and edit-training work specifically for FLUX.2 Klein or Qwen-Image-Edit, including paired datasets, trainer-version contracts, and held-out fidelity checks. Do not use for generic Stable Diffusion/DiT training, prompt authoring, or model serving; route those tasks to their specialized skill.
---

# FLUX.2 Klein 9B — LoRA Training Reference

## Evidence boundary

This file is a route to evaluate a training plan, not a tested recipe. Model
cards establish model identity and license; trainer repositories establish only
the behavior of their pinned version. Numeric settings and BFS notes below are
historical local experiment candidates unless an exact source is linked. Before
training, record the model revision, trainer commit, dataset contract, hardware,
and a small held-out acceptance set. Do not promote a historical score, memory
estimate, slot order, or private result into a universal default.

## Архитектура моделей

### FLUX.2 Klein — Rectified Flow Transformer (DiT)

| Параметр | Klein 9B | Klein 4B | Qwen-Image-Edit | FLUX.1 dev |
|---------|---------|---------|---------|---------|
| Blocks | 32 (8+24) | 25 (5+20) | 60 (MM-DiT) | 56 (8+48) |
| Embedding dim | 12,288 | 7,680 | — | 15,360 |
| VAE latent channels | **32** (128 packed features) | 32 (128 packed features) | verify the exact revision | **16** |
| Text encoder | Qwen3 (bundled) | Qwen3 | Qwen2.5-VL (7B) | Mistral-Small-3.1 |
| Guidance embeddings | **НЕТ** | НЕТ | — | Есть |
| Total params | 9B | 4B | **20B DiT + 7B VL** | 12B |

**FLUX.2 Klein VAE:** `AutoencoderKLFlux2`, **32 latent channels** (FLUX.1: 16) → после 2×2 patch packing в трансформере: 32×4 = **128 dims per token**, 16× spatial compression. **Несовместим с FLUX.1 LoRA** — другой VAE, другой latent space. Tiling для больших разрешений: 1024px тайлы с 25% overlap, обрабатывает произвольное разрешение.

**Klein editing механизм (Kontext-style):** reference image VAE-кодируется и конкатенируется с noise latent вдоль sequence dim. Positional embeddings разделяют reference и output через **3D RoPE time offsets** (ref1=t:1, ref2=t:2, output=t:0). Поддерживает до 10 reference images теоретически, обучен на 2.

**Text encoder Klein:** Qwen3 (встроен в 9B), выходы из слоёв 9, 18, 27.

Do not assume a trainer’s `flux_guidance_*` fields are no-ops or active from
their names. Verify their behavior against the pinned trainer release and the
selected model before relying on them.

**Для LoRA тренировки: base модель** `FLUX.2-klein-base-9B`, не distilled 4-step.

---

### Qwen Image Edit 2511 — MMDiT с dual encoding

Архитектурно совершенно другая модель. **20B MMDiT** (Multimodal DiT) + **Qwen2.5-VL 7B** как visual-language encoder.

**Dual encoding** — ключевое отличие от Klein:
```
Входное изображение →┬→ Qwen2.5-VL 7B → семантические фичи (кто/что/стиль)
                     └→ VAE encoder   → reconstructive latent (текстуры/пиксели)
                                ↓ оба пути сходятся в MMDiT
```

This is an architectural interpretation, not a measured cross-model guarantee.
Assess identity preservation on the task’s held-out images rather than claiming
that one model drifts less at an equal LoRA rank.

**Consistency Mode** (`qe2511_consis_alpha`) — результат I2I reconstruction training objective: модель дообучена реконструировать входное изображение без изменений. Это выравнивает VL и DiT latent spaces, делая консервативные правки более точными. Триггер `restore image details` активирует этот bias.

**LoRA target modules для Qwen-Image-Edit-2511** (13 модулей, в отличие от Klein):
```
to_q, to_k, to_v, to_out.0
add_q_proj, add_k_proj, add_v_proj, to_add_out
img_mlp.net.2    ← image-specific FFN (в Klein нет разделения)
img_mod.1        ← image AdaLayerNorm modulation
txt_mlp.net.2    ← text-specific FFN
txt_mod.1        ← text modulation
linear_in, linear_out
```

**Qwen нативно поддерживает 3 control image слота** (control_1, control_2, control_3) через sequence concatenation + MSRoPE.

---

## Edit LoRA (before/after): датасет и тренировка

### Датасет (ai-toolkit формат)

```
dataset/
  control_1/    ← "before" изображение (источник)
  control_2/    ← опциональный 2-й референс (напр., лицо донора)
  targets/      ← "after" изображение (результат)
  captions/     ← .txt файл с инструкцией на сэмпл
```

**Критично:** имена файлов должны совпадать между папками (`0001.png ↔ 0001.png ↔ 0001.txt`).

Do not infer `folder_path`/`control_path_1` semantics from issue #536 or PR
#629. The primary records do not establish a reversed-path bug: #536 was
closed as not planned, while #629 fixes Flux2 training that ignored a *single*
control image. Pin the trainer commit and run a small non-production fixture
that proves which input becomes which control/target before a training job.
Sources: https://github.com/ostris/ai-toolkit/issues/536 and
https://github.com/ostris/ai-toolkit/pull/629

**Порядок входных изображений важен.** Для BFS Head Swap:
- V1–V2: `[face, body]`
- **V3+: `[body, face]`** — инвертирование порядка дало значительный прирост качества

**Historical BFS observation:** the recorded dataset counts are not a minimum or
maximum for another edit. Start from a representative, consented dataset and
use held-out fidelity/attribute checks to decide whether more diversity or
cleaner pairs are needed.

### zero_cond_t — ключевой параметр

`zero_cond_t` трактует control images как чистые референсы при t=0, пока основное изображение следует нормальному diffusion schedule. Предотвращает identity drift.

Use it only when the pinned trainer and inference implementation document the
field; then keep train/inference conditioning consistent and verify it on a
held-out edit. It is not a universal Qwen-Image-Edit switch.

### Trigger word

Trigger ОБЯЗАТЕЛЬНО ставить в **user message** (slot `prompt`), НЕ в system/instruction message. LoRA-триггеры обучаются в user message контексте. Это объясняет почему в head swap воркфлоу `head_swap:` идёт в `prompt`, а не в `instruction`.

---

## Гиперпараметры и конфиги

### ai-toolkit (Klein 9B) — рекомендуется для edit LoRA

```yaml
learning_rate: 1e-4          # снизь до 5e-5 при нестабильности
batch_size: 1
gradient_accumulation: 1-4
lora_rank: 16-32             # стандарт; 64-128 для сложных edits
steps: 2000-6000             # зависит от датасета
save_every: 250-500
optimizer: adamw8bit
dtype: bf16
noise_scheduler: flowmatch
```

**BFS Head Swap для Klein 9B конкретно:**
- rank: 128 (начало), 64 (позже)
- steps: 3500–3750
- Curriculum resolution: начинал с 256/512px → прогрессивно до 1024/1536

### DiffSynth-Studio

```bash
python train.py \
  --learning_rate 1e-4 \
  --epochs 5 \
  --lora_rank 32 \
  --max_pixels 1048576  # 1024×1024
```

LoRA target modules (24 transformer blocks):
```
to_q, to_k, to_v, to_out.0,
add_q_proj, add_k_proj, add_v_proj, to_add_out,
linear_in, linear_out, to_qkv_mlp_proj
```

Полный fine-tune скрипт: `examples/flux2/model_training/full/FLUX.2-klein-base-9B.sh`

### SimpleTuner (Klein 9B)

```json
{
  "model_family": "flux2",
  "model_flavour": "klein-9b",
  "base_model_precision": "int8-quanto",
  "lora_rank": 16,
  "learning_rate": 1e-4,
  "lr_scheduler": "constant",
  "flux_guidance_mode": "constant",
  "flux_guidance_value": 1.0,
  "gradient_checkpointing": true
}
```

VRAM: ~14GB (int8-quanto), ~22GB (bf16).

### 50+ training runs (Calvin Herbst, Feb 2026)

Что реально работает:
- `linear: 128, linear_alpha: 64, conv: 64, conv_alpha: 32` → улучшает в почти каждом тесте
- `lr: 0.000095`, `timestep_type: shift`, `weight_decay: 0.00015`
- Более высокий rank = более чёткие детали, более естественный grain

---

## Инпеинтинг LoRA

### Подход 1: ostris "Green Screen" (проще всего)

Обучаешь модель на парах где маскированные области закрашены **чистым зелёным (RGB 0, 255, 0)**.
Модель учит: зелёный = "перегенерировать эту область по тексту".

- Использует существующий `control_image` slot в ai-toolkit — **не нужна модификация архитектуры**
- Inference: красишь область зелёным, пишешь промпт что должно быть
- Модель: `ostris/qwen_image_edit_inpainting` на HuggingFace
- При тренировке: normal t2i dropout для generalization, random inpaint blobs по умолчанию

### Подход 2: SimpleTuner mask conditioning (PR #2520, merged Jan 29, 2026)

`mask_conditioning_type` — добавляет proper mask-conditioned training для FLUX.2 Klein.
Подходит для более строгого контроля маски.

### Чего НЕ делать

**FLUX.1-Fill approach** (concatenated latents, 16+16+64 channels) требует полной модификации архитектуры модели — **не реализуемо как LoRA.** Нужен full fine-tune с добавлением input channels.

---

## Тренировка на больших разрешениях (1024 → 1536 → 2048)

Klein официально поддерживает 64×64 до **4MP (2048×2048)**, dimensions кратны 16.

### DiffSynth-Studio: изменить `--max_pixels`

| Разрешение | max_pixels |
|------------|------------|
| 1024×1024 (1MP) | `1048576` |
| 1536×1536 | `2359296` |
| 2048×2048 (4MP) | `4194304` |

Нет архитектурных ограничений — Klein использует RoPE (resolution-agnostic).

### Память на H200 (140GB)

| Разрешение | VRAM (bf16) | Оптимизации |
|------------|-------------|-------------|
| 1024×1024 | ~22GB | базовые |
| 1536×1536 | 40–80GB+ | grad_checkpoint + fp8 + 8bit adam |
| 2048×2048 | 80GB+ | все + cache_latents |

H200 (140GB) комфортно берёт 1536 с оптимизациями.

### Curriculum learning (метод BFS)

**Начинай с маленького разрешения (256–512px), постепенно увеличивай.**
Прыжок сразу на 1536 может вызвать нестабильность. Kohya-ss задокументировали деградацию likeness при >1024px без curriculum подхода.

### SimpleTuner bucketing

```json
{
  "resolution_type": "pixel_area",
  "crop_aspect": "square",
  "crop_style": "center"
}
```

`crop_aspect: square` — наиболее надёжный вариант для multi-aspect.

---

## Расширение latent space / checkpoint fine-tune

**Нет опубликованных методов расширения native resolution Klein через checkpoint fine-tuning** (на март 2026).

На практике это **не нужно** — Klein уже генерирует до 4MP нативно.

Если всё же нужен "latent expansion":
- Просто тренируй на большем `--max_pixels` через DiffSynth-Studio full fine-tune
- Теоретически применимы RoPE scaling техники (YaRN, NTK-aware) из LLM мира, но требуют данных на целевом разрешении

**Full checkpoint fine-tune скрипт:** `examples/flux2/model_training/full/FLUX.2-klein-base-9B.sh` (DiffSynth-Studio)

---

## Сравнение фреймворков

| Фреймворк | Klein 9B | Edit LoRA | Inpaint | Multi-Aspect | Заметки |
|-----------|----------|-----------|---------|--------------|---------|
| **ai-toolkit** | Да | Да (native) | Green screen | Ограничено | Лучший для edit LoRA |
| **SimpleTuner** | Да | Частично (PR#2520) | Mask conditioning | Да (с нюансами) | Лучшая документация |
| **DiffSynth-Studio** | Да | Да (ICEdit format) | Не задокументировано | Да (dynamic) | Поддерживает full fine-tune |
| **fal.ai trainer** | Да (hosted) | Да (Qwen 2511) | Нет | Нет | Cloud, проще всего |
| **kohya-ss** | Ограничено | Нет | Нет | Да | Нестабильно для Klein |

**Рекомендация для edit LoRA (head swap, face swap):** ai-toolkit + base модель.

---

---

## Тайловая обработка крупных изображений (tile-as-video)

### Проблема
Банальная тайловая обработка через ComfyUI-TiledDiffusion даёт **цветовые скачки** между тайлами: каждый тайл генерируется независимо без знания соседей.

### Решение: Kontext-style sequence concatenation (без обучения)

Klein нативно поддерживает произвольное число reference images через sequence concatenation + 3D RoPE. Это можно использовать для тайлов:

```
Tile 1 (обработан) → reference_1
Tile 2 (обработан) → reference_2
Tile 3 (текущий)   → output (Klein видит соседей при генерации)
```

**Практический порядок обхода (BFS-style):**
1. Обработать угловой тайл (нет соседей → reference пустой)
2. Обработать тайлы по периметру (1 сосед как reference)
3. Обработать внутренние тайлы (2-3 соседних тайла как references)

Это работает за счёт того, что Klein использует те же RoPE time offsets что и для head swap: `ref1=t:1, ref2=t:2, output=t:0`. Тайлы по-сути становятся "видеокадрами" в пространстве последовательности.

### Существующие подходы для tiled diffusion

| Метод | Где | Принцип | Для FLUX/DiT |
|-------|-----|---------|-------------|
| **MultiDiffusion** | ComfyUI-TiledDiffusion | Усреднение latents в overlapping зонах | Работает (базовый) |
| **SyncDiffusion** | отдельно | LPIPS loss для согласованности цветов | Нет реализации для Klein |
| **SpotDiffusion** | ComfyUI-TiledDiffusion | Shifting windows, снижает артефакты | Лучший из TiledDiffusion |
| **DemoFusion** | отдельно | Progressive upscaling + skip residuals | Нет для Klein |
| **DyPE** | отдельно | Training-free 16MP для FLUX | Только для FLUX.1 |
| **Scale-DiT** | arxiv:2501.12900 | LoRA для масштабирования DiT | Обучается |
| **Kontext-concat** | нативно в Klein | Соседние тайлы как references | **Лучший** |

### Практический ComfyUI пайплайн

```
Большое изображение (напр. 3072×2048)
  ↓
VAEEncodeTiled (1024px тайлы, 25% overlap)
  ↓
Для каждого тайла:
  [уже_обработанные_соседи] → LoadImage → reference_1, reference_2
  [текущий_тайл]            → noise latent
  Klein KSampler с 2 references
  ↓
VAEDecodeTiled
  ↓
Stitch с Gaussian blending в зонах overlap
```

**Ключевые ноды:** `ComfyUI-TiledDiffusion` (SpotDiffusion режим), `VAEEncodeTiled`, `VAEDecodeTiled`.

### Почему circular convolution НЕ работает для Klein

FLUX.1/Klein трансформер не содержит conv слоёв в основной части — только attention и MLP. Circular padding применимо **только к VAE** (там есть conv), но не к самому DiT. Поэтому бесшовных панорам через circular padding не получить — используй StitchDiffusion LoRA.

### Когда нужен тайлинг vs когда нет

| Сценарий | Решение |
|---------|---------|
| Изображение ≤ 4MP | Klein напрямую (поддерживает до 2048px нативно) |
| Изображение > 4MP | VAEEncodeTiled + SpotDiffusion |
| Панорама (seamless) | StitchDiffusion LoRA + wrap padding в VAE |
| Batch крупных продуктовых кадров | Тайлинг с Kontext-соседями |

---

## Мульти-референс тренировка (2 входа → 1 выход)

### Нужна ли модификация архитектуры?

**Нет.** Qwen-Image-Edit-2509/2511 уже нативно поддерживает 2 control image слота. Для head swap (body + face → result) архитектурных изменений не требуется:

```
dataset/
  control_1/   ← BODY (поза, одежда, окружение)
  control_2/   ← FACE (лицо донора)
  targets/     ← RESULT (голова пересажена)
  captions/    ← "head_swap: ..."
```

Порядок слотов критичен и должен быть консистентным во всём датасете.

### Расширение до 3 слотов (body + face + pose map)

Только добавление `control_3/` папки + новый time offset в position embeddings (t=3). **Веса трансформера не меняются.** Это уже поддерживается в Qwen-Image-Edit нативно.

### Строгий attribute masking (без attribute leakage)

Проблема 2-slot LoRA: модель иногда берёт волосы с body вместо face. Решения:

**A) Текстовые якоря** (текущий подход): явно в промпте "hair MUST match Picture 2", повторить 2-3 раза в разных формулировках.

**B) FuseAnyPart-style adapter** (arxiv:2410.22771): отдельный lightweight adapter принимает masked_face + masked_body → combined conditioning. Жёсткое маскирование на уровне латентов. Требует нового компонента поверх модели.

**C) ACE++ (arxiv:2501.02487)**: Long-context Condition Unit — все conditioning images (reference + mask + output) конкатенируются в единый extended sequence. Two-stage training: сначала 0-ref, потом multi-ref задачи.

### Что нужно изменить в датасете vs 1-input → 1-output

| Аспект | 1-input | 2-input (head swap) |
|--------|---------|---------------------|
| Датасет | (source, target) пары | (body, face, result) триплеты |
| Синтетика | Можно генерировать | Нужны реальные результаты head swap как GT |
| Caption | Общая инструкция | Явные ссылки на "image 1" и "image 2" |
| Порядок | Не критичен | Строго: body=control_1, face=control_2 |
| zero_cond_t | Желательно | Обязательно (иначе references зашумляются) |

---

## Известные проблемы

| Проблема | Причина | Решение |
|---------|---------|---------|
| Модель учит трансформацию в обратную сторону | Семантика control/target не подтверждена для закреплённой версии trainer | Зафиксировать commit и проверить малым control/target fixture до training job |
| LyCORIS создаёт 0 модулей | Key mismatch с Klein architecture | Использовать стандартный LoRA format |
| SimpleTuner зависает на RTX 5090 | Issue #2477 | Fallback на H200 |
| Деградация likeness при >1024px | Прямой jump на высокое разрешение | Curriculum: 256→512→1024→1536 |
| identity drift при editing | zero_cond_t не включён | Включить и при тренировке, и при inference |
| Attribute leakage (волосы с body вместо face) | 2-slot LoRA не имеет жёсткого mask control | Текстовые якоря ИЛИ FuseAnyPart adapter |

---

## Источники

- **BFL официальная документация:** https://docs.bfl.ml/flux_2/flux2_klein_training
- **ai-toolkit:** https://github.com/ostris/ai-toolkit
- **SimpleTuner FLUX2:** https://github.com/bghira/SimpleTuner/blob/main/documentation/quickstart/FLUX2.md
- **DiffSynth-Studio training scripts:** https://github.com/modelscope/DiffSynth-Studio/blob/main/examples/flux2/model_training/
- **BFS Head Swap LoRA:** https://huggingface.co/Alissonerdx/BFS-Best-Face-Swap
- **ostris inpainting LoRA:** https://huggingface.co/ostris/qwen_image_edit_inpainting
- **50+ training runs research:** https://medium.com/@calvinherbst/50-flux-2-klein-lora-training-runs-dev-and-klein-to-see-what-config-parameters-actually-matter-3196e4f64fd5
- **FLUX.1 Kontext paper** (тот же conditioning mechanism): https://hf.co/papers/2506.15742
- **Qwen-Image Technical Report:** https://hf.co/papers/2508.02324
- **FuseAnyPart** (mask-guided multi-ref): https://arxiv.org/abs/2410.22771
- **ACE++ multi-task editing FLUX**: https://arxiv.org/abs/2501.02487
- **DiffSynth-Studio Qwen-Image-Edit-2511 training**: https://github.com/modelscope/DiffSynth-Studio/blob/main/examples/qwen_image/model_training/lora/Qwen-Image-Edit-2511.sh
