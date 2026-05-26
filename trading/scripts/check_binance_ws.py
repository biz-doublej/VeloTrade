"""Binance testnet WebSocket 시세 스트림 검증 (10초)."""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_PROJ = Path(__file__).resolve().parents[1]
load_dotenv(_PROJ / ".env")
sys.path.insert(0, str(_PROJ / "src"))


async def main():
    from velotrade_trading.adapters.binance import BinanceExchange

    adapter = BinanceExchange(use_testnet=True)
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    print(f"Binance testnet WebSocket — subscribe {symbols} (10s)")

    count = 0
    seen = {}
    try:
        async def consume():
            nonlocal count
            async for quote in adapter.stream_quotes(symbols):
                count += 1
                seen[quote.symbol] = quote
                if count <= 6:
                    print(f"  #{count} {quote.symbol:9s} bid={quote.bid} ask={quote.ask}")
        await asyncio.wait_for(consume(), timeout=10.0)
    except asyncio.TimeoutError:
        pass
    finally:
        await adapter.close()

    print(f"\nTotal messages: {count}")
    print(f"Unique symbols seen: {sorted(seen.keys())}")
    for sym, q in seen.items():
        print(f"  last quote — {sym}: bid={q.bid} ask={q.ask}")


if __name__ == "__main__":
    asyncio.run(main())
