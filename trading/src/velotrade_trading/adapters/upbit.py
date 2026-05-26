"""Upbit 어댑터 — 국내 코인 (KRW 마켓).

API: https://docs.upbit.com
인증: JWT (access key + secret + nonce). 출금 권한 OFF, IP 화이트리스트 필수.

⚠️ Upbit 는 testnet 이 없다. paper 모드는 PaperExchange 가 이 어댑터를 market_feed
   로 사용해 시뮬레이션한다. 이 모듈 자체는 항상 실 API 와 통신.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

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
    "wait": "submitted",
    "watch": "submitted",
    "trade": "partially_filled",
    "done": "filled",
    "cancel": "cancelled",
}


class UpbitExchange(ExchangeAdapter):
    """Upbit 는 실거래 전용. paper 모드는 PaperExchange 가 감싸 사용."""

    def __init__(
        self,
        *,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self._access = access_key or os.getenv("UPBIT_ACCESS_KEY", "")
        self._secret = secret_key or os.getenv("UPBIT_SECRET_KEY", "")
        if not self._access or not self._secret:
            raise RuntimeError("Upbit credentials missing — set UPBIT_ACCESS_KEY/SECRET_KEY")
        self._base_url = "https://api.upbit.com"
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=httpx.Timeout(15.0))

    # --- 메타 ---------------------------------------------------------------

    @property
    def name(self) -> str:
        return "upbit"

    @property
    def is_paper(self) -> bool:
        # 실 API. paper 시뮬레이션은 PaperExchange 에서 감싼다.
        return False

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.CRYPTO

    @property
    def quote_currency(self) -> str:
        return "KRW"

    # --- JWT 인증 ------------------------------------------------------------

    def _jwt_header(self, query: dict[str, str] | None = None) -> dict[str, str]:
        import jwt  # PyJWT (alpaca-py 의존성으로 함께 설치되거나 명시 설치)

        payload: dict[str, str | int] = {
            "access_key": self._access,
            "nonce": str(uuid.uuid4()),
        }
        if query:
            qstring = urlencode(query).encode()
            m = hashlib.sha512()
            m.update(qstring)
            payload["query_hash"] = m.hexdigest()
            payload["query_hash_alg"] = "SHA512"

        token = jwt.encode(payload, self._secret, algorithm="HS256")
        if isinstance(token, bytes):  # PyJWT 1.x
            token = token.decode()
        return {"Authorization": f"Bearer {token}"}

    # --- 계좌 ---------------------------------------------------------------

    async def get_cash(self) -> Decimal:
        r = await self._client.get("/v1/accounts", headers=self._jwt_header())
        r.raise_for_status()
        for acc in r.json():
            if acc["currency"] == "KRW":
                return Decimal(acc["balance"])
        return Decimal(0)

    async def get_positions(self) -> list[Position]:
        r = await self._client.get("/v1/accounts", headers=self._jwt_header())
        r.raise_for_status()
        out: list[Position] = []
        for acc in r.json():
            if acc["currency"] == "KRW":
                continue
            qty = Decimal(acc["balance"])
            if qty <= 0:
                continue
            out.append(
                Position(
                    symbol=f"KRW-{acc['currency']}",
                    qty=qty,
                    avg_entry_price=Decimal(acc.get("avg_buy_price", "0")),
                    exchange=self.name,
                    asset_class=AssetClass.CRYPTO,
                )
            )
        return out

    # --- 시세 ---------------------------------------------------------------

    async def get_quote(self, symbol: str) -> Quote:
        """`symbol` = 'KRW-BTC' 형식."""
        r = await self._client.get("/v1/ticker", params={"markets": symbol})
        r.raise_for_status()
        d = r.json()[0]
        last = Decimal(str(d["trade_price"]))
        # Upbit ticker는 호가가 아니라 체결가만 — orderbook 별도 호출 권장
        # 봇은 mid 사용. spread 정확성 필요 시 /v1/orderbook 로 보강.
        return Quote(
            symbol=symbol,
            bid=last,
            ask=last,
            last=last,
            timestamp=datetime.utcnow(),
            exchange=self.name,
            asset_class=AssetClass.CRYPTO,
            raw=d,
        )

    async def get_historical_closes(
        self, symbol: str, *, limit: int = 200, interval: str = "1d"
    ) -> list[Decimal]:
        # interval: minutes/{1,3,5,15,30,60,240}, days, weeks, months
        unit_path = {
            "1m": "minutes/1",
            "5m": "minutes/5",
            "15m": "minutes/15",
            "1h": "minutes/60",
            "1d": "days",
        }.get(interval, "days")
        r = await self._client.get(
            f"/v1/candles/{unit_path}",
            params={"market": symbol, "count": min(limit, 200)},
        )
        r.raise_for_status()
        # Upbit 응답은 최신 → 오래된 순. 뒤집어서 통일.
        return [Decimal(str(c["trade_price"])) for c in reversed(r.json())]

    async def stream_quotes(self, symbols: list[str]) -> AsyncIterator[Quote]:
        # 임시 polling. Day 2-3 에 wss://api.upbit.com/websocket/v1 로 교체.
        while True:
            for sym in symbols:
                try:
                    yield await self.get_quote(sym)
                except Exception:
                    continue
            await asyncio.sleep(1.5)

    # --- 주문 ---------------------------------------------------------------

    async def submit_order(self, order: Order) -> OrderResult:
        if order.type != "market":
            # 향후 limit 지원
            params = {
                "market": order.symbol,
                "side": "bid" if order.side == "buy" else "ask",
                "volume": str(order.qty),
                "price": str(order.price),
                "ord_type": "limit",
            }
        else:
            # Upbit market 주문: buy 는 price(원화 금액), sell 은 volume(코인 수량)
            if order.side == "buy":
                # buy 시 qty 가 KRW 금액으로 해석되도록 봇이 변환 후 호출
                params = {
                    "market": order.symbol,
                    "side": "bid",
                    "price": str(order.qty * (order.price or Decimal(1))),
                    "ord_type": "price",
                }
            else:
                params = {
                    "market": order.symbol,
                    "side": "ask",
                    "volume": str(order.qty),
                    "ord_type": "market",
                }

        r = await self._client.post(
            "/v1/orders",
            params=params,
            headers=self._jwt_header(params),
        )
        r.raise_for_status()
        return self._to_result(r.json())

    async def cancel_order(self, exchange_order_id: str) -> None:
        params = {"uuid": exchange_order_id}
        r = await self._client.delete(
            "/v1/order", params=params, headers=self._jwt_header(params)
        )
        r.raise_for_status()

    async def get_order(self, exchange_order_id: str) -> OrderResult:
        params = {"uuid": exchange_order_id}
        r = await self._client.get(
            "/v1/order", params=params, headers=self._jwt_header(params)
        )
        r.raise_for_status()
        return self._to_result(r.json())

    def _to_result(self, data: dict) -> OrderResult:
        side = "buy" if data["side"] == "bid" else "sell"
        return OrderResult(
            client_order_id=data.get("identifier"),
            exchange_order_id=data["uuid"],
            symbol=data["market"],
            side=side,  # type: ignore[arg-type]
            type="limit" if data.get("ord_type") == "limit" else "market",
            status=_STATUS_MAP.get(data["state"], "submitted"),
            qty=Decimal(data.get("volume", data.get("price", "0"))),
            filled_qty=Decimal(data.get("executed_volume", "0")),
            filled_avg_price=(
                Decimal(data["paid_fee"]) / Decimal(data["executed_volume"])
                if Decimal(data.get("executed_volume", "0")) > 0
                else None
            ),
            submitted_at=(
                datetime.fromisoformat(data["created_at"])
                if data.get("created_at")
                else None
            ),
            raw=data,
        )

    async def close(self) -> None:
        await self._client.aclose()
