"""핵심 도메인 모델.

거래소 어댑터와 전략은 모두 이 타입들로 대화한다.
Decimal 사용 (float 부동소수점 오차로 금액·수량을 다루지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal


class AssetClass(str, Enum):
    US_STOCK = "us_stock"
    CRYPTO = "crypto"


OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
OrderStatus = Literal[
    "pending",          # 봇 내부에서만 존재 (어댑터로 보내기 전)
    "submitted",        # 거래소에 접수됨
    "partially_filled",
    "filled",
    "cancelled",
    "rejected",
]


@dataclass(slots=True)
class Quote:
    """시세. 어댑터가 발행한다."""

    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    timestamp: datetime
    exchange: str
    asset_class: AssetClass
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal(2)


@dataclass(slots=True)
class Position:
    """현재 보유 포지션. 어댑터가 거래소에서 동기화한다."""

    symbol: str
    qty: Decimal
    avg_entry_price: Decimal
    current_price: Decimal | None = None
    exchange: str = ""
    asset_class: AssetClass = AssetClass.US_STOCK

    @property
    def market_value(self) -> Decimal:
        price = self.current_price or self.avg_entry_price
        return self.qty * price

    @property
    def unrealized_pnl(self) -> Decimal:
        if self.current_price is None:
            return Decimal(0)
        return (self.current_price - self.avg_entry_price) * self.qty


@dataclass(slots=True)
class Order:
    """봇이 어댑터에 보내는 주문 요청."""

    symbol: str
    side: OrderSide
    type: OrderType
    qty: Decimal
    price: Decimal | None = None          # limit 일 때만
    client_order_id: str | None = None    # 멱등성 키 (재시도 보호)
    time_in_force: Literal["day", "gtc", "ioc", "fok"] = "day"


@dataclass(slots=True)
class OrderResult:
    """어댑터가 돌려주는 주문 결과."""

    client_order_id: str | None
    exchange_order_id: str
    symbol: str
    side: OrderSide
    type: OrderType
    status: OrderStatus
    qty: Decimal
    filled_qty: Decimal = Decimal(0)
    filled_avg_price: Decimal | None = None
    submitted_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Signal:
    """전략이 발생시키는 매매 신호.

    `size_pct` 는 자본 대비 비율(0~1). 봇이 RiskManager 통과시킨 뒤
    실제 qty 로 변환한다. 전략은 거래소·계좌 잔고를 모른다.
    """

    symbol: str
    side: OrderSide | Literal["hold"]
    size_pct: Decimal                          # 0.0 ~ 1.0
    confidence: float                          # 0.0 ~ 1.0
    reasoning: str
    strategy: str                              # 전략 이름
    created_at: datetime = field(default_factory=datetime.utcnow)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        return self.side in {"buy", "sell"} and self.size_pct > 0
