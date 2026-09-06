# VLM и Сегментационные Модели: Справочник

## Архитектурные типы и выбор

### Promptable Segmentation/Tracking
**SAM3** (2025, SAM License, gated, 848M params)
- Детектор (DETR-based) + трекер (SAM2-style) + общий vision encoder
- PCS: текстовый промпт/exemplars → все инстансы концепта (маски + боксы + scores)
- PVS: точки/боксы/маски → конкретный объект → трекинг по видео
- BF16 для инференса; streaming и pre-loaded режимы видео
- Gated: нужно принять лицензию на HF + токен

```python
from transformers import Sam3Processor, Sam3Model
model = Sam3Model.from_pretrained("facebook/sam3").to(device)
processor = Sam3Processor.from_pretrained("facebook/sam3")
inputs = processor(images=image, text="ear", return_tensors="pt").to(device)
with torch.no_grad():
    outputs = model(**inputs)
results = processor.post_process_instance_segmentation(
    outputs, threshold=0.5, mask_threshold=0.5,
    target_sizes=inputs.get("original_sizes").tolist()
)[0]
masks = results["masks"]   # [N, H, W]
boxes = results["boxes"]   # [N, 4] xyxy
scores = results["scores"] # [N]
```

**SAM2.1** (2024, Apache-2.0)
- Streaming memory для видео; промпты: точки/боксы/маски
- Размеры и FPS на A100: tiny 38.9M/91.2, small 46M/84.8, base+ 80.8M/64.1, large 224.4M/39.5
- Официальный training+fine-tuning код опубликован
- Полезен как генератор масок/псевдоразметки и backbone для доменной адаптации

```python
from transformers import pipeline
generator = pipeline("mask-generation", model="facebook/sam2.1-hiera-large", device=0)
outputs = generator("https://...", points_per_batch=64)
```

**EdgeTAM** (2025, Apache-2.0)
- On-device вариант SAM2; 16 FPS на iPhone 15 Pro Max без квантования
- CoreML экспорт: image encoder / prompt encoder / mask decoder
- Для iOS/мобильного деплоя

---

### Open-Vocabulary Detection (боксы по тексту)

**Grounding DINO** (Apache-2.0)
- DETR + grounded pretraining; text-conditioned detection
- Разделяй классы точкой: `"a cat. a dog."`
- `post_process_grounded_object_detection` для структурированного вывода
- Первый этап в pipeline детектор → SAM

**OWLv2** (Apache-2.0)
- CLIP backbone + box heads; zero-shot text-conditioned detection
- Несколько текст-классов одновременно

**YOLO-World** (GPL-3.0 by default; upstream says commercial usage is supported)
- Real-time open-vocab OD; RepVL-PAN + region-text contrastive loss
- 35.4 AP @ 52 FPS на V100 (LVIS); экспорт TFLite/INT8

For a product, apply GPL-v3 terms or obtain separate terms only if the intended
distribution/policy needs an alternative; involve legal review for that choice.
Source: https://github.com/AILab-CVC/YOLO-World (Licence section).

---

### Florence-2 (2023, MIT, 0.23B/0.77B)
- Seq2seq, все задачи через task prompt (`<OD>`, `<CAPTION>`, и др.)
- FLD-5B: 5.4B аннотаций на 126M изображений
- Вывод: структурированный текст → пост-процессинг `post_process_generation`
- Лучше как гроундер/детектор + генератор структуры; маски выгоднее брать SAM-ом
- Требует `trust_remote_code=True`

```python
from transformers import AutoProcessor, AutoModelForCausalLM
model = AutoModelForCausalLM.from_pretrained(
    "microsoft/Florence-2-large", torch_dtype=dtype, trust_remote_code=True).to(device)
processor = AutoProcessor.from_pretrained("microsoft/Florence-2-large", trust_remote_code=True)
inputs = processor(text="<OD>", images=image, return_tensors="pt").to(device, dtype)
generated_ids = model.generate(**inputs, max_new_tokens=1024, num_beams=3)
text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
parsed = processor.post_process_generation(text, task="<OD>", image_size=(image.width, image.height))
```

