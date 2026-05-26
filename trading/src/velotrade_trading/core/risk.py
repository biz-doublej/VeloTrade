"""리스크 매니저 — 전략의 시그널을 검증해 위험한 주문을 차단한다.

원칙:
  1. 시그널은 항상 검증을 거친다 (전략을 신뢰하지 않는다).
  2. 위반 시 RiskRejected 예외 — 봇이 잡아서 시그널만 기록하고 주문은 안 보낸다.
  3. 모든 한도는 RiskConfig 로 외부에서 주입 (.env 또는 yaml).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from velotrade_trading.core.portfolio import Portfolio
from velotrade_trading.core.types import Order, Quote, Signal


class RiskRejected(Exception):
    """리스크 한도 위반 — 시그널을 거부."""


@dataclass(slots=True)
class RiskConfig:
    """모든 비율은 0.0 ~ 1.0 (계좌 equity 기준)."""

    max_position_pct: Decimal = Decimal("0.05")     # 한 번 주문 최대 비중
    max_per_symbol_pct: Decimal = Decimal("0.20")   # 종목당 최대 보유
    daily_loss_pct: Decimal = Decimal("0.02")       # 일일 실현 손실 한도
    min_order_value: Decimal = Decimal(10)          # 최소 주문 금액 (수수료 효율)
    allow_short: bool = False                       # 공매도 허용


@dataclass
class RiskState:
    """일일 누적 손익 추적 (간단 버전 — DB 정식 기록은 별개)."""

    day: date
    realized_pnl: Decimal = Decimal(0)


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config
        self._state = RiskState(day=datetime.utcnow().date())

    # --- 일일 손익 -----------------------------------------------------------

    def record_realized_pnl(self, pnl: Decimal) -> None:
        today = datetime.utcnow().date()
        if today != self._state.day:
            self._state = RiskState(day=today)
        self._state.realized_pnl += pnl

    # --- 시그널 검증 ---------------------------------------------------------

    def validate(self, signal: Signal, portfolio: Portfolio, quote: Quote) -> Order:
        """시그널 → 실제 주문. 위반 시 RiskRejected."""
        if not signal.is_actionable:
            raise RiskRejected(f"hold/0-size signal: {signal}")

        # 공매도 가드
        if signal.side == "sell" and not portfolio.has_position(signal.symbol):
            if not self.config.allow_short:
                raise RiskRejected(f"short not allowed: {signal.symbol}")

        # 일일 손실 한도
        daily_limit = -(portfolio.equity * self.config.daily_loss_pct)
        if self._state.realized_pnl <= daily_limit:
            raise RiskRejected(
                f"daily loss limit reached: realized={self._state.realized_pnl}, "
                f"limit={daily_limit}"
            )

        # 단일 거래 최대 비중
        size_pct = min(signal.size_pct, self.config.max_position_pct)
        notional = portfolio.equity * size_pct
        if notional < self.config.min_order_value:
            raise RiskRejected(
                f"notional {notional} below min {self.config.min_order_value}"
            )

        # 종목 집중도 (buy 일 때 사후 잔고 추정)
        if signal.side == "buy":
            current_pct = portfolio.position_pct(signal.symbol)
            projected_pct = current_pct + size_pct
            if projected_pct > self.config.max_per_symbol_pct:
                # 한도까지만 채워서 부분 진입
                allowable = self.config.max_per_symbol_pct - current_pct
                if allowable <= 0:
                    raise RiskRejected(
                        f"per-symbol cap reached: {signal.symbol} at {current_pct:.2%}"
                    )
                size_pct = min(size_pct, allowable)
                notional = portfolio.equity * size_pct

        # 가격 → 수량
        price = quote.ask if signal.side == "buy" else quote.bid
        if price <= 0:
            raise RiskRejected(f"invalid price for {signal.symbol}: {price}")
        qty = (notional / price).quantize(Decimal("0.00000001"))
        if qty <= 0:
            raise RiskRejected(f"computed qty <= 0 for {signal.symbol}")

        # sell 일 때 보유분 초과 금지
        if signal.side == "sell":
            held = portfolio.positions.get(signal.symbol)
            if held is None or held.qty < qty:
                # 보유분 전량으로 조정
                if held is None or held.qty <= 0:
                    raise RiskRejected(f"no position to sell: {signal.symbol}")
                qty = held.qty

        return Order(
            symbol=signal.symbol,
            side=signal.side,
            type="market",
            qty=qty,
            client_order_id=f"vt-{signal.strategy}-{int(signal.created_at.timestamp())}",
        )
