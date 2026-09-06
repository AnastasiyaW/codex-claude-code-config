# GPU Деплой: Два Инстанса SAM3 на H100

> **Scope and evidence boundary (2026-09-06):** this is a historical
> configuration example, not a safe default or a host-change runbook. Before
> acting, inspect the actual GPU/driver/MIG layout, active owners, model revision
> and workload objective; preserve the current layout and obtain explicit
> operational authority for any MIG, MPS, Docker, service or package mutation.
> H100 profiles, throughput, VRAM and model APIs must be re-measured on the
> target stack. Synthetic benchmark inputs prove neither segmentation quality
> nor retouch workflow acceptance.

## Ключевой вывод

"Оба по 100% GPU одновременно" — физически невозможно. Ресурсы делятся.
Цель реалистичная: предсказуемая латентность + суммарная утилизация близко к 100%.

| Подход | Изоляция | Утилизация | Сложность | Рекомендуется |
|--------|----------|-----------|-----------|--------------|
| **MIG** | Аппаратная ✅ | Высокая | Средняя | **Да, если критична изоляция** |
| CUDA MPS | Кооперативная | Хорошая | Средняя | Если MIG нельзя |
| Triton batching | Логическая | Лучшая для throughput | Средняя/высокая | Если нужен throughput, не изоляция |
| Два процесса без MIG/MPS | Нет | Непредсказуемая | Низкая | Только для теста |

---

## Оценка памяти для SAM3 на H100 80GB

- SAM3: 848M параметров; BF16 ≈ **~1.7 GB только веса**
- Реальная VRAM: зависит от разрешения, числа объектов, видео-буферов
- Два инстанса в BF16 **влезают в 80GB** с запасом для активаций

---

## Схема 1 (Рекомендована): MIG → два аппаратно-изолированных инстанса

### Почему MIG

MIG даёт **гарантированную QoS**: аппаратно изолированные SM, HBM, кэши.
Один клиент не может "выдавить" другого по расписанию/памяти.

H100 80GB поддерживает до 7 MIG-инстансов. Профиль `4g.40gb + 3g.40gb` = 7/7 SM + 80GB.

### Настройка MIG

```bash
# 1. Проверить GPU
nvidia-smi -L

# 2. Остановить мониторинг (если нужно)
sudo systemctl stop dcgm || true
sudo systemctl stop nvsm || true

# 3. Включить MIG mode
sudo nvidia-smi -i 0 -mig 1

# 4. Очистить старую геометрию
sudo nvidia-smi mig -dci || true
sudo nvidia-smi mig -dgi || true

# 5. Создать два инстанса (суммарно = 100% H100 80GB)
sudo nvidia-smi mig -cgi 4g.40gb,3g.40gb -C

# 6. Получить MIG UUID
nvidia-smi -L | sed -n 's/.*(UUID: \(MIG-[^) ]*\)).*/\1/p'
```

### Запуск двух воркеров

```bash
#!/usr/bin/env bash
set -euo pipefail

MIG_UUIDS=($(nvidia-smi -L | sed -n 's/.*(UUID: \(MIG-[^) ]*\)).*/\1/p'))
if [ "${#MIG_UUIDS[@]}" -lt 2 ]; then
  echo "Нужно 2 MIG-устройства. Выполни: sudo nvidia-smi mig -cgi 4g.40gb,3g.40gb -C"
  exit 1
fi

export PYTORCH_ALLOC_CONF="backend:cudaMallocAsync"
export TOKENIZERS_PARALLELISM="false"

taskset -c 0-15 env CUDA_VISIBLE_DEVICES="${MIG_UUIDS[0]}" \
  python -u sam3_worker.py --worker_id 0 --img_size 1024 --batch 4 &

taskset -c 16-31 env CUDA_VISIBLE_DEVICES="${MIG_UUIDS[1]}" \
  python -u sam3_worker.py --worker_id 1 --img_size 1024 --batch 4 &

wait
```

### Docker с MIG

