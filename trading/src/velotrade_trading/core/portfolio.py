"""포트폴리오 — 현재 자본, 포지션 합계, 익스포저 계산.

봇은 매 tick 마다 Portfolio.refresh() 로 어댑터에서 동기화한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from velotrade_trading.core.types import Position


@dataclass
class Portfolio:
    """단일 거래소 계좌의 스냅샷."""

    exchange: str
    cash: Decimal = Decimal(0)              # 가용 자본 (USD / KRW / USDT 등)
    currency: str = "USD"
    positions: dict[str, Position] = field(default_factory=dict)

    # --- 계산 ---------------------------------------------------------------

    @property
    def positions_value(self) -> Decimal:
        return sum((p.market_value for p in self.positions.values()), Decimal(0))

    @property
    def equity(self) -> Decimal:
        """현금 + 포지션 평가액."""
        return self.cash + self.positions_value

    def position_pct(self, symbol: str) -> Decimal:
        """해당 종목이 전체 자본에서 차지하는 비율."""
        equity = self.equity
        if equity <= 0:
            return Decimal(0)
        pos = self.positions.get(symbol)
        if pos is None:
            return Decimal(0)
        return pos.market_value / equity

    def has_position(self, symbol: str) -> bool:
        pos = self.positions.get(symbol)
        return pos is not None and pos.qty != 0

    # --- 동기화 -------------------------------------------------------------

    def upsert_position(self, position: Position) -> None:
        if position.qty == 0:
            self.positions.pop(position.symbol, None)
        else:
            self.positions[position.symbol] = position

    def set_cash(self, cash: Decimal) -> None:
        self.cash = cash

    def replace_positions(self, positions: list[Position]) -> None:
        self.positions = {p.symbol: p for p in positions if p.qty != 0}
