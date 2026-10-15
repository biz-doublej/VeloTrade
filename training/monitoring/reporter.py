"""Training Reporter — best-effort telemetry. 모니터링 실패는 학습을 절대 죽이지 않는다.

TrainingReporter (abstract)
 ├─ LocalReporter     : artifacts/<run>/training_status.json, training_metrics.jsonl (atomic write)
 ├─ SupabaseReporter  : vt.training_runs / vt.training_metrics (REST, outbound HTTPS only)
 └─ CompositeReporter : 여러 reporter 를 묶고 각 호출을 try/except 로 격리

전송하는 것: 상태/heartbeat/metric/체크포인트 "이름"/sanitize 된 짧은 메시지만.
전송하지 않는 것: dataset, checkpoint 파일, traceback 전문, 절대경로, secret.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from event_alpha.utils import atomic_write_json, sanitize_text  # noqa: E402

from .gpu import query_gpu  # noqa: E402

log = logging.getLogger("event_alpha")

STATUSES = {"PENDING", "RUNNING", "COMPLETED", "FAILED", "INTERRUPTED", "CANCELLED"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrainingReporter(ABC):
    """공통 인터페이스. 구현체는 예외를 밖으로 던지지 않는 것이 원칙(Composite 가 한 번 더 격리)."""

    @abstractmethod
    def start_run(self, info: dict[str, Any]) -> None: ...

    @abstractmethod
    def heartbeat(self, state: dict[str, Any]) -> None: ...

    @abstractmethod
    def log_metrics(self, split: str, epoch: int, step: int, metrics: dict[str, float]) -> None: ...

    @abstractmethod
    def log_checkpoint(self, name: str) -> None: ...

    @abstractmethod
    def complete(self, summary: dict[str, Any] | None = None) -> None: ...

    @abstractmethod
    def fail(self, error: str, interrupted: bool = False) -> None: ...


class LocalReporter(TrainingReporter):
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.status_path = run_dir / "training_status.json"
        self.metrics_path = run_dir / "training_metrics.jsonl"
        self._state: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _flush(self) -> None:
        with self._lock:
            atomic_write_json(self.status_path, self._state)

    def start_run(self, info: dict[str, Any]) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._state = {**info, "status": "RUNNING", "updated_at": _now_iso()}
        self._flush()

    def heartbeat(self, state: dict[str, Any]) -> None:
        self._state.update(state)
        self._state["updated_at"] = _now_iso()
        self._flush()

    def log_metrics(self, split: str, epoch: int, step: int, metrics: dict[str, float]) -> None:
        rec = {"ts": _now_iso(), "split": split, "epoch": epoch, "step": step, **metrics}
        with self._lock, open(self.metrics_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    def log_checkpoint(self, name: str) -> None:
        self.heartbeat({"checkpoint_path": name})

    def complete(self, summary: dict[str, Any] | None = None) -> None:
        self.heartbeat({"status": "COMPLETED", "finished_at": _now_iso(), "progress": 1.0,
                        **(summary or {})})

    def fail(self, error: str, interrupted: bool = False) -> None:
        self.heartbeat({"status": "INTERRUPTED" if interrupted else "FAILED",
                        "finished_at": _now_iso(), "error_message": sanitize_text(error)[:500]})


class SupabaseReporter(TrainingReporter):
    """PostgREST 로 vt 스키마에 upsert. 연속 실패 시 지수 backoff — 학습에는 영향 없음."""

    def __init__(self, url: str, service_key: str, run_id: str, timeout: float = 8.0) -> None:
        import httpx  # 지연 import: 설치/네트워크 문제가 학습 import 를 막지 않게

        self._httpx = httpx
        self.base = url.rstrip("/") + "/rest/v1"
        self.run_id = run_id
        self.timeout = timeout
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Content-Profile": "vt",
            "Accept-Profile": "vt",
        }
        self._fail_count = 0
        self._next_try = 0.0
        self._warned = False
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, run_id: str) -> SupabaseReporter | None:
        url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            return None
        return cls(url, key, run_id)

    def _post(self, table: str, row: dict[str, Any], upsert_on: str | None = None) -> None:
        now = time.monotonic()
        if now < self._next_try:
            return
        headers = dict(self._headers)
        params = {}
        if upsert_on:
            headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
            params["on_conflict"] = upsert_on
        else:
            headers["Prefer"] = "return=minimal"
        try:
            r = self._httpx.post(f"{self.base}/{table}", headers=headers, params=params,
                                 content=json.dumps(row, default=str), timeout=self.timeout)
            r.raise_for_status()
            self._fail_count = 0
        except Exception as e:  # noqa: BLE001 — telemetry 는 best-effort
            self._fail_count += 1
            self._next_try = now + min(600.0, 15.0 * 2 ** min(self._fail_count, 6))
            if not self._warned or self._fail_count % 10 == 0:
                self._warned = True
                # 예외 메시지에 URL/키가 섞일 수 있어 type 만 기록
                log.warning("supabase telemetry failed (%s); training continues", type(e).__name__)

    _RUN_COLS = {
        "run_id", "experiment_name", "model_name", "status", "hostname", "gpu_name", "started_at",
        "updated_at", "finished_at", "current_epoch", "total_epochs", "current_step", "total_steps",
        "progress", "train_loss", "val_loss", "accuracy", "macro_f1", "mae", "rmse", "spearman_ic",
        "learning_rate", "gpu_utilization", "gpu_memory_used_mb", "gpu_memory_total_mb",
        "elapsed_seconds", "checkpoint_path", "log_tail", "error_message", "git_commit",
    }

    def _upsert_run(self, state: dict[str, Any]) -> None:
        row = {k: v for k, v in state.items() if k in self._RUN_COLS}
        row["run_id"] = self.run_id
        row["updated_at"] = _now_iso()
        for k in ("checkpoint_path",):
            if row.get(k):
                row[k] = os.path.basename(str(row[k]))  # 절대경로 노출 방지
        for k in ("log_tail", "error_message"):
            if row.get(k):
                row[k] = sanitize_text(str(row[k]))[:2000]
        self._post("training_runs", row, upsert_on="run_id")

    def start_run(self, info: dict[str, Any]) -> None:
        self._upsert_run({**info, "status": "RUNNING"})

    def heartbeat(self, state: dict[str, Any]) -> None:
        self._upsert_run(state)

    def log_metrics(self, split: str, epoch: int, step: int, metrics: dict[str, float]) -> None:
        for name, v in metrics.items():
            if v is None:
                continue
            self._post("training_metrics", {
                "run_id": self.run_id, "timestamp": _now_iso(), "epoch": epoch, "step": step,
                "split": split, "metric_name": name, "metric_value": float(v),
            })

    def log_checkpoint(self, name: str) -> None:
        self._upsert_run({"checkpoint_path": name})

    def complete(self, summary: dict[str, Any] | None = None) -> None:
        self._upsert_run({"status": "COMPLETED", "finished_at": _now_iso(), "progress": 1.0,
                          **(summary or {})})

    def fail(self, error: str, interrupted: bool = False) -> None:
        self._upsert_run({"status": "INTERRUPTED" if interrupted else "FAILED",
                          "finished_at": _now_iso(), "error_message": error})


class CompositeReporter(TrainingReporter):
    """상태를 공유하고 주기적으로 heartbeat 를 flush 하는 Facade (백그라운드 스레드)."""

    def __init__(self, reporters: list[TrainingReporter], *, local_every: float = 30.0,
                 remote_every: float = 60.0) -> None:
        self.reporters = reporters
        self.local_every = local_every
        self.remote_every = remote_every
        self.state: dict[str, Any] = {}
        self._t0 = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- 안전 호출 ---------------------------------------------------------------------
    def _each(self, fn: str, *a: Any, **kw: Any) -> None:
        for r in self.reporters:
            try:
                getattr(r, fn)(*a, **kw)
            except Exception as e:  # noqa: BLE001
                log.warning("reporter %s.%s failed: %s", type(r).__name__, fn, type(e).__name__)

    # -- API ---------------------------------------------------------------------------
    def update(self, **fields: Any) -> None:
        with self._lock:
            self.state.update({k: v for k, v in fields.items()})
            self.state["elapsed_seconds"] = int(time.monotonic() - self._t0)

    def start_run(self, info: dict[str, Any]) -> None:
        self.update(**info, status="RUNNING")
        self._each("start_run", dict(self.state))
        self._thread = threading.Thread(target=self._loop, name="reporter-heartbeat", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        last_remote = 0.0
        while not self._stop.wait(self.local_every):
            with self._lock:
                snap = dict(self.state)
                snap["elapsed_seconds"] = int(time.monotonic() - self._t0)
            snap.update(query_gpu())
            now = time.monotonic()
            for r in self.reporters:
                is_remote = isinstance(r, SupabaseReporter)
                if is_remote and now - last_remote < self.remote_every:
                    continue
                try:
                    r.heartbeat(snap)
                except Exception as e:  # noqa: BLE001
                    log.warning("heartbeat %s failed: %s", type(r).__name__, type(e).__name__)
            if now - last_remote >= self.remote_every:
                last_remote = now

    def heartbeat(self, state: dict[str, Any]) -> None:
        self.update(**state)

    def log_metrics(self, split: str, epoch: int, step: int, metrics: dict[str, float]) -> None:
        self._each("log_metrics", split, epoch, step, metrics)

    def log_checkpoint(self, name: str) -> None:
        self.update(checkpoint_path=name)
        self._each("log_checkpoint", name)

    def _finish(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def complete(self, summary: dict[str, Any] | None = None) -> None:
        self._finish()
        self._each("complete", {**self.state, **(summary or {})})

    def fail(self, error: str, interrupted: bool = False) -> None:
        self._finish()
        self._each("fail", error, interrupted)


def build_reporter(run_dir: Path, run_id: str, mode: str, heartbeat_s: int, remote_s: int) -> tuple[
    CompositeReporter, str
]:
    """mode: auto/true/false. 반환: (reporter, supabase 상태 메시지)."""
    reps: list[TrainingReporter] = [LocalReporter(run_dir)]
    msg = "supabase: disabled"
    if mode != "false":
        sb = SupabaseReporter.from_env(run_id)
        if sb is not None:
            reps.append(sb)
            msg = "supabase: enabled (connectivity NOT verified at startup)"
        elif mode == "true":
            msg = "supabase: requested but SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY missing"
        else:
            msg = "supabase: skipped (env not set)"
    return CompositeReporter(reps, local_every=heartbeat_s, remote_every=remote_s), msg
