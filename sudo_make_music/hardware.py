"""GPU / RAM detection. Never imports torch unless it is already needed."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, asdict


@dataclass
class HardwareInfo:
    gpu_name: str | None
    vram_mb: int | None  # total VRAM of GPU 0
    ram_mb: int | None

    def to_dict(self) -> dict:
        return asdict(self)


def _ram_mb() -> int | None:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def _nvidia_smi() -> tuple[str, int] | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip().splitlines()
        name, mem = [x.strip() for x in out[0].split(",")]
        return name, int(float(mem))
    except Exception:
        return None


def detect() -> HardwareInfo:
    gpu = _nvidia_smi()
    if gpu is None:
        try:  # fall back to torch if present (also covers ROCm builds)
            import torch

            if torch.cuda.is_available():
                p = torch.cuda.get_device_properties(0)
                gpu = (p.name, p.total_memory // (1024 * 1024))
        except Exception:
            pass
    return HardwareInfo(gpu[0] if gpu else None, gpu[1] if gpu else None, _ram_mb())


def free_vram_mb() -> int | None:
    try:
        import torch

        if torch.cuda.is_available():
            free, _ = torch.cuda.mem_get_info()
            return free // (1024 * 1024)
    except Exception:
        pass
    return None
