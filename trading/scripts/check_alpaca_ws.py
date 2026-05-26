"""Alpaca WebSocket 시세 스트림 짧은 검증 (15초)."""

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
    from velotrade_trading.adapters.alpaca import AlpacaExchange

    adapter = AlpacaExchange(is_paper=True)
    symbols = ["AAPL", "MSFT", "NVDA"]
    print(f"WebSocket connect + subscribe {symbols} (15s timeout)")

    count = 0
    seen_symbols = set()
    try:
        async def consume():
            nonlocal count, seen_symbols
            async for quote in adapter.stream_quotes(symbols):
                count += 1
                seen_symbols.add(quote.symbol)
                if count <= 5:
                    print(f"  {quote.symbol:6s} bid={quote.bid} ask={quote.ask} last={quote.last}")
                if count == 6:
                    print("  ... (suppressing further; counting only)")

        await asyncio.wait_for(consume(), timeout=15.0)
    except asyncio.TimeoutError:
        pass
    finally:
        await adapter.close()

    print(f"\nTotal messages: {count}")
    print(f"Symbols seen  : {sorted(seen_symbols)}")
    if count == 0:
        print("  (장 마감 중에는 0 메시지가 정상 — connection·auth·subscribe 만 검증)")


if __name__ == "__main__":
    asyncio.run(main())