```bash
sudo docker run --rm \
  --gpus '"device=MIG-<ВАШ-UUID>"' \
  -e NVIDIA_VISIBLE_DEVICES="MIG-<ВАШ-UUID>" \
  -e PYTORCH_ALLOC_CONF="backend:cudaMallocAsync" \
  pytorch/pytorch:latest \
  python sam3_worker.py --worker_id 0
```

---

## Схема 2 (Fallback): CUDA MPS

**Ограничение:** MPS — кооперативный шеринг, не аппаратная изоляция.
При тяжёлых kernels будет contention по памяти/кэшу/SM.

```bash
#!/usr/bin/env bash
# Запуск MPS демона
export CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps
export CUDA_MPS_LOG_DIRECTORY=/tmp/nvidia-mps-log
mkdir -p "${CUDA_MPS_PIPE_DIRECTORY}" "${CUDA_MPS_LOG_DIRECTORY}"
sudo -E nvidia-cuda-mps-control -d

export CUDA_MPS_ENABLE_PER_CTX_DEVICE_MULTIPROCESSOR_PARTITIONING=1
export PYTORCH_ALLOC_CONF="backend:cudaMallocAsync"

# Два клиента по 50% SM каждый
taskset -c 0-15  env CUDA_VISIBLE_DEVICES=0 CUDA_MPS_ACTIVE_THREAD_PERCENTAGE=50 \
  python sam3_worker.py --worker_id 0 &

taskset -c 16-31 env CUDA_VISIBLE_DEVICES=0 CUDA_MPS_ACTIVE_THREAD_PERCENTAGE=50 \
  python sam3_worker.py --worker_id 1 &

wait
echo quit | sudo -E nvidia-cuda-mps-control
```

---

## Python Worker: SAM3 бенчмарк

```python
# sam3_worker.py
import argparse, time
import torch
import numpy as np
from PIL import Image
from sam3.model_builder import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor

def make_random_batch(batch, img_size):
    return [Image.fromarray(np.random.randint(0, 256, (img_size, img_size, 3), np.uint8))
            for _ in range(batch)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker_id", type=int, required=True)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--img_size", type=int, default=1024)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--prompt", type=str, default="shoe")
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_grad_enabled(False)

    if device == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = True
        # FlashAttention если доступен
        torch.backends.cuda.enable_flash_sdp(True)
        torch.backends.cuda.enable_mem_efficient_sdp(True)
        torch.backends.cuda.enable_math_sdp(False)

    model = build_sam3_image_model().to(device).eval()
    processor = Sam3Processor(model)

    # torch.compile (опционально: даёт throughput, но поднимает time-to-first и peak memory)
    # model = torch.compile(model, mode="max-autotune")

    # Прогрев
    for img in make_random_batch(2, min(args.img_size, 512)):
        st = processor.set_image(img)
        processor.set_text_prompt(state=st, prompt=args.prompt)
    if device == "cuda":
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()

    # Основной цикл
    images_done, t_total = 0, 0.0
    deadline = time.time() + args.seconds

    while time.time() < deadline:
        t0 = time.time()
        for img in make_random_batch(args.batch, args.img_size):
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=(device == "cuda")):
                state = processor.set_image(img)
                out = processor.set_text_prompt(state=state, prompt=args.prompt)
                _ = out["masks"].shape  # ensure forward completed
        if device == "cuda":
            torch.cuda.synchronize()
        dt = time.time() - t0
        images_done += args.batch
        t_total += dt

    ips = images_done / max(t_total, 1e-9)
    peak_gb = torch.cuda.max_memory_allocated() / 1024**3 if device == "cuda" else 0

    print(f"[worker {args.worker_id}] "
          f"throughput={ips:.2f} img/s  "
          f"latency={1000*t_total/max(images_done,1):.1f} ms/img  "
          f"peak_mem={peak_gb:.2f} GB")

if __name__ == "__main__":
    main()
```

---

## Управление памятью PyTorch

