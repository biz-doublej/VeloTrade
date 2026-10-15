"""가격 로딩 + 시장 feature.

규약: feature 는 "event 직전 마지막 거래일(<= event date)의 종가까지" 과거 정보만 사용한다.
rolling 계산은 모두 과거 방향(closed on the right, 미래 shift 없음)이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

MARKET_FEATURES = [
    "ret_1d", "ret_5d", "ret_20d", "vol_20d", "vol_chg_20d", "px_vs_ma20",
    "spy_ret_1d", "spy_ret_5d", "spy_vol_20d", "qqq_ret_1d", "vix_level", "vix_chg_5d",
]


class PriceDataNotAvailable(RuntimeError):
    """PRICE_DATA_NOT_AVAILABLE — 가격 데이터가 없을 때 임의 값을 만들지 않고 중단한다."""


def load_price_json(path: Path) -> pd.DataFrame | None:
    """Yahoo chart JSON → 분할/배당 조정 OHLCV (index: 거래일 date)."""
    try:
        with open(path, encoding="utf-8") as f:
            res = json.load(f)["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        adj = res["indicators"]["adjclose"][0]["adjclose"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, OSError):
        return None
    df = pd.DataFrame(
        {
            "open": q["open"], "high": q["high"], "low": q["low"],
            "close": q["close"], "volume": q["volume"], "adjclose": adj,
        },
        index=pd.to_datetime(ts, unit="s").normalize(),
    )
    df = df.dropna(subset=["open", "close", "adjclose"])
    df = df[(df["open"] > 0) & (df["close"] > 0)]
    f = df["adjclose"] / df["close"]
    out = pd.DataFrame(
        {
            "open": df["open"] * f, "high": df["high"] * f, "low": df["low"] * f,
            "close": df["adjclose"], "volume": df["volume"].astype(float),
        }
    )
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out if len(out) else None


def price_features(px: pd.DataFrame) -> pd.DataFrame:
    """각 거래일 종가 기준 과거-only feature (행 t 는 t 종가까지의 정보)."""
    c = px["close"]
    r1 = c.pct_change(1)
    feat = pd.DataFrame(index=px.index)
    feat["ret_1d"] = r1
    feat["ret_5d"] = c.pct_change(5)
    feat["ret_20d"] = c.pct_change(20)
    feat["vol_20d"] = r1.rolling(20).std()
    feat["vol_chg_20d"] = px["volume"] / px["volume"].rolling(20).mean() - 1.0
    feat["px_vs_ma20"] = c / c.rolling(20).mean() - 1.0
    return feat


def load_market_frame(prices_dir: Path, symbols: list[str]) -> pd.DataFrame:
    """SPY/QQQ/VIX 시장 feature (index: 거래일)."""
    frames: dict[str, pd.DataFrame] = {}
    for s in symbols:
        df = load_price_json(prices_dir / f"{s}.json")
        if df is None:
            raise PriceDataNotAvailable(f"PRICE_DATA_NOT_AVAILABLE: {s} in {prices_dir}")
        frames[s] = df
    spy = frames["SPY"]
    spy_r1 = spy["close"].pct_change(1)
    out = pd.DataFrame(index=spy.index)
    out["spy_ret_1d"] = spy_r1
    out["spy_ret_5d"] = spy["close"].pct_change(5)
    out["spy_vol_20d"] = spy_r1.rolling(20).std()
    if "QQQ" in frames:
        out["qqq_ret_1d"] = frames["QQQ"]["close"].pct_change(1).reindex(out.index)
    if "_VIX" in frames:
        vix = frames["_VIX"]["close"].reindex(out.index)
        out["vix_level"] = vix
        out["vix_chg_5d"] = vix.pct_change(5)
    return out


def fit_feature_stats(df: pd.DataFrame, cols: list[str]) -> dict[str, dict[str, float]]:
    """train split 으로만 평균/표준편차 계산 (z-score)."""
    stats = {}
    for c in cols:
        x = df[c].astype(float)
        lo, hi = x.quantile(0.005), x.quantile(0.995)
        x = x.clip(lo, hi)
        stats[c] = {"mean": float(x.mean()), "std": float(x.std() or 1.0), "lo": float(lo), "hi": float(hi)}
    return stats


def apply_feature_stats(df: pd.DataFrame, cols: list[str], stats: dict) -> np.ndarray:
    out = np.zeros((len(df), len(cols)), dtype=np.float32)
    for j, c in enumerate(cols):
        s = stats[c]
        x = df[c].astype(float).clip(s["lo"], s["hi"]).fillna(s["mean"])
        out[:, j] = ((x - s["mean"]) / s["std"]).to_numpy(dtype=np.float32)
    return out
