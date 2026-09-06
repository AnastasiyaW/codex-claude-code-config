---
name: vlm-segmentation
description: Choose and evaluate VLM or segmentation pipelines, including text-conditioned detection, masks, part labels, model-license constraints, and measured GPU deployment choices. Use when a task has a VLM or segmentation component; route pure diffusion prompting, training, or serving to its specialized skill.
---

# VLM + Segmentation + Diffusion Engineering

Скилл охватывает три тесно связанных домена. Выбери нужный раздел и загрузи соответствующий reference-файл.

## Навигация по доменам

| Задача | Reference файл |
|--------|---------------|
| Выбор модели сегментации, pipeline "текст → маски", VLM-стек, part-labeling | `references/vlm-segmentation.md` |
| Диффузионные архитектуры, schedulers, обучение, LoRA, text encoder fusion | `references/diffusion-engineering.md` |
| Два инстанса SAM3 на H100, MIG/MPS, memory, профилирование | `references/gpu-deployment.md` |

**Правило выбора:** если вопрос смешивает темы (например, "как деплоить диффузионную модель на H100") — прочитай оба релевантных файла.

---

## Быстрые ответы без чтения reference-файлов

### Candidate pipeline "фраза → маски"
```
1. SAM3 PCS (текстовый концепт) → instance masks + boxes + scores
   ИЛИ
   Grounding DINO / OWLv2 / YOLO-World → boxes → SAM2.1 → masks

2. Part-labeling: отдельный классификатор по ROI + фиксированный словарь
```

### Candidate diffusion pipeline
```
1. Backbone: UNet (просто) или DiT/Flow (масштабирование)
2. Latent diffusion (VAE → латенты → денойзер → VAE decode)
3. Text encoder: CLIP (SD), два CLIP (SDXL), Qwen3 (Flux.2 klein 9B)
4. Fine-tune: начинать с LoRA, full fine-tune только если нужно
5. Memory: AMP (BF16) → checkpointing → ZeRO/FSDP при масштабе
```

### Two SAM3 instances on H100 (only after host inspection)
```
MIG can provide hardware partitioning where the inspected GPU, driver, current
MIG layout and workload support it. It changes host GPU configuration: preserve
the current layout and obtain explicit operational approval before any change.

MPS (fallback) → кооперативный шеринг, без строгой изоляции
```

---

## Ключевые характеристики моделей (быстрая справка)

| Модель | Параметры | Лицензия | Главная сильная сторона |
|--------|-----------|----------|------------------------|
| SAM3 | 848M | SAM License (gated) | Open-vocab сегментация по тексту, все инстансы |
| SAM2.1-large | model-card specific | Apache-2.0 | Видео-трекинг, интерактивная сегментация; reproduce any FPS on the target stack |
| SAM2.1-tiny | model-card specific | Apache-2.0 | Lightweight variant; reproduce any FPS on the target stack |
| Florence-2-large | 770M | MIT | Унифицированные задачи через task prompt |
| EdgeTAM | ~SAM2-tiny | Apache-2.0 | 16 FPS на iPhone 15 Pro Max, CoreML |
| Grounding DINO | — | Apache-2.0 | Text-conditioned detection, boxes |
| YOLO-World | — | GPL-3.0 | Real-time open-vocab OD, 52 FPS V100 |

---

## Критические предупреждения

- **SAM3**: gated access на HF, кастомная SAM License — проверь перед продакшном
- **YOLO-World**: upstream states GPL-3.0 and supports commercial usage. GPL
  obligations apply by default; obtain a separate commercial licence only when
  the intended distribution or policy requires terms outside GPL, with legal
  review for the specific product.
- **Замена text encoder**: не plug-and-play, нужен projection + переобучение cross-attention
- **MIG vs MPS**: только MIG даёт аппаратную изоляцию VRAM/SM; MPS — кооперативный шеринг
- For non-English prompts, compare the target model’s supported languages on a
  representative evaluation set; do not silently translate or claim a universal
  English advantage.
