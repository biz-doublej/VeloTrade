"""Strategy 추상 — 모든 매매 전략의 공통 인터페이스.

핵심 메서드:
  - on_quote(quote, ctx) → Signal | None : 시세 tick 마다 호출
  - on_event(event, ctx) → Signal | None : 외부 이벤트 (공시/뉴스/매크로) 발생 시
  - warmup(ctx)                            : 시작 시 historical close 로드

거래소·자본·DB 는 모두 ctx 를 통해서만 접근. 전략은 stateless 한 게 이상적이지만,
지표 캐시는 strategy 인스턴스가 보관해도 OK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from velotrade_trading.adapters.base import ExchangeAdapter
from velotrade_trading.core.portfolio import Portfolio
from velotrade_trading.core.types import Quote, Signal


@dataclass
class StrategyContext:
    """전략이 매 호출 시 받는 컨텍스트."""

    adapter: ExchangeAdapter
    portfolio: Portfolio
    params: dict[str, Any] = field(default_factory=dict)


class Strategy(ABC):
    """전략 베이스. 종목별 종가 윈도우는 베이스가 관리해 편하게 사용."""

    name: str = "abstract"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = params or {}
        self.window_size: int = int(self.params.get("window", 200))
        self._closes: dict[str, deque[Decimal]] = {}

    # --- 시세 윈도우 관리 ----------------------------------------------------

    async def warmup(self, symbol: str, ctx: StrategyContext) -> None:
        closes = await ctx.adapter.get_historical_closes(symbol, limit=self.window_size)
        self._closes[symbol] = deque(closes, maxlen=self.window_size)

    def _push_close(self, symbol: str, price: Decimal) -> None:
        dq = self._closes.setdefault(symbol, deque(maxlen=self.window_size))
        dq.append(price)

    def closes(self, symbol: str) -> list[Decimal]:
        return list(self._closes.get(symbol, []))

    # --- 인터페이스 ----------------------------------------------------------

    @abstractmethod
    async def on_quote(self, quote: Quote, ctx: StrategyContext) -> Signal | None: ...

    async def on_event(
        self, event: dict[str, Any], ctx: StrategyContext
    ) -> Signal | None:  # noqa: B027
        """외부 이벤트 핸들러. 기본은 무시. LLM 전략 등에서 오버라이드."""
        return None

    # --- 헬퍼 ----------------------------------------------------------------

    def _signal(
        self,
        *,
        symbol: str,
        side: str,
        size_pct: Decimal,
        confidence: float,
        reasoning: str,
        meta: dict[str, Any] | None = None,
    ) -> Signal:
        return Signal(
            symbol=symbol,
            side=side,  # type: ignore[arg-type]
            size_pct=size_pct,
            confidence=confidence,
            reasoning=reasoning,
            strategy=self.name,
            meta=meta or {},
        )
