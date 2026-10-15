"""공용 유틸: seed, atomic write, logging, git/환경 정보, secret/path 마스킹."""

from __future__ import annotations

import json
import logging
import os
import platform
import random
import re
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET_PAT = re.compile(
    r"(eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}|sk-[A-Za-z0-9]{20,}|"
    r"(?i:\b\w*(?:key|secret|token|password)\w*\s*[=:]\s*\S+))"
)


def mask_secrets(text: str) -> str:
    return _SECRET_PAT.sub("***", text)


def sanitize_text(text: str) -> str:
    """외부(dashboard) 로 나가는 문자열에서 secret 과 사용자 절대경로를 제거."""
    text = mask_secrets(text)
    text = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", "~", text)
    text = re.sub(r"/(?:home|Users)/[^/\s]+", "~", text)
    return text


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def set_seed(seed: int) -> None:
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch

        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def setup_logging(log_file: Path | None = None, name: str = "event_alpha") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    logger.propagate = False
    return logger


def git_commit(repo_root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, timeout=5
        )
        return (out.stdout.strip() or None) if out.returncode == 0 else None
    except Exception:
        return None


def env_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
    try:
        import torch

        info["torch_version"] = torch.__version__
        info["cuda_version"] = torch.version.cuda
        info["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            info["gpu_name"] = p.name
            info["gpu_vram_mb"] = int(p.total_memory / 2**20)
    except ImportError:
        info["torch_version"] = None
    return info


def make_run_id(prefix: str = "") -> str:
    return (prefix + "_" if prefix else "") + datetime.now().strftime("%Y%m%d_%H%M%S")
