"""Alpaca paper 실주문 end-to-end 검증.

  1. AAPL 시세 조회
  2. 매수 1주 주문 (market, fractional 가능)
  3. 주문 결과 DB 기록 (vt.orders)
  4. 5초 후 주문 상태 재조회
  5. 포지션 동기화 + DB upsert

⚠️ 이건 paper 계좌. 실거래 절대 안 함. 봇 require_paper=True 가드는 우회.
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
    from velotrade_trading.adapters.alpaca import AlpacaExchange
    from velotrade_trading.core.types import Order
    from velotrade_trading.db.client import DBRecorder, get_or_create_account

    adapter = AlpacaExchange(is_paper=True)
    db = DBRecorder()

    account_id = await get_or_create_account(
        db,
        exchange="alpaca",
        account_type="paper",
        label="default",
        base_currency="USD",
    )
    print(f"account_id: {account_id}")

    try:
        # 1. 시세
        quote = await adapter.get_quote("AAPL")
        print(f"\n[1] AAPL quote")
        print(f"    bid={quote.bid} ask={quote.ask} mid={quote.mid}")

        cash = await adapter.get_cash()
        print(f"    cash={cash}")

        # 2. 주문 — fractional 1 share (~$300)
        order = Order(
            symbol="AAPL",
            side="buy",
            type="market",
            qty=Decimal("1"),
            client_order_id=f"vt-check-{int(asyncio.get_event_loop().time())}",
        )
        print(f"\n[2] submitting order: BUY 1 AAPL (market)")
        result = await adapter.submit_order(order)
        print(f"    exchange_order_id : {result.exchange_order_id}")
        print(f"    status            : {result.status}")
        print(f"    filled_qty        : {result.filled_qty}")
        print(f"    filled_avg_price  : {result.filled_avg_price}")

        # 3. DB 기록
        order_db_id = await db.record_order(result, account_id=account_id)
        print(f"\n[3] DB recorded: order_id={order_db_id}")

        # 4. 5초 대기 후 상태 재조회
        print("\n[4] waiting 5s for fill...")
        await asyncio.sleep(5)
        result2 = await adapter.get_order(result.exchange_order_id)
        print(f"    status after 5s   : {result2.status}")
        print(f"    filled_qty        : {result2.filled_qty}")
        print(f"    filled_avg_price  : {result2.filled_avg_price}")

        # 5. 포지션 동기화
        positions = await adapter.get_positions()
        print(f"\n[5] positions on Alpaca ({len(positions)}):")
        for p in positions:
            print(f"    {p.symbol:8s} qty={p.qty} avg_entry={p.avg_entry_price} current={p.current_price}")
            await db.upsert_position(account_id=account_id, position=p)

        print("\n[OK] end-to-end paper order + DB sync succeeded")

    finally:
        await adapter.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
