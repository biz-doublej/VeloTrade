"""Upbit WebSocket + paper 시뮬레이터 end-to-end 검증.

  1. UpbitExchange(public_only=True) — 시세만
  2. PaperExchange 로 감쌈
  3. WebSocket 시세 5초 수신
  4. paper 매수 1건 → 메모리 시뮬레이션 fill
  5. 포지션 확인
  6. DB 기록 (alerts 만 — paper 포지션은 메모리)
"""

import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_PROJ = Path(__file__).resolve().parents[1]
load_dotenv(_PROJ / ".env")
sys.path.insert(0, str(_PROJ / "src"))


async def main():
    from velotrade_trading.adapters.paper import PaperExchange
    from velotrade_trading.adapters.upbit import UpbitExchange
    from velotrade_trading.core.types import Order
    from velotrade_trading.db.client import DBRecorder, get_or_create_account

    upbit_feed = UpbitExchange(public_only=True)
    adapter = PaperExchange(
        base_name="upbit",
        market_feed=upbit_feed,
        starting_cash=Decimal("10000000"),  # 천만원
        quote_currency="KRW",
    )
    db = DBRecorder()

    account_id = await get_or_create_account(
        db,
        exchange="upbit",
        account_type="paper",
        label="simulated-default",
        base_currency="KRW",
    )
    print(f"account_id: {account_id}")
    print(f"adapter: {adapter.name} (is_paper={adapter.is_paper})")

    try:
        # 1. REST 시세 1건
        quote = await adapter.get_quote("KRW-BTC")
        cash = await adapter.get_cash()
        print(f"\n[1] KRW-BTC REST quote")
        print(f"    last={quote.last}")
        print(f"    paper KRW cash={cash:,}")

        # 2. WebSocket 5초 수신
        print(f"\n[2] WebSocket subscribe KRW-BTC, KRW-ETH, KRW-SOL (5s)")
        count = 0
        last_quotes = {}
        try:
            async def consume():
                nonlocal count
                async for q in adapter.stream_quotes(["KRW-BTC", "KRW-ETH", "KRW-SOL"]):
                    count += 1
                    last_quotes[q.symbol] = q.last
                    if count <= 6:
                        print(f"    #{count} {q.symbol:8s} last={q.last:,}")
            await asyncio.wait_for(consume(), timeout=5.0)
        except asyncio.TimeoutError:
            pass

        print(f"\n    total messages: {count}")
        print(f"    seen symbols  : {sorted(last_quotes.keys())}")

        # 3. paper 매수
        order = Order(
            symbol="KRW-BTC",
            side="buy",
            type="market",
            qty=Decimal("0.0001"),  # 0.0001 BTC ≈ 1만원 수준
            client_order_id=f"vt-check-{int(asyncio.get_event_loop().time())}",
        )
        print(f"\n[3] paper BUY 0.0001 KRW-BTC")
        result = await adapter.submit_order(order)
        print(f"    exchange_order_id : {result.exchange_order_id}")
        print(f"    status            : {result.status}")
        print(f"    filled_qty        : {result.filled_qty}")
        print(f"    filled_avg_price  : {result.filled_avg_price:,}")

        await db.record_order(result, account_id=account_id)

        # 4. paper 포지션 + 잔고
        positions = await adapter.get_positions()
        new_cash = await adapter.get_cash()
        print(f"\n[4] paper state after order:")
        print(f"    KRW cash      : {new_cash:,}")
        for p in positions:
            print(f"    {p.symbol:8s} qty={p.qty} avg_entry={p.avg_entry_price:,}")
            await db.upsert_position(account_id=account_id, position=p)

        print("\n[OK] Upbit WS + paper simulator + DB sync succeeded")

    finally:
        await adapter.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
