"""Chronological split — random split 금지. embargo 로 horizon label 겹침을 차단."""

from __future__ import annotations

import pandas as pd

from .config import SplitConfig


def assign_split(event_dates: pd.Series, cfg: SplitConfig) -> pd.Series:
    """train / val / test / embargo 라벨. event_dates: datetime64."""
    d = pd.to_datetime(event_dates)
    train_end = pd.Timestamp(cfg.train_end)
    val_end = pd.Timestamp(cfg.val_end)
    emb = pd.Timedelta(days=cfg.embargo_days)

    out = pd.Series("test", index=d.index, dtype="object")
    out[d <= val_end] = "val"
    out[d <= train_end] = "train"
    # split 마지막 embargo_days 는 label window(최대 5 거래일)가 다음 split 과 겹치므로 제외
    out[(d > train_end - emb) & (d <= train_end)] = "embargo"
    out[(d > val_end - emb) & (d <= val_end)] = "embargo"
    return out


def split_summary(df: pd.DataFrame) -> dict:
    res: dict = {}
    for name, g in df.groupby("split"):
        res[str(name)] = {
            "n": int(len(g)),
            "start": str(g["event_date"].min().date()),
            "end": str(g["event_date"].max().date()),
            "n_tickers": int(g["ticker"].nunique()),
        }
    return res


def assert_chronological(df: pd.DataFrame) -> None:
    tr = df.loc[df["split"] == "train", "event_date"]
    va = df.loc[df["split"] == "val", "event_date"]
    te = df.loc[df["split"] == "test", "event_date"]
    if len(tr) and len(va) and tr.max() >= va.min():
        raise AssertionError("train/val overlap in time")
    if len(va) and len(te) and va.max() >= te.min():
        raise AssertionError("val/test overlap in time")
