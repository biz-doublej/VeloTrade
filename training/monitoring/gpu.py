"""GPU 상태 조회 (best-effort). NVML → nvidia-smi → torch 순서로 fallback. 실패해도 예외 없음."""

from __future__ import annotations

import subprocess
from typing import Any


def query_gpu(index: int = 0) -> dict[str, Any]:
    try:
        import pynvml  # nvidia-ml-py

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(index)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        name = pynvml.nvmlDeviceGetName(h)
        return {
            "gpu_name": name.decode() if isinstance(name, bytes) else str(name),
            "gpu_utilization": float(util.gpu),
            "gpu_memory_used_mb": int(mem.used / 2**20),
            "gpu_memory_total_mb": int(mem.total / 2**20),
        }
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits", "-i", str(index)],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            n, u, mu, mt = [x.strip() for x in out.stdout.strip().split(",")]
            return {
                "gpu_name": n, "gpu_utilization": float(u),
                "gpu_memory_used_mb": int(float(mu)), "gpu_memory_total_mb": int(float(mt)),
            }
    except Exception:
        pass
    try:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info(index)
            return {
                "gpu_name": torch.cuda.get_device_name(index),
                "gpu_utilization": None,
                "gpu_memory_used_mb": int((total - free) / 2**20),
                "gpu_memory_total_mb": int(total / 2**20),
            }
    except Exception:
        pass
    return {}
