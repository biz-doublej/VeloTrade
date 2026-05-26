"""Supabase PostgREST 연결 및 vt 스키마 노출 여부 확인."""

import asyncio
import os
import sys

from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()


async def main():
    import httpx

    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("[ERR] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
        return

    headers_vt = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Profile": "vt",
        "Accept-Profile": "vt",
    }
    headers_public = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }

    async with httpx.AsyncClient(base_url=f"{url}/rest/v1", timeout=10.0) as c:
        # A. public 스키마 (기본 노출) 확인
        r = await c.get("/", headers=headers_public)
        print(f"[A: public root]   status={r.status_code}")

        # B. vt 스키마로 root 호출 (스키마 노출 여부)
        r = await c.get("/", headers=headers_vt)
        print(f"[B: vt root]       status={r.status_code}")
        if r.status_code != 200:
            print(f"   body: {r.text[:300]}")

        # C. vt.exchange_accounts 직접 호출
        r = await c.get("/exchange_accounts?limit=1", headers=headers_vt)
        print(f"[C: vt.exchange_accounts] status={r.status_code}")
        if r.status_code == 200:
            print(f"   rows: {len(r.json())}")
        else:
            print(f"   body: {r.text[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
