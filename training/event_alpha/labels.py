"""Label 생성.

타이밍 규약 (leakage 방지의 핵심):
  * 뉴스 date D 는 날짜 단위(시각 없음)라, 의사결정 시점을 "D 종가 이후"로 보수적으로 가정한다.
  * 진입가 = D 다음 거래일(t0)의 시가. 보유 h 일 후 종가 청산: close[t0+h-1] / open[t0] - 1.
  * excess_return_h = 종목 수익률 - SPY 동일 구간 수익률.
  * 분류 threshold / winsorize 한계는 train 분포로만 산출한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import LabelConfig

CLASS_NAMES = ["DOWN", "NEUTRAL", "UP"]


def forward_window_return(
    open_: np.ndarray, close: np.ndarray, t0: np.ndarray, h: int
) -> np.ndarray:
    """t0(거래일 index) 진입 시가 → close[t0+h-1] 청산 수익률. 범위 밖은 NaN."""
    n = len(close)
    t_end = t0 + h - 1
    valid = (t0 >= 0) & (t_end < n)
    out = np.full(len(t0), np.nan)
    idx = np.where(valid)[0]
    out[idx] = close[t_end[idx]] / open_[t0[idx]] - 1.0
    return out


def fit_thresholds(train_excess: pd.Series, cfg: LabelConfig) -> dict[str, float]:
    x = train_excess.dropna()
    return {
        "lower": float(x.quantile(cfg.lower_quantile)),
        "upper": float(x.quantile(cfg.upper_quantile)),
        "winsor_lo": float(x.quantile(cfg.winsor_pct)),
        "winsor_hi": float(x.quantile(1 - cfg.winsor_pct)),
    }


def classify(excess: pd.Series, thr: dict[str, float]) -> pd.Series:
    out = pd.Series(1, index=excess.index, dtype="int8")  # NEUTRAL
    out[excess <= thr["lower"]] = 0
    out[excess >= thr["upper"]] = 2
    out[excess.isna()] = -1
    return out


def label_distribution(df: pd.DataFrame, col: str = "y_cls") -> dict:
    res = {}
    for split, g in df.groupby("split"):
        vc = g[col].value_counts().sort_index()
        res[str(split)] = {CLASS_NAMES[int(k)]: int(v) for k, v in vc.items() if k >= 0}
    return res
