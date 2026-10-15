"""Pydantic 설정 스키마 + YAML 로더. 모든 경로는 repo root 기준 상대경로."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]


class PathsConfig(BaseModel):
    news_parquet: str = "data/event_alpha/raw/financial_news.parquet"
    prices_dir: str = "data/event_alpha/raw/prices"
    processed_dir: str = "data/event_alpha/processed"
    # HF model id 를 코드에 하드코딩하지 않는다 — 로컬 경로만 받는다 (offline-first).
    pretrained_dir: str = "artifacts/pretrained/event_alpha_encoder"
    artifacts_dir: str = "artifacts/event_alpha"
    log_dir: str = "logs/training"


class DataConfig(BaseModel):
    max_tickers: int = 250
    benchmark: str = "SPY"
    market_symbols: list[str] = ["SPY", "QQQ", "_VIX"]
    min_headline_chars: int = 15
    max_events: int | None = None          # smoke test 용 상한
    include_ticker_in_text: bool = False   # ticker shortcut 방지: 기본 OFF
    include_publisher_in_text: bool = True
    min_price_history_days: int = 25       # feature 계산용 최소 과거


class SplitConfig(BaseModel):
    """chronological split. 날짜는 event date 기준 (포함)."""

    train_end: str = "2017-12-31"
    val_end: str = "2018-12-31"            # test = val_end 이후 전부
    embargo_days: int = 7                  # 5d label 이 split 경계를 넘지 않도록 버리는 달력일


class LabelConfig(BaseModel):
    horizons: list[int] = [1, 3, 5]
    cls_horizon: int = 3
    lower_quantile: float = 0.30           # train 분포 기준 (test 를 보지 않음)
    upper_quantile: float = 0.70
    winsor_pct: float = 0.005              # regression target 양끝 winsorize (train 기준)


class ModelConfig(BaseModel):
    max_length: int = 64
    market_hidden: int = 64
    dropout: float = 0.1
    reg_loss_weight: float = 1.0


class TrainConfig(BaseModel):
    seed: int = 42
    epochs: int = 3
    batch_size: int = 128
    eval_batch_size: int = 512
    lr: float = 2e-5
    head_lr: float = 1e-3
    weight_decay: float = 0.01
    warmup_ratio: float = 0.06
    grad_clip: float = 1.0
    precision: Literal["auto", "bf16", "fp16", "fp32"] = "auto"
    early_stopping_patience: int = 1       # val macro-F1 기준
    checkpoint_every_steps: int = 2000
    log_every_steps: int = 100
    max_oom_retries: int = 2
    max_train_samples: int | None = None   # smoke test
    max_eval_samples: int | None = None


class EvalConfig(BaseModel):
    top_fracs: list[float] = [0.01, 0.05, 0.10, 0.20]
    cost_bps_scenarios: list[float] = [0.0, 5.0, 10.0, 20.0]
    signal_horizon: int = 3


class MonitorConfig(BaseModel):
    heartbeat_seconds: int = 30
    supabase_every_seconds: int = 60
    supabase_enabled: Literal["auto", "true", "false"] = "auto"  # auto: env 있을 때만
    log_tail_lines: int = 15


class Config(BaseModel):
    experiment_name: str = "Event Alpha Model v0"
    paths: PathsConfig = Field(default_factory=PathsConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    split: SplitConfig = Field(default_factory=SplitConfig)
    label: LabelConfig = Field(default_factory=LabelConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    train: TrainConfig = Field(default_factory=TrainConfig)
    eval: EvalConfig = Field(default_factory=EvalConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)

    @model_validator(mode="after")
    def _check(self) -> "Config":
        if self.label.cls_horizon not in self.label.horizons:
            raise ValueError("cls_horizon must be in horizons")
        if not (0 < self.label.lower_quantile < self.label.upper_quantile < 1):
            raise ValueError("invalid label quantiles")
        if self.split.train_end >= self.split.val_end:
            raise ValueError("train_end must be before val_end")
        return self

    def path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else REPO_ROOT / p


def load_config(path: str | Path, overrides: dict | None = None) -> Config:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg = Config.model_validate(raw)
    if overrides:
        data = cfg.model_dump()
        for dotted, v in overrides.items():
            node = data
            *parents, leaf = dotted.split(".")
            for k in parents:
                node = node[k]
            node[leaf] = v
        cfg = Config.model_validate(data)
    return cfg