```python
import torch

# Лимит для caching allocator (мягкий, не аппаратный)
torch.cuda.memory.set_per_process_memory_fraction(0.45, device=0)

# Рекомендованные env vars
# PYTORCH_ALLOC_CONF=backend:cudaMallocAsync   ← снижает фрагментацию
# PYTORCH_ALLOC_CONF=max_split_size_mb:128     ← только для native backend
```

**Важно:** `set_per_process_memory_fraction` — ограничение PyTorch-аллокатора, не аппаратная изоляция VRAM. Не заменяет MIG.

---

## Оптимизации для H100

**BF16** — стандарт на Hopper; H100 имеет нативные BF16 Tensor Cores.

**FlashAttention-2**: поддерживает H100/Hopper + fp16/bf16. Включить:
```python
torch.backends.cuda.enable_flash_sdp(True)
```

**torch.compile**: может дать 10-30% throughput. Риски: медленный старт, может поднять peak memory. Тестировать на реальном графе SAM3.

**TorchAO квантование** (если нужно влезть в память):
- Float8 требует compute capability ≥ 8.9 (H100 ✅)
- Int4 может ухудшать качество масок — тестировать!
- Есть tutorial TorchAO для SAM-семейства

---

## Протокол валидации "не мешают"

```
1. Baseline: один воркер, full GPU → max throughput (img/s), p95 latency

2. Два воркера (MIG):
   - CUDA_VISIBLE_DEVICES=MIG-UUID-0 + CUDA_VISIBLE_DEVICES=MIG-UUID-1
   - Наблюдать: стабильный throughput, нет "пилы", нет внезапных остановок

3. Метрики:
   - nvidia-smi: utilization.gpu, utilization.memory, memory.used
   - PyTorch: memory_allocated, memory_reserved, max_memory_allocated
   - P95 latency на каждый воркер

4. Успех MIG = каждый воркер стабилен и не зависит от нагрузки другого
```

```bash
# Live мониторинг
nvidia-smi --query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used \
  --format=csv -l 1

# Per-process stats
nvidia-smi pmon -s um -d 1

# Полный timeline (Nsight Systems)
nsys profile -o two_workers --trace=cuda,nvtx ./run_two_workers.sh
```

---

## Лицензия SAM3 — важно для продакшна

- SAM License (кастомная, не Apache/MIT/GPL)
- Gated access на HF: нужно принять условия + токен
- "limited license" на использование/модификацию/распространение
- Проверить: ограничения end-use, запрет/разрешение на производные сервисы
- Зафиксировать версию чекпойнта и текст лицензии в репозитории

---

## Источники

- SAM3 repo: https://github.com/facebookresearch/sam3
- SAM3 license: https://huggingface.co/facebook/sam3/blob/main/LICENSE
- NVIDIA MIG User Guide: https://docs.nvidia.com/datacenter/tesla/mig-user-guide/
- MIG Supported GPUs (H100): https://docs.nvidia.com/datacenter/tesla/mig-user-guide/supported-gpus.html
- MIG Getting Started: https://docs.nvidia.com/datacenter/tesla/mig-user-guide/getting-started-with-mig.html
- CUDA MPS docs: https://docs.nvidia.com/deploy/mps/
- MPS tools & env vars: https://docs.nvidia.com/deploy/mps/appendix-tools-and-interface-reference.html
- PyTorch set_per_process_memory_fraction: https://docs.pytorch.org/docs/stable/generated/torch.cuda.memory.set_per_process_memory_fraction.html
- PyTorch CUDA semantics + PYTORCH_ALLOC_CONF: https://docs.pytorch.org/docs/stable/notes/cuda.html
- TorchAO quantization: https://docs.pytorch.org/ao/stable/workflows/inference.html
- TorchAO SAM tutorial: https://docs.pytorch.org/tutorials/unstable/gpu_quantization_torchao_tutorial.html
- FlashAttention repo: https://github.com/Dao-AILab/flash-attention
- Nsight Systems: https://docs.nvidia.com/nsight-systems/UserGuide/
- Triton dynamic batching: https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/tutorials/Conceptual_Guide/Part_2-improving_resource_utilization/README.html
