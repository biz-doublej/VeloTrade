"""Paper(시뮬레이션) 어댑터.

용도:
  - Upbit 처럼 testnet 이 없는 거래소를 paper 모드에서 사용할 때.
  - 백테스트 / 단위 테스트.
  - Alpaca·Binance testnet 이 다운됐을 때의 폴백.

동작:
  - 실제 시세는 다른 어댑터(`market_feed`)에서 빌려온다.
  - 주문은 mid 가격에 즉시 fill (슬리피지 옵션으로 모사).
  - 모든 상태(현금·포지션·주문)는 메모리 보관. 봇이 DB 동기화.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal

from velotrade_trading.adapters.base import ExchangeAdapter
from velotrade_trading.core.types import (
    AssetClass,
    Order,
    OrderResult,
    Position,
    Quote,
)


class PaperExchange(ExchangeAdapter):
    def __init__(
        self,
        *,
        base_name: str,
        market_feed: ExchangeAdapter,
        starting_cash: Decimal = Decimal(10_000),
        quote_currency: str = "USD",
        asset_class: AssetClass = AssetClass.US_STOCK,
        slippage_bps: int = 5,
    ) -> None:
        """`market_feed` 는 시세만 빌려주는 실 어댑터 (paper 키 또는 read-only)."""
        self._name = f"paper:{base_name}"
        self._feed = market_feed
        self._cash = starting_cash
        self._quote_currency = quote_currency
        self._asset_class = asset_class
        self._slippage_bps = slippage_bps
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, OrderResult] = {}

    # --- 메타 ---------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_paper(self) -> bool:
        return True

    @property
    def asset_class(self) -> AssetClass:
        return self._asset_class

    @property
    def quote_currency(self) -> str:
        return self._quote_currency

    # --- 계좌 ---------------------------------------------------------------

    async def get_cash(self) -> Decimal:
        return self._cash

    async def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    # --- 시세 (feed 위임) ---------------------------------------------------

    async def get_quote(self, symbol: str) -> Quote:
        return await self._feed.get_quote(symbol)

    async def get_historical_closes(
        self, symbol: str, *, limit: int = 200, interval: str = "1d"
    ) -> list[Decimal]:
        return await self._feed.get_historical_closes(symbol, limit=limit, interval=interval)

    async def stream_quotes(self, symbols: list[str]) -> AsyncIterator[Quote]:
        async for quote in self._feed.stream_quotes(symbols):
            yield quote

    # --- 주문 (메모리 fill) -------------------------------------------------

    async def submit_order(self, order: Order) -> OrderResult:
        quote = await self.get_quote(order.symbol)
        # 슬리피지 모사: buy 는 ask+, sell 은 bid-
        slip = Decimal(self._slippage_bps) / Decimal(10_000)
        if order.side == "buy":
            fill_price = quote.ask * (Decimal(1) + slip)
        else:
            fill_price = quote.bid * (Decimal(1) - slip)

        notional = order.qty * fill_price

        # 잔고/포지션 검증
        if order.side == "buy":
            if notional > self._cash:
                return self._reject(order, f"insufficient cash: need {notional}, have {self._cash}")
            self._cash -= notional
            self._apply_buy(order.symbol, order.qty, fill_price)
        else:
            held = self._positions.get(order.symbol)
            if held is None or held.qty < order.qty:
                return self._reject(order, f"insufficient position: {order.symbol}")
            self._cash += notional
            self._apply_sell(order.symbol, order.qty, fill_price)

        result = OrderResult(
            client_order_id=order.client_order_id,
            exchange_order_id=f"paper-{uuid.uuid4().hex[:12]}",
            symbol=order.symbol,
            side=order.side,
            type=order.type,
            status="filled",
            qty=order.qty,
            filled_qty=order.qty,
            filled_avg_price=fill_price,
            submitted_at=datetime.utcnow(),
            raw={"paper": True, "slippage_bps": self._slippage_bps},
        )
        self._orders[result.exchange_order_id] = result
        return result

    async def cancel_order(self, exchange_order_id: str) -> None:
        # paper 는 즉시 fill 이라 cancel 대상 없음
        order = self._orders.get(exchange_order_id)
        if order and order.status in {"submitted", "partially_filled"}:
            order.status = "cancelled"

    async def get_order(self, exchange_order_id: str) -> OrderResult:
        if exchange_order_id not in self._orders:
            raise KeyError(exchange_order_id)
        return self._orders[exchange_order_id]

    async def close(self) -> None:
        await self._feed.close()

    # --- 포지션 계산 (FIFO 평균단가) ----------------------------------------

    def _apply_buy(self, symbol: str, qty: Decimal, price: Decimal) -> None:
        existing = self._positions.get(symbol)
        if existing is None:
            self._positions[symbol] = Position(
                symbol=symbol,
                qty=qty,
                avg_entry_price=price,
                current_price=price,
                exchange=self._name,
                asset_class=self._asset_class,
            )
        else:
            total_cost = existing.avg_entry_price * existing.qty + price * qty
            total_qty = existing.qty + qty
            existing.avg_entry_price = total_cost / total_qty
            existing.qty = total_qty
            existing.current_price = price

    def _apply_sell(self, symbol: str, qty: Decimal, price: Decimal) -> None:
        held = self._positions[symbol]
        held.qty -= qty
        held.current_price = price
        if held.qty == 0:
            del self._positions[symbol]

    def _reject(self, order: Order, reason: str) -> OrderResult:
        return OrderResult(
            client_order_id=order.client_order_id,
            exchange_order_id=f"paper-reject-{uuid.uuid4().hex[:8]}",
            symbol=order.symbol,
            side=order.side,
            type=order.type,
            status="rejected",
            qty=order.qty,
            submitted_at=datetime.utcnow(),
            raw={"paper": True, "reject_reason": reason},
        )
