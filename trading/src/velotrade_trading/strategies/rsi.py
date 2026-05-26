"""RSI 전략 — 과매도(<oversold) 매수, 과매수(>overbought) 매도.

파라미터:
  - period: RSI 계산 기간 (default 14)
  - oversold: 매수 임계 (default 30)
  - overbought: 매도 임계 (default 70)
  - size_pct: 시그널당 자본 비율 (default 0.05)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from velotrade_trading.core.types import Quote, Signal
from velotrade_trading.strategies.base import Strategy, StrategyContext


def compute_rsi(closes: list[Decimal], period: int = 14) -> Decimal | None:
    """Wilder smoothing RSI. closes 는 오래된 것 → 최근."""
    if len(closes) < period + 1:
        return None
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(diff if diff > 0 else Decimal(0))
        losses.append(-diff if diff < 0 else Decimal(0))

    avg_gain = sum(gains[:period]) / Decimal(period)
    avg_loss = sum(losses[:period]) / Decimal(period)

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * Decimal(period - 1) + gains[i]) / Decimal(period)
        avg_loss = (avg_loss * Decimal(period - 1) + losses[i]) / Decimal(period)

    if avg_loss == 0:
        return Decimal(100)
    rs = avg_gain / avg_loss
    return Decimal(100) - (Decimal(100) / (Decimal(1) + rs))


class RSIStrategy(Strategy):
    name = "rsi"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        p = self.params
        self.period: int = int(p.get("period", 14))
        self.oversold: Decimal = Decimal(str(p.get("oversold", 30)))
        self.overbought: Decimal = Decimal(str(p.get("overbought", 70)))
        self.size_pct: Decimal = Decimal(str(p.get("size_pct", 0.05)))
        # 최소 윈도우 보장
        self.window_size = max(self.window_size, self.period * 4)

    async def on_quote(self, quote: Quote, ctx: StrategyContext) -> Signal | None:
        self._push_close(quote.symbol, quote.last)
        closes = self.closes(quote.symbol)
        rsi = compute_rsi(closes, self.period)
        if rsi is None:
            return None

        if rsi <= self.oversold:
            return self._signal(
                symbol=quote.symbol,
                side="buy",
                size_pct=self.size_pct,
                confidence=float((self.oversold - rsi) / self.oversold + Decimal("0.5")),
                reasoning=f"RSI({self.period})={rsi:.1f} <= oversold({self.oversold})",
                meta={"rsi": float(rsi), "period": self.period},
            )
        if rsi >= self.overbought:
            return self._signal(
                symbol=quote.symbol,
                side="sell",
                size_pct=self.size_pct,
                confidence=float((rsi - self.overbought) / (Decimal(100) - self.overbought)
                                 + Decimal("0.5")),
                reasoning=f"RSI({self.period})={rsi:.1f} >= overbought({self.overbought})",
                meta={"rsi": float(rsi), "period": self.period},
            )
        return None
