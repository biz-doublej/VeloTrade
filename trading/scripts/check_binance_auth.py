"""Binance testnet 인증 진단 — ping, time, account 단계별."""

import asyncio
import hashlib
import hmac
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


async def main():
    key = os.getenv("BINANCE_TESTNET_API_KEY", "")
    secret = os.getenv("BINANCE_TESTNET_SECRET_KEY", "")
    print(f"key length: {len(key)}, secret length: {len(secret)}")
    base = "https://testnet.binance.vision"

    async with httpx.AsyncClient(base_url=base, headers={"X-MBX-APIKEY": key}, timeout=10.0) as c:
        # 1. ping (public)
        r = await c.get("/api/v3/ping")
        print(f"\n[1] ping       status={r.status_code} body={r.text[:120]}")

        # 2. server time
        r = await c.get("/api/v3/time")
        print(f"[2] time       status={r.status_code} body={r.text[:120]}")
        server_time = r.json().get("serverTime") if r.status_code == 200 else None
        local_time = int(time.time() * 1000)
        print(f"    local={local_time}, server={server_time}, diff={local_time - (server_time or 0)} ms")

        # 3. account with explicit timestamp + recvWindow
        params = {
            "timestamp": str(server_time or local_time),
            "recvWindow": "5000",
        }
        query = urlencode(params)
        sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig

        r = await c.get("/api/v3/account", params=params)
        print(f"\n[3] account    status={r.status_code}")
        print(f"    body: {r.text[:400]}")


if __name__ == "__main__":
    asyncio.run(main())
