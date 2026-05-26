"""Binance 어댑터 — 글로벌 코인.

Testnet: https://testnet.binance.vision (Spot Testnet)
Live:    https://api.binance.com

`python-binance` SDK 의존. paper 모드 = testnet.
스트리밍은 websocket. Day 2-3 에 정식 통합.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from datetime import datetime
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
    "NEW": "submitted",
    "PARTIALLY_FILLED": "partially_filled",
    "FILLED": "filled",
    "CANCELED": "cancelled",
    "EXPIRED": "cancelled",
    "REJECTED": "rejected",
}


class BinanceExchange(ExchangeAdapter):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        secret_key: str | None = None,
        use_testnet: bool | None = None,
    ) -> None:
        use_testnet_env = os.getenv("BINANCE_USE_TESTNET", "true").lower() == "true"
        self._is_paper = use_testnet if use_testnet is not None else use_testnet_env

        if self._is_paper:
            self._key = api_key or os.getenv("BINANCE_TESTNET_API_KEY", "")
            self._secret = secret_key or os.getenv("BINANCE_TESTNET_SECRET_KEY", "")
            self._base_url = "https://testnet.binance.vision"
        else:
            self._key = api_key or os.getenv("BINANCE_LIVE_API_KEY", "")
            self._secret = secret_key or os.getenv("BINANCE_LIVE_SECRET_KEY", "")
            self._base_url = "https://api.binance.com"

        if not self._key or not self._secret:
            raise RuntimeError(
                f"Binance credentials missing for "
                f"{'testnet' if self._is_paper else 'live'} mode"
            )

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-MBX-APIKEY": self._key},
            timeout=httpx.Timeout(15.0),
        )

    # --- 메타 ---------------------------------------------------------------

    @property
    def name(self) -> str:
        return "binance"

    @property
    def is_paper(self) -> bool:
        return self._is_paper

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.CRYPTO

    @property
    def quote_currency(self) -> str:
        return "USDT"

    # --- 인증 헬퍼 -----------------------------------------------------------

    def _sign(self, params: dict[str, str]) -> dict[str, str]:
        """Binance signed 요청 — timestamp + recvWindow + HMAC-SHA256 signature.

        recvWindow=5000ms 로 시간 차 ±5초 허용 (Binance 기본 5초).
        timestamp 는 local time - 1초 (server 보다 약간 과거로 안전 마진).
        """
        import hashlib
        import hmac
        from urllib.parse import urlencode

        # local 이 server 보다 빠를 수 있어 1초 보수적으로 빼기
        params["timestamp"] = str(int(time.time() * 1000) - 1000)
        params.setdefault("recvWindow", "5000")
        query = urlencode(params)
        sig = hmac.new(self._secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    # --- 계좌 ---------------------------------------------------------------

    async def get_cash(self) -> Decimal:
        r = await self._client.get("/api/v3/account", params=self._sign({}))
        r.raise_for_status()
        for bal in r.json()["balances"]:
            if bal["asset"] == self.quote_currency:
                return Decimal(bal["free"])
        return Decimal(0)

    async def get_positions(self) -> list[Position]:
        r = await self._client.get("/api/v3/account", params=self._sign({}))
        r.raise_for_status()
        positions: list[Position] = []
        for bal in r.json()["balances"]:
            free = Decimal(bal["free"])
            asset = bal["asset"]
            if free <= 0 or asset == self.quote_currency:
                continue
            symbol = f"{asset}{self.quote_currency}"
            # 평균 단가는 거래소가 제공 안 함 — 봇 DB 에서 보강
            positions.append(
                Position(
                    symbol=symbol,
                    qty=free,
                    avg_entry_price=Decimal(0),  # DB join 으로 보강
                    exchange=self.name,
                    asset_class=AssetClass.CRYPTO,
                )
            )
        return positions

    # --- 시세 ---------------------------------------------------------------

    async def get_quote(self, symbol: str) -> Quote:
        r = await self._client.get("/api/v3/ticker/bookTicker", params={"symbol": symbol})
        r.raise_for_status()
        data = r.json()
        bid = Decimal(data["bidPrice"])
        ask = Decimal(data["askPrice"])
        return Quote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=(bid + ask) / Decimal(2),
            timestamp=datetime.utcnow(),
            exchange=self.name,
            asset_class=AssetClass.CRYPTO,
            raw=data,
        )

    async def get_historical_closes(
        self, symbol: str, *, limit: int = 200, interval: str = "1d"
    ) -> list[Decimal]:
        r = await self._client.get(
            "/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        r.raise_for_status()
        # [openTime, open, high, low, close, volume, ...]
        return [Decimal(k[4]) for k in r.json()]

    async def stream_quotes(self, symbols: list[str]) -> AsyncIterator[Quote]:
        """Binance WebSocket bookTicker 스트림 (다중 심볼 combined stream).

        Testnet: wss://stream.testnet.binance.vision/stream?streams=...
        Live:    wss://stream.binance.com:9443/stream?streams=...

        bookTicker = 실시간 best bid/ask. 인증 불필요.
        Trade 채널은 별도. bookTicker 만으로 충분.
        연결 끊김 시 5초 후 재연결.
        """
        import json
        import websockets

        ws_base = (
            "wss://stream.testnet.binance.vision/stream"
            if self._is_paper
            else "wss://stream.binance.com:9443/stream"
        )
        # bookTicker stream 이름은 lowercase symbol
        streams = "/".join(f"{s.lower()}@bookTicker" for s in symbols)
        url = f"{ws_base}?streams={streams}"

        while True:
            try:
                async with websockets.connect(
                    url, ping_interval=180, ping_timeout=30, max_size=2**20
                ) as ws:
                    async for raw in ws:
                        try:
                            envelope = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        data = envelope.get("data") or envelope
                        # bookTicker: {u:updateId, s:SYMBOL, b:bidPrice, B:bidQty, a:askPrice, A:askQty}
                        sym = data.get("s")
                        bp = data.get("b")
                        ap = data.get("a")
                        if not (sym and bp and ap):
                            continue
                        try:
                            bid = Decimal(bp)
                            ask = Decimal(ap)
                        except Exception:
                            continue
                        yield Quote(
                            symbol=sym,
                            bid=bid,
                            ask=ask,
                            last=(bid + ask) / Decimal(2),
                            timestamp=datetime.utcnow(),
                            exchange=self.name,
                            asset_class=AssetClass.CRYPTO,
                            raw=data,
                        )
            except (
                websockets.exceptions.ConnectionClosed,
                websockets.exceptions.WebSocketException,
                ConnectionError,
                OSError,
            ):
                await asyncio.sleep(5.0)
                continue

    # --- 주문 ---------------------------------------------------------------

    async def submit_order(self, order: Order) -> OrderResult:
        params = {
            "symbol": order.symbol,
            "side": order.side.upper(),
            "type": "MARKET" if order.type == "market" else "LIMIT",
            "quantity": str(order.qty),
        }
        if order.type == "limit" and order.price is not None:
            params["price"] = str(order.price)
            params["timeInForce"] = "GTC"
        if order.client_order_id:
            params["newClientOrderId"] = order.client_order_id

        r = await self._client.post("/api/v3/order", params=self._sign(params))
        r.raise_for_status()
        return self._to_result(r.json())

    async def cancel_order(self, exchange_order_id: str) -> None:
        # Binance 는 symbol + orderId 둘 다 필요. 봇이 metadata 로 symbol 전달.
        raise NotImplementedError("use cancel_order_with_symbol(symbol, order_id)")

    async def get_order(self, exchange_order_id: str) -> OrderResult:
        raise NotImplementedError("use get_order_with_symbol(symbol, order_id)")

    async def cancel_order_with_symbol(self, symbol: str, exchange_order_id: str) -> None:
        params = self._sign({"symbol": symbol, "orderId": exchange_order_id})
        r = await self._client.delete("/api/v3/order", params=params)
        if r.status_code not in (200, 204):
            r.raise_for_status()

    async def get_order_with_symbol(self, symbol: str, exchange_order_id: str) -> OrderResult:
        params = self._sign({"symbol": symbol, "orderId": exchange_order_id})
        r = await self._client.get("/api/v3/order", params=params)
        r.raise_for_status()
        return self._to_result(r.json())

    def _to_result(self, data: dict) -> OrderResult:
        return OrderResult(
            client_order_id=data.get("clientOrderId"),
            exchange_order_id=str(data["orderId"]),
            symbol=data["symbol"],
            side=data["side"].lower(),  # type: ignore[arg-type]
            type=data["type"].lower(),  # type: ignore[arg-type]
            status=_STATUS_MAP.get(data["status"], "submitted"),
            qty=Decimal(data["origQty"]),
            filled_qty=Decimal(data.get("executedQty", "0")),
            filled_avg_price=(
                Decimal(data["cummulativeQuoteQty"]) / Decimal(data["executedQty"])
                if Decimal(data.get("executedQty", "0")) > 0
                else None
            ),
            submitted_at=(
                datetime.fromtimestamp(data["transactTime"] / 1000)
                if data.get("transactTime")
                else None
            ),
            raw=data,
        )

    async def close(self) -> None:
        await self._client.aclose()
