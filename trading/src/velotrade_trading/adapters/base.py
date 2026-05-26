"""ExchangeAdapter — 모든 거래소 어댑터의 공통 인터페이스.

전략·봇·리스크매니저는 거래소를 모른다. 이 인터페이스만 안다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from decimal import Decimal

from velotrade_trading.core.types import (
    AssetClass,
    Order,
    OrderResult,
    Position,
    Quote,
)


class ExchangeAdapter(ABC):
    """비동기 거래소 어댑터."""

    # --- 메타 ----------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """'alpaca' | 'binance' | 'upbit' | 'paper:<base>' 등."""

    @property
    @abstractmethod
    def is_paper(self) -> bool:
        """True 면 실거래가 아닌 paper/testnet/시뮬레이터."""

    @property
    @abstractmethod
    def asset_class(self) -> AssetClass: ...

    @property
    @abstractmethod
    def quote_currency(self) -> str:
        """'USD' | 'USDT' | 'KRW' 등."""

    # --- 계좌 / 포지션 -------------------------------------------------------

    @abstractmethod
    async def get_cash(self) -> Decimal: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    # --- 시세 ----------------------------------------------------------------

    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    async def get_historical_closes(
        self, symbol: str, *, limit: int = 200, interval: str = "1d"
    ) -> list[Decimal]:
        """기술 지표 계산용 종가 시리즈 (오래된 것 → 최근 순)."""

    @abstractmethod
    def stream_quotes(self, symbols: list[str]) -> AsyncIterator[Quote]:
        """실시간 시세 스트림. async for 로 소비."""

    # --- 주문 ----------------------------------------------------------------

    @abstractmethod
    async def submit_order(self, order: Order) -> OrderResult: ...

    @abstractmethod
    async def cancel_order(self, exchange_order_id: str) -> None: ...

    @abstractmethod
    async def get_order(self, exchange_order_id: str) -> OrderResult: ...

    # --- 수명주기 ------------------------------------------------------------

    async def __aenter__(self) -> "ExchangeAdapter":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:  # noqa: B027
        """필요 시 오버라이드 (httpx client, websocket 정리)."""
        return None
