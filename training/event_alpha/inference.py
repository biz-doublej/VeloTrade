"""Model Output Contract — alpha 추정치만 출력. 주문 관련 필드는 절대 포함하지 않는다."""

from __future__ import annotations

from typing import Any

import numpy as np

from . import MODEL_VERSION
from .labels import CLASS_NAMES

# 계약 위반 방지: 이 키들은 어떤 출력에도 있으면 안 된다.
FORBIDDEN_KEYS = frozenset(
    {"quantity", "qty", "position_size", "size_pct", "order_type", "exchange", "side",
     "order", "account", "leverage", "notional", "price_limit", "limit_price"}
)

CONTRACT_KEYS = ("ticker", "event_id", "prediction_timestamp", "model_version", "direction",
                 "confidence", "alpha_1d", "alpha_3d", "alpha_5d")


def assert_contract(record: dict[str, Any]) -> None:
    bad = FORBIDDEN_KEYS & set(record)
    if bad:
        raise ValueError(f"order-related fields are forbidden in model output: {sorted(bad)}")


def make_record(
    ticker: str, event_id: str, prediction_timestamp: str, probs: np.ndarray, alphas: dict[int, float]
) -> dict[str, Any]:
    k = int(np.argmax(probs))
    rec = {
        "ticker": ticker,
        "event_id": event_id,
        "prediction_timestamp": prediction_timestamp,
        "model_version": MODEL_VERSION,
        "direction": CLASS_NAMES[k],
        "confidence": round(float(probs[k]), 4),
        **{f"alpha_{h}d": round(float(a), 6) for h, a in sorted(alphas.items())},
    }
    assert_contract(rec)
    return rec
