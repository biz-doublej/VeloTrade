"""Binance testnet 실주문 end-to-end 검증.

  1. 계좌 잔고 확인 (USDT)
  2. BTCUSDT 시세 조회
  3. 0.001 BTC 매수 (시장가) — 약 $76 만큼
  4. 결과 + DB 기록
  5. 5초 후 주문 상태 재조회
  6. 포지션 (Binance balance) 동기화
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
    from velotrade_trading.adapters.binance import BinanceExchange
    from velotrade_trading.core.types import Order
    from velotrade_trading.db.client import DBRecorder, get_or_create_account

    adapter = BinanceExchange(use_testnet=True)
    db = DBRecorder()

    account_id = await get_or_create_account(
        db,
        exchange="binance",
        account_type="paper",
        label="testnet-default",
        base_currency="USDT",
    )
    print(f"account_id: {account_id}")

    try:
        # 1. 시세 + 잔고
        quote = await adapter.get_quote("BTCUSDT")
        cash = await adapter.get_cash()
        print(f"\n[1] BTCUSDT quote")
        print(f"    bid={quote.bid} ask={quote.ask}")
        print(f"    USDT cash={cash}")
        if cash < Decimal("100"):
            print("    [WARN] USDT 잔고가 100 USDT 미만 — testnet faucet 필요할 수 있음")
            print("           https://testnet.binance.vision/ 에서 'Test Funds' 받기")

        # 2. 매수 — 매우 작은 수량 (0.001 BTC ≈ $76)
        qty = Decimal("0.001")
        order = Order(
            symbol="BTCUSDT",
            side="buy",
            type="market",
            qty=qty,
            client_order_id=f"vt-check-{int(asyncio.get_event_loop().time())}",
        )
        print(f"\n[2] submitting: BUY {qty} BTCUSDT (market)")
        result = await adapter.submit_order(order)
        print(f"    exchange_order_id : {result.exchange_order_id}")
        print(f"    status            : {result.status}")
        print(f"    filled_qty        : {result.filled_qty}")
        print(f"    filled_avg_price  : {result.filled_avg_price}")

        # 3. DB 기록
        order_db_id = await db.record_order(result, account_id=account_id)
        print(f"\n[3] DB orders.order_id = {order_db_id}")

        # 4. 5초 후 재조회
        print("\n[4] waiting 3s + fetching order status...")
        await asyncio.sleep(3)
        try:
            result2 = await adapter.get_order_with_symbol("BTCUSDT", result.exchange_order_id)
            print(f"    status            : {result2.status}")
            print(f"    filled_qty        : {result2.filled_qty}")
        except Exception as e:
            print(f"    get_order err: {e}")

        # 5. 포지션 (모든 자산 잔고)
        positions = await adapter.get_positions()
        print(f"\n[5] Binance balances ({len(positions)}):")
        for p in positions:
            print(f"    {p.symbol:12s} qty={p.qty}")
            await db.upsert_position(account_id=account_id, position=p)

        print("\n[OK] Binance testnet order + DB sync succeeded")

    finally:
        await adapter.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