---

### LLaVA (код Apache-2.0, веса — зависит от base LLM)
- CLIP ViT-L-336px + MLP projector + Vicuna/LLaMA
- **Не выдаёт маски напрямую** — роль в стеке: оркестратор
  - Переформулирует промпты для детектора
  - Выбирает классы/синонимы для open-vocab
  - Объясняет ошибки, валидирует результаты
- 4-bit режим: <8GB VRAM для LLaVA-1.5-7B

```bash
python -m llava.serve.cli \
  --model-path liuhaotian/llava-v1.5-7b \
  --image-file "https://..." --load-4bit
```

---

## Интеграционные паттерны

### Pattern 1: Concept Phrase → Instance Masks (рекомендован)
```
SAM3 PCS: text("shoe") → [mask1, mask2, ...] + boxes + scores

ИЛИ (если SAM3 недоступен):
Grounding DINO("shoe") → boxes → SAM2.1(boxes) → masks
```

### Pattern 2: Part-Level Labeling
```
1. SAM2/SAM3 + доменная адаптация → маски частей (геометрия)
2. Классификатор по ROI/маске + фиксированный словарь (лейблинг)

Почему разделять: open-vocab хорошо ищет концепты, но
для стабильного контролируемого словаря надёжнее фиксированная классификация
```

### Pattern 3: MLLM-оркестратор + детектор/сегментатор
```
LLaVA/Qwen3-VL:
  - переписывает запрос в набор детектор-классов
  - добавляет пространственные фильтры
→ Grounding DINO / OWLv2 → boxes
→ SAM2.1 → masks
→ Part classifer → labels
```

---

## Research модели (part-level / multi-granularity)

**Semantic-SAM** (MIT)
- Universal segmentation + recognition, разные гранулярности, включая parts
- Обучение на SA-1B + part segmentation данные
- Ключевая идея: decoupled classification для objects и parts → object + part labels

**SEEM** (Apache-2.0)
- Универсальный декодер; multimodal prompts (points, boxes, scribbles, language)
- Сегментация "всё/везде/все сразу"

**OpenSeeD** (Apache-2.0)
- Open-vocab segmentation + detection; decoupled decoding + conditioned mask decoding

---

## Советы по производительности и памяти

- `torch.autocast("cuda", dtype=torch.bfloat16)` — стандарт для SAM2/SAM3
- SAM2 поддерживает `torch.compile` — ускорение VOS
- `PYTORCH_ALLOC_CONF=backend:cudaMallocAsync` — снижает фрагментацию
- Для edge: EdgeTAM (CoreML), SAM2.1-tiny (39M params)
- Русские промпты: для Grounding DINO/OWLv2/YOLO-World надёжнее EN + маппинг

---

## Источники
- SAM3 paper: https://arxiv.org/abs/2511.16719
- SAM3 repo: https://github.com/facebookresearch/sam3
- SAM3 HF (gated): https://huggingface.co/facebook/sam3
- SAM2 paper: https://arxiv.org/abs/2408.00714
- SAM2 repo: https://github.com/facebookresearch/sam2
- Florence-2 paper: https://arxiv.org/abs/2311.06242
- Florence-2 HF: https://huggingface.co/microsoft/Florence-2-large
- LLaVA paper: https://arxiv.org/abs/2304.08485
- LLaVA repo: https://github.com/haotian-liu/LLaVA
- Grounding DINO: https://arxiv.org/abs/2303.05499
- OWLv2: https://arxiv.org/abs/2306.09683
- YOLO-World: https://arxiv.org/abs/2401.17270
- Semantic-SAM: https://arxiv.org/abs/2307.04767
- OpenSeeD: https://arxiv.org/abs/2303.08131
