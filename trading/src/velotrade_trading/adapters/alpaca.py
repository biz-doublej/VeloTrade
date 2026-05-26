"""Alpaca 어댑터 — 미국 주식.

Paper:  https://paper-api.alpaca.markets   (별도 키)
Live:   https://api.alpaca.markets

`alpaca-py` SDK 의존. paper / live 는 환경변수로 분기.

⚠️ 시세 스트리밍은 alpaca-py 의 StockDataStream 을 사용하지만,
   Day 2-3 에 정식 통합. 현재는 REST polling 으로 stream_quotes 를 구현해
   봇 루프가 동작하도록 한다.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal

import httpx

from velotrade_trading.adapters.base import ExchangeAdapter
from velotrade_trading.core.types import (
    AssetClass,
    Order,
    OrderResult,
    OrderStatus,
    Position,
    Quote,
)


_STATUS_MAP: dict[str, OrderStatus] = {
    "new": "submitted",
    "accepted": "submitted",
    "pending_new": "submitted",
    "partially_filled": "partially_filled",
    "filled": "filled",
    "canceled": "cancelled",
    "rejected": "rejected",
    "expired": "cancelled",
}


class AlpacaExchange(ExchangeAdapter):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
        is_paper: bool | None = None,
    ) -> None:
        # paper 키 우선 (안전 기본값)
        env_paper = os.getenv("ALPACA_PAPER_API_KEY")
        env_paper_secret = os.getenv("ALPACA_PAPER_SECRET_KEY")
        env_live = os.getenv("ALPACA_LIVE_API_KEY")
        env_live_secret = os.getenv("ALPACA_LIVE_SECRET_KEY")

        if api_key and secret_key:
            self._key = api_key
            self._secret = secret_key
            self._is_paper = bool(is_paper) if is_paper is not None else True
        elif env_paper and env_paper_secret:
            self._key = env_paper
            self._secret = env_paper_secret
            self._is_paper = True
        elif env_live and env_live_secret:
            self._key = env_live
            self._secret = env_live_secret
            self._is_paper = False
        else:
            raise RuntimeError(
                "Alpaca credentials missing — set ALPACA_PAPER_API_KEY/SECRET_KEY in .env"
            )

        self._base_url = base_url or (
            "https://paper-api.alpaca.markets" if self._is_paper else "https://api.alpaca.markets"
        )
        self._data_url = "https://data.alpaca.markets"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "APCA-API-KEY-ID": self._key,
                "APCA-API-SECRET-KEY": self._secret,
            },
            timeout=httpx.Timeout(15.0),
        )
        self._data_client = httpx.AsyncClient(
            base_url=self._data_url,
            headers={
                "APCA-API-KEY-ID": self._key,
                "APCA-API-SECRET-KEY": self._secret,
            },
            timeout=httpx.Timeout(15.0),
        )

    # --- 메타 ---------------------------------------------------------------

    @property
    def name(self) -> str:
        return "alpaca"

    @property
    def is_paper(self) -> bool:
        return self._is_paper

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.US_STOCK

    @property
    def quote_currency(self) -> str:
        return "USD"

    # --- 계좌 ---------------------------------------------------------------

    async def get_cash(self) -> Decimal:
        r = await self._client.get("/v2/account")
        r.raise_for_status()
        return Decimal(r.json()["cash"])

    async def get_positions(self) -> list[Position]:
        r = await self._client.get("/v2/positions")
        r.raise_for_status()
        return [
            Position(
                symbol=p["symbol"],
                qty=Decimal(p["qty"]),
                avg_entry_price=Decimal(p["avg_entry_price"]),
                current_price=Decimal(p["current_price"]) if p.get("current_price") else None,
                exchange=self.name,
                asset_class=AssetClass.US_STOCK,
            )
            for p in r.json()
        ]

    # --- 시세 ---------------------------------------------------------------

    async def get_quote(self, symbol: str) -> Quote:
        r = await self._data_client.get(f"/v2/stocks/{symbol}/quotes/latest")
        r.raise_for_status()
        q = r.json()["quote"]
        bid = Decimal(str(q["bp"]))
        ask = Decimal(str(q["ap"]))
        # latest trade for "last"
        last = (bid + ask) / Decimal(2)
        return Quote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=last,
            timestamp=datetime.fromisoformat(q["t"].replace("Z", "+00:00")),
            exchange=self.name,
            asset_class=AssetClass.US_STOCK,
            raw=q,
        )

    async def get_historical_closes(
        self, symbol: str, *, limit: int = 200, interval: str = "1d"
    ) -> list[Decimal]:
        # alpaca timeframe: 1Min, 5Min, 15Min, 1Hour, 1Day
        tf_map = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "1h": "1Hour", "1d": "1Day"}
        tf = tf_map.get(interval, "1Day")
        end = datetime.utcnow() - timedelta(minutes=16)  # SIP 데이터 16분 지연
        r = await self._data_client.get(
            f"/v2/stocks/{symbol}/bars",
            params={
                "timeframe": tf,
                "limit": limit,
                "end": end.isoformat() + "Z",
                "adjustment": "raw",
            },
        )
        r.raise_for_status()
        bars = r.json().get("bars", [])
        return [Decimal(str(b["c"])) for b in bars]

    async def stream_quotes(self, symbols: list[str]) -> AsyncIterator[Quote]:
        # 임시 polling. Day 2-3 에 alpaca-py StockDataStream 으로 교체.
        while True:
            for sym in symbols:
                try:
                    yield await self.get_quote(sym)
                except Exception:
                    continue
            await asyncio.sleep(5.0)

    # --- 주문 ---------------------------------------------------------------

    async def submit_order(self, order: Order) -> OrderResult:
        payload = {
            "symbol": order.symbol,
            "qty": str(order.qty),
            "side": order.side,
            "type": order.type,
            "time_in_force": order.time_in_force,
        }
        if order.type == "limit" and order.price is not None:
            payload["limit_price"] = str(order.price)
        if order.client_order_id:
            payload["client_order_id"] = order.client_order_id

        r = await self._client.post("/v2/orders", json=payload)
        r.raise_for_status()
        return self._to_result(r.json())

    async def cancel_order(self, exchange_order_id: str) -> None:
        r = await self._client.delete(f"/v2/orders/{exchange_order_id}")
        if r.status_code not in (200, 204):
            r.raise_for_status()

    async def get_order(self, exchange_order_id: str) -> OrderResult:
        r = await self._client.get(f"/v2/orders/{exchange_order_id}")
        r.raise_for_status()
        return self._to_result(r.json())

    def _to_result(self, data: dict) -> OrderResult:
        return OrderResult(
            client_order_id=data.get("client_order_id"),
            exchange_order_id=data["id"],
            symbol=data["symbol"],
            side=data["side"],
            type=data["order_type"] if "order_type" in data else data.get("type", "market"),
            status=_STATUS_MAP.get(data["status"], "submitted"),
            qty=Decimal(data["qty"]),
            filled_qty=Decimal(data.get("filled_qty", "0")),
            filled_avg_price=(
                Decimal(data["filled_avg_price"]) if data.get("filled_avg_price") else None
            ),
            submitted_at=(
                datetime.fromisoformat(data["submitted_at"].replace("Z", "+00:00"))
                if data.get("submitted_at")
                else None
            ),
            raw=data,
        )

    async def close(self) -> None:
        await self._client.aclose()
        await self._data_client.aclose()
