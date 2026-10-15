"""raw news parquet + price json → processed event table (+ tokenization).

data/raw → processed → split → training. 원본(raw)은 수정하지 않는다.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import Config
from .features import (
    MARKET_FEATURES,
    PriceDataNotAvailable,
    load_market_frame,
    load_price_json,
    price_features,
)
from .labels import classify, fit_thresholds, forward_window_return
from .split import assert_chronological, assign_split

log = logging.getLogger("event_alpha")

_WS = re.compile(r"\s+")


def _clean(s: str) -> str:
    return _WS.sub(" ", html.unescape(s)).strip()


def make_event_id(ticker: str, date: str, headline: str) -> str:
    return hashlib.sha1(f"{ticker}|{date}|{headline}".encode()).hexdigest()[:16]


def build_text(row: pd.Series, cfg: Config) -> str:
    parts = []
    if cfg.data.include_ticker_in_text:
        parts.append(f"[TICKER] {row['ticker']}")
    if cfg.data.include_publisher_in_text:
        parts.append(f"[SRC] {row['publisher']}")
    parts.append(f"[HEADLINE] {row['headline']}")
    return " ".join(parts)


def _load_news(cfg: Config) -> pd.DataFrame:
    p = cfg.path(cfg.paths.news_parquet)
    if not p.exists():
        raise FileNotFoundError(f"news parquet not found: {p}")
    df = pd.read_parquet(p, columns=["headline", "publisher", "date", "stock"])
    df = df.rename(columns={"stock": "ticker"})
    df["event_date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.drop(columns=["date"])
    df = df[df["event_date"] >= pd.Timestamp("2010-01-01")]  # 1969-12-31 등 epoch 오류 제거
    df["headline"] = df["headline"].astype(str).map(_clean)
    df = df[df["headline"].str.len() >= cfg.data.min_headline_chars]
    df = df.drop_duplicates(subset=["ticker", "event_date", "headline"])
    return df.reset_index(drop=True)


def build_processed(cfg: Config) -> tuple[pd.DataFrame, dict[str, Any]]:
    prices_dir = cfg.path(cfg.paths.prices_dir)
    if not prices_dir.exists() or not any(prices_dir.glob("*.json")):
        raise PriceDataNotAvailable(f"PRICE_DATA_NOT_AVAILABLE: {prices_dir}")

    news = _load_news(cfg)
    market = load_market_frame(prices_dir, cfg.data.market_symbols)
    bench = load_price_json(prices_dir / f"{cfg.data.benchmark}.json")
    assert bench is not None

    skip = set(cfg.data.market_symbols) | {cfg.data.benchmark}
    avail = {p.stem for p in prices_dir.glob("*.json")} - skip
    counts = news[news["ticker"].isin(avail)]["ticker"].value_counts()
    tickers = list(counts.index[: cfg.data.max_tickers])
    news = news[news["ticker"].isin(tickers)]
    log.info("news rows=%d tickers=%d", len(news), len(tickers))

    horizons = cfg.label.horizons
    pieces: list[pd.DataFrame] = []
    for tk, g in news.groupby("ticker"):
        px = load_price_json(prices_dir / f"{tk}.json")
        if px is None or len(px) < cfg.data.min_price_history_days + max(horizons) + 5:
            continue
        dates = px.index.values  # datetime64[ns], 정렬됨
        ev = g["event_date"].values
        # t0: event date 이후 첫 거래일 (strictly after). feature 일: t0-1 (<= event date)
        t0 = np.searchsorted(dates, ev, side="right")
        fi = t0 - 1
        ok = (fi >= cfg.data.min_price_history_days) & (t0 < len(dates))
        if not ok.any():
            continue
        g = g[ok].copy()
        t0, fi = t0[ok], fi[ok]

        feats = price_features(px).iloc[fi].reset_index(drop=True)
        mfeat = market.reindex(px.index).ffill(limit=3).iloc[fi].reset_index(drop=True)
        spy_o = bench["open"].reindex(px.index).to_numpy()
        spy_c = bench["close"].reindex(px.index).to_numpy()
        o, c = px["open"].to_numpy(), px["close"].to_numpy()

        out = g.reset_index(drop=True)
        out["feature_date"] = px.index[fi].values
        out["entry_date"] = px.index[t0].values
        for col in feats.columns:
            out[col] = feats[col].values
        for col in mfeat.columns:
            out[col] = mfeat[col].values
        for h in horizons:
            r = forward_window_return(o, c, t0, h)
            b = forward_window_return(spy_o, spy_c, t0, h)
            out[f"ret_fwd_{h}d"] = r
            out[f"excess_return_{h}d"] = r - b
        pieces.append(out)

    if not pieces:
        raise PriceDataNotAvailable("PRICE_DATA_NOT_AVAILABLE: no events aligned with prices")
    df = pd.concat(pieces, ignore_index=True)
    df = df.dropna(subset=[f"excess_return_{h}d" for h in horizons])
    df = df.dropna(subset=MARKET_FEATURES, how="all")
    df = df.sort_values(["event_date", "ticker"]).reset_index(drop=True)

    if cfg.data.max_events is not None and len(df) > cfg.data.max_events:
        # 시간 순서 유지 + 균등 간격 추출 (random split/shuffle 아님)
        idx = np.linspace(0, len(df) - 1, cfg.data.max_events).astype(int)
        df = df.iloc[idx].reset_index(drop=True)

    df["event_id"] = [
        make_event_id(t, str(d.date()), h)
        for t, d, h in zip(df["ticker"], df["event_date"], df["headline"], strict=True)
    ]
    df["text"] = df.apply(lambda r: build_text(r, cfg), axis=1)

    # --- split / label (threshold 는 train 만 사용) -----------------------------------
    df["split"] = assign_split(df["event_date"], cfg.split)
    assert_chronological(df[df["split"] != "embargo"])
    tr = df[df["split"] == "train"]
    thr = fit_thresholds(tr[f"excess_return_{cfg.label.cls_horizon}d"], cfg.label)
    df["y_cls"] = classify(df[f"excess_return_{cfg.label.cls_horizon}d"], thr)
    for h in horizons:
        t = fit_thresholds(tr[f"excess_return_{h}d"], cfg.label)
        df[f"y_reg_{h}d"] = df[f"excess_return_{h}d"].clip(t["winsor_lo"], t["winsor_hi"])

    # --- leakage assertions ------------------------------------------------------
    assert (df["feature_date"] < df["entry_date"]).all(), "feature_date must precede entry_date"
    assert (df["feature_date"] <= df["event_date"]).all(), "feature must not be after event date"
    assert (df["entry_date"] > df["event_date"]).all(), "entry must be after event date"

    meta = {
        "n_events": int(len(df)),
        "n_tickers": int(df["ticker"].nunique()),
        "thresholds_train_only": thr,
        "price_universe_note": "survivorship bias: delisted tickers missing from Yahoo are absent",
    }
    return df, meta


def tokenize_texts(texts: list[str], tokenizer_dir: Path, max_length: int) -> np.ndarray:
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(tokenizer_dir), local_files_only=True)
    ids = np.zeros((len(texts), max_length), dtype=np.int32)
    bs = 20000
    for i in range(0, len(texts), bs):
        enc = tok(
            texts[i : i + bs], truncation=True, max_length=max_length,
            padding="max_length", return_attention_mask=False,
        )
        ids[i : i + bs] = np.asarray(enc["input_ids"], dtype=np.int32)
    return ids
