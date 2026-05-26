"""Moving Average Cross — 단기 MA가 장기 MA를 상향 돌파 시 매수, 하향 돌파 시 매도.

파라미터:
  - fast: 단기 기간 (default 20)
  - slow: 장기 기간 (default 50)
  - size_pct: 시그널당 자본 비율 (default 0.05)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from velotrade_trading.core.types import Quote, Signal
from velotrade_trading.strategies.base import Strategy, StrategyContext


def sma(values: list[Decimal], period: int) -> Decimal | None:
    if len(values) < period:
        return None
    window = values[-period:]
    return sum(window, Decimal(0)) / Decimal(period)


class MACrossStrategy(Strategy):
    name = "ma_cross"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        p = self.params
        self.fast: int = int(p.get("fast", 20))
        self.slow: int = int(p.get("slow", 50))
        self.size_pct: Decimal = Decimal(str(p.get("size_pct", 0.05)))
        self.window_size = max(self.window_size, self.slow * 4)
        # 종목별 직전 cross 상태
        self._last_state: dict[str, str] = {}

    async def on_quote(self, quote: Quote, ctx: StrategyContext) -> Signal | None:
        self._push_close(quote.symbol, quote.last)
        closes = self.closes(quote.symbol)
        fast = sma(closes, self.fast)
        slow = sma(closes, self.slow)
        if fast is None or slow is None:
            return None

        state = "above" if fast > slow else "below" if fast < slow else "equal"
        prev = self._last_state.get(quote.symbol)
        self._last_state[quote.symbol] = state

        if prev is None or state == prev or state == "equal":
            return None

        # 골든 크로스 ↑
        if prev == "below" and state == "above":
            return self._signal(
                symbol=quote.symbol,
                side="buy",
                size_pct=self.size_pct,
                confidence=0.6,
                reasoning=(
                    f"golden cross: MA({self.fast})={fast:.2f} > MA({self.slow})={slow:.2f}"
                ),
                meta={"fast_ma": float(fast), "slow_ma": float(slow)},
            )
        # 데드 크로스 ↓
        if prev == "above" and state == "below":
            return self._signal(
                symbol=quote.symbol,
                side="sell",
                size_pct=self.size_pct,
                confidence=0.6,
                reasoning=(
                    f"dead cross: MA({self.fast})={fast:.2f} < MA({self.slow})={slow:.2f}"
                ),
                meta={"fast_ma": float(fast), "slow_ma": float(slow)},
            )
        return None
