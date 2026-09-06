# Память, оптимизация и распределённое обучение

## Table of contents
1. Из чего состоит VRAM при обучении
2. AMP (FP16/BF16)
3. Activation checkpointing
4. Gradient accumulation
5. ZeRO / DeepSpeed
6. FSDP (PyTorch)
7. Quantization: 8-bit, 4-bit, FP8
8. Attention: xFormers / SDPA
9. DeepSpeed конфиг (JSON)
10. Мини-рецепты по бюджету

---

## 1. Из чего состоит VRAM при обучении

```
VRAM ≈ Веса + Градиенты + Состояния оптимизатора + Активации
```

| Компонент | Размер | Рычаг |
|---|---|---|
| Веса модели | 1× | LoRA, quantization |
| Градиенты | 1× (fp16) или 2× (fp32 master) | AMP |
| AdamW states (m, v) | 2× | 8-bit optimizer, offload |
| Активации | Зависит от batch | Checkpointing |

**Практическое правило:** AdamW хранит 2 копии состояний → при fp32 параметрах = ~4× размер весов только на оптимизатор. С 8-bit оптимизатором можно срезать это вдвое.

---

## 2. AMP (FP16 / BF16)

```python
import torch

# Choose the dtype only after checking the target accelerator.  GradScaler is
# active for fp16 and deliberately disabled for bf16.
amp_dtype = torch.bfloat16
scaler = torch.amp.GradScaler("cuda", enabled=amp_dtype == torch.float16)

for batch in dataloader:
    optimizer.zero_grad(set_to_none=True)
    
    with torch.autocast(device_type="cuda", dtype=amp_dtype):
        output = model(batch)
        loss = criterion(output, target)
    
    # For fp16 this scales; for bf16 the disabled scaler is a no-op.
    scaler.scale(loss).backward()
    scaler.unscale_(optimizer)
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    scaler.step(optimizer)
    scaler.update()
    
```

**BF16 vs FP16:**
- BF16: больший range (как fp32), не нужен GradScaler → проще и стабильнее
- FP16: точнее, но риск underflow → нужен GradScaler
- На H100/A100 → BF16; на старых GPU (V100) → FP16

---

## 3. Activation Checkpointing

Пересчитывает часть forward на backward вместо хранения активаций.

```python
from torch.utils.checkpoint import checkpoint, checkpoint_sequential

# Один блок
def forward(self, x):
    return checkpoint(self.heavy_block, x, use_reentrant=False)

# Несколько блоков последовательно
output = checkpoint_sequential(self.layers, segments=4, input=x)

# Для Diffusers UNet — включить встроенный checkpointing
pipe.unet.enable_gradient_checkpointing()
pipe.text_encoder.gradient_checkpointing_enable()
```

**Трейдофф:** −30–50% VRAM ↔ +20–40% compute time.

---

## 4. Gradient Accumulation

Эмулирует большой batch при малой памяти:

```python
accumulation_steps = 4
effective_batch = per_gpu_batch × accumulation_steps

optimizer.zero_grad(set_to_none=True)
for step, batch in enumerate(dataloader):
    with torch.autocast("cuda", torch.bfloat16):
        loss = model(batch) / accumulation_steps  # нормализовать!
    loss.backward()
    
    if (step + 1) % accumulation_steps == 0:
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
```

---

## 5. ZeRO / DeepSpeed

Шардирует оптимизатор / параметры / градиенты между воркерами.

| Stage | Что шардируется | Экономия |
|---|---|---|
| ZeRO-1 | Состояния оптимизатора | 4× |
| ZeRO-2 | + Градиенты | 8× |
| ZeRO-3 | + Параметры | N× (где N = число GPU) |
| ZeRO-3 + Offload | + CPU/NVMe offload | Огромная, но медленнее |

```python
# Инициализация через DeepSpeed
import deepspeed

model_engine, optimizer, _, _ = deepspeed.initialize(
    model=model,
    config="ds_config.json",
)

# Training step
for batch in dataloader:
    loss = model_engine(batch)
    model_engine.backward(loss)
    model_engine.step()
```

---

## 6. FSDP (PyTorch Fully Sharded Data Parallel)

Нативный PyTorch аналог ZeRO-3.

