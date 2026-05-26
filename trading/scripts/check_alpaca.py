"""Alpaca paper 연결 + historical bars 파라미터 조합 테스트."""

import asyncio
import os
import sys
import json
from datetime import datetime, timedelta

from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()


async def try_bars(client, label, params):
    r = await client.get("/v2/stocks/AAPL/bars", params=params)
    data = r.json() if r.status_code == 200 else None
    bars = (data or {}).get("bars") if data else None
    if isinstance(bars, dict):
        bars = bars.get("AAPL", [])
    bars = bars or []
    print(f"\n[{label}]")
    print(f"  params      : {params}")
    print(f"  status_code : {r.status_code}")
    print(f"  bars count  : {len(bars)}")
    if bars:
        print(f"  first close : {bars[0].get('c')}  ({bars[0].get('t')[:10]})")
        print(f"  last close  : {bars[-1].get('c')}  ({bars[-1].get('t')[:10]})")
    else:
        print(f"  raw         : {json.dumps(data, indent=2)[:300]}")


async def main():
    import httpx

    key = os.getenv("ALPACA_PAPER_API_KEY")
    secret = os.getenv("ALPACA_PAPER_SECRET_KEY")
    if not key or not secret:
        print("[ERR] keys missing")
        return

    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    async with httpx.AsyncClient(
        base_url="https://data.alpaca.markets", headers=headers, timeout=15.0
    ) as c:
        end_yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        start_1y = (datetime.utcnow() - timedelta(days=400)).strftime("%Y-%m-%d")

        # A. start + end + iex
        await try_bars(c, "A: start + end + iex", {
            "timeframe": "1Day",
            "start": start_1y,
            "end": end_yesterday,
            "feed": "iex",
            "limit": 200,
            "adjustment": "raw",
        })

        # B. start만 + iex
        await try_bars(c, "B: start only + iex", {
            "timeframe": "1Day",
            "start": start_1y,
            "feed": "iex",
            "limit": 200,
        })

        # C. end 미지정, limit만 + iex
        await try_bars(c, "C: limit only + iex", {
            "timeframe": "1Day",
            "feed": "iex",
            "limit": 200,
        })

        # D. feed 명시 없이 (default 처리)
        await try_bars(c, "D: no feed param", {
            "timeframe": "1Day",
            "start": start_1y,
            "end": end_yesterday,
            "limit": 200,
        })


if __name__ == "__main__":
    asyncio.run(main())
