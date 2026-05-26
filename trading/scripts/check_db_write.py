"""DBRecorder 통합 검증 — alert 기록 + position upsert + select 확인."""

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
    from velotrade_trading.core.types import AssetClass, Position
    from velotrade_trading.db.client import DBRecorder, get_or_create_account

    db = DBRecorder()
    try:
        # 1. 계좌 ID 조회 (이미 시드됨)
        account_id = await get_or_create_account(
            db,
            exchange="alpaca",
            account_type="paper",
            label="default",
            base_currency="USD",
        )
        print(f"[1] alpaca paper account_id = {account_id}")

        # 2. alert 기록
        alert_id = await db.record_alert(
            level="info",
            alert_type="bot_lifecycle",
            title="DBRecorder integration test",
            body="connectivity & write OK",
            meta={"test": True},
        )
        print(f"[2] alert recorded: {alert_id}")

        # 3. position upsert (AAPL paper 가상 포지션)
        pos = Position(
            symbol="AAPL",
            qty=Decimal("0"),       # 실제 없음 — UPSERT 후 즉시 삭제하지 않으면 0 으로 남음
            avg_entry_price=Decimal("200.00"),
            current_price=Decimal("210.00"),
            exchange="alpaca",
            asset_class=AssetClass.US_STOCK,
        )
        pos_id = await db.upsert_position(account_id=account_id, position=pos)
        print(f"[3] position upserted: {pos_id}")

        # 4. SELECT 확인
        import httpx
        async with httpx.AsyncClient(
            base_url=f"{db.url}/rest/v1",
            headers={
                "apikey": db.key,
                "Authorization": f"Bearer {db.key}",
                "Accept-Profile": "vt",
            },
            timeout=10.0,
        ) as c:
            r = await c.get("/alerts", params={"order": "created_at.desc", "limit": "3"})
            alerts = r.json()
            print(f"\n[4] recent alerts ({len(alerts)}):")
            for a in alerts:
                print(f"    {a['created_at'][:19]}  [{a['level']:5s}] {a['alert_type']:15s} {a['title']}")

            r = await c.get("/positions", params={"select": "symbol,qty,avg_entry_price,current_price"})
            positions = r.json()
            print(f"\n[5] positions ({len(positions)}):")
            for p in positions:
                print(f"    {p['symbol']:8s} qty={p['qty']} entry={p['avg_entry_price']} current={p.get('current_price')}")

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