```python
from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
from torch.distributed.fsdp import MixedPrecision, BackwardPrefetch
from torch.distributed.fsdp.wrap import transformer_auto_wrap_policy
import functools

# Политика оборачивания трансформер-блоков
auto_wrap = functools.partial(
    transformer_auto_wrap_policy,
    transformer_layer_cls={TransformerBlock},  # укажите ваш класс блока
)

bf16_policy = MixedPrecision(
    param_dtype=torch.bfloat16,
    reduce_dtype=torch.bfloat16,
    buffer_dtype=torch.bfloat16,
)

model = FSDP(
    model,
    auto_wrap_policy=auto_wrap,
    mixed_precision=bf16_policy,
    backward_prefetch=BackwardPrefetch.BACKWARD_PRE,
    device_id=torch.cuda.current_device(),
)
```

---

## 7. Quantization

### 8-bit / 4-bit через bitsandbytes

```python
from diffusers import StableDiffusionPipeline, BitsAndBytesConfig
import torch

# 4-bit quantization
quantization_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
)

pipe = StableDiffusionPipeline.from_pretrained(
    "stable-diffusion-v1-5/stable-diffusion-v1-5",
    quantization_config=quantization_config,
)
```

### 8-bit optimizer (экономия на состояниях)

```python
import bitsandbytes as bnb

optimizer = bnb.optim.AdamW8bit(
    model.parameters(),
    lr=1e-4,
    weight_decay=0.01,
)
```

### FP8 (H100, экспериментально)

```python
# torchao float8 linear
from torchao.float8 import convert_to_float8_training

model = convert_to_float8_training(model)
```

---

## 8. Attention: xFormers / SDPA

```python
# xFormers (установить: pip install xformers)
pipe.unet.enable_xformers_memory_efficient_attention()

# PyTorch SDPA (встроено в PyTorch 2.0+)
# Автоматически выбирает Flash Attention / Memory-efficient / Math

# Для Flux/DiT-моделей — SDPA или xFormers могут давать разный профит
# чем для UNet-моделей; проверять отдельно

# Отключить xFormers если нужен детерминизм
pipe.unet.disable_xformers_memory_efficient_attention()
```

---

## 9. DeepSpeed конфиг (ключевой JSON)

```json
{
  "train_batch_size": 64,
  "gradient_accumulation_steps": 4,
  "bf16": { "enabled": true },
  "zero_optimization": {
    "stage": 2,
    "offload_optimizer": { "device": "cpu", "pin_memory": true },
    "allgather_partitions": true,
    "reduce_scatter": true,
    "overlap_comm": true,
    "contiguous_gradients": true
  },
  "optimizer": {
    "type": "AdamW",
    "params": {
      "lr": 1e-4,
      "betas": [0.9, 0.999],
      "eps": 1e-8,
      "weight_decay": 0.01
    }
  },
  "gradient_clipping": 1.0
}
```

**Stage 2 + CPU offload оптимизатора** — хороший первый шаг на 1–4 GPU: экономит VRAM без сильного удара по скорости.

---

## 10. Мини-рецепты по бюджету

| Бюджет | Рецепт | Компромисс |
|---|---|---|
| **8–16 GB (1 GPU)** | LoRA + grad_accum 4–8 + BF16 + checkpointing + 8-bit optim + xFormers | Маленький batch, медленнее сходимость |
| **24–48 GB (1–4 GPU)** | LoRA или partial FT + FSDP или ZeRO-2 + BF16 | Следить за коммуникационным overhead |
| **8+ GPU, H100** | Full FT + ZeRO-3 + BF16/FP8 + WebDataset + Flash Attention | Стоимость данных и лицензий |

**Ссылки:**
- PyTorch AMP: https://docs.pytorch.org/docs/stable/amp.html
- PyTorch checkpointing: https://docs.pytorch.org/docs/stable/checkpoint.html
- PyTorch FSDP: https://docs.pytorch.org/docs/stable/fsdp.html
- DeepSpeed ZeRO: https://deepspeed.readthedocs.io/en/latest/zero3.html
- DeepSpeed config JSON: https://www.deepspeed.ai/docs/config-json/
- Diffusers memory optimization: https://huggingface.co/docs/diffusers/en/optimization/memory
- Diffusers quantization: https://huggingface.co/docs/diffusers/en/api/quantization
