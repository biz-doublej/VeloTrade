"""Supabase vt 스키마에 초기 시드 데이터 입력.

대상:
- vt.exchange_accounts: Alpaca paper, Binance testnet, Upbit paper
- vt.watchlist_items: 미국 주식 9개 + 코인 4개 + 국내 코인 4개

여러 번 실행해도 안전 (UPSERT 기반).

실행: python scripts/seed_db.py
"""

import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# 프로젝트 루트에서 .env 로드
_PROJ = Path(__file__).resolve().parents[1]
load_dotenv(_PROJ / ".env")

# src 를 path 에 추가 (editable install 안 했을 경우 대비)
sys.path.insert(0, str(_PROJ / "src"))


# --- 시드 데이터 정의 -------------------------------------------------------

EXCHANGE_ACCOUNTS = [
    {
        "exchange": "alpaca",
        "account_type": "paper",
        "label": "default",
        "base_currency": "USD",
        "starting_capital": Decimal("100000"),
    },
    {
        "exchange": "binance",
        "account_type": "paper",
        "label": "testnet-default",
        "base_currency": "USDT",
        "starting_capital": Decimal("10000"),
    },
    {
        "exchange": "upbit",
        "account_type": "paper",
        "label": "simulated-default",
        "base_currency": "KRW",
        "starting_capital": Decimal("10000000"),
    },
]

WATCHLIST = [
    # 미국 주식 (Alpaca) — Mag7 + 인덱스 ETF
    {"exchange": "alpaca", "asset_class": "us_stock", "symbol": "AAPL"},
    {"exchange": "alpaca", "asset_class": "us_stock", "symbol": "MSFT"},
    {"exchange": "alpaca", "asset_class": "us_stock", "symbol": "NVDA"},
    {"exchange": "alpaca", "asset_class": "us_stock", "symbol": "GOOGL"},
    {"exchange": "alpaca", "asset_class": "us_stock", "symbol": "AMZN"},
    {"exchange": "alpaca", "asset_class": "us_stock", "symbol": "META"},
    {"exchange": "alpaca", "asset_class": "us_stock", "symbol": "TSLA"},
    {"exchange": "alpaca", "asset_class": "us_stock", "symbol": "SPY"},
    {"exchange": "alpaca", "asset_class": "us_stock", "symbol": "QQQ"},
    # 코인 글로벌 (Binance, USDT 페어)
    {"exchange": "binance", "asset_class": "crypto", "symbol": "BTCUSDT"},
    {"exchange": "binance", "asset_class": "crypto", "symbol": "ETHUSDT"},
    {"exchange": "binance", "asset_class": "crypto", "symbol": "SOLUSDT"},
    {"exchange": "binance", "asset_class": "crypto", "symbol": "BNBUSDT"},
    # 코인 국내 (Upbit, KRW 마켓)
    {"exchange": "upbit", "asset_class": "crypto", "symbol": "KRW-BTC"},
    {"exchange": "upbit", "asset_class": "crypto", "symbol": "KRW-ETH"},
    {"exchange": "upbit", "asset_class": "crypto", "symbol": "KRW-SOL"},
    {"exchange": "upbit", "asset_class": "crypto", "symbol": "KRW-XRP"},
]


# --- 실행 -------------------------------------------------------------------


async def main():
    from velotrade_trading.db.client import (
        DBRecorder,
        get_or_create_account,
    )

    db = DBRecorder()
    try:
        # 1. 계좌
        print(f"[1] exchange_accounts seeding ({len(EXCHANGE_ACCOUNTS)} rows)")
        account_ids: dict[tuple[str, str], str] = {}
        for acc in EXCHANGE_ACCOUNTS:
            account_id = await get_or_create_account(
                db,
                exchange=acc["exchange"],
                account_type=acc["account_type"],
                label=acc["label"],
                base_currency=acc["base_currency"],
                starting_capital=acc["starting_capital"],
            )
            if account_id:
                account_ids[(acc["exchange"], acc["account_type"])] = account_id
                print(f"    {acc['exchange']:8s} {acc['account_type']:5s}  {acc['label']:25s}  id={account_id[:8]}...")
            else:
                print(f"    {acc['exchange']:8s} FAILED")

        # 2. 워치리스트 (UPSERT)
        print(f"\n[2] watchlist_items seeding ({len(WATCHLIST)} rows)")
        success = 0
        for item in WATCHLIST:
            row = await db._upsert(
                "watchlist_items",
                {**item, "enabled": True},
                on_conflict="exchange,symbol",
            )
            if row:
                success += 1

        print(f"    upserted: {success}/{len(WATCHLIST)}")

        # 3. 결과 확인
        from velotrade_trading.db.client import get_watchlist
        for ex in ["alpaca", "binance", "upbit"]:
            symbols = await get_watchlist(db, exchange=ex)
            print(f"    {ex:8s} watchlist: {len(symbols)} symbols → {symbols}")

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
