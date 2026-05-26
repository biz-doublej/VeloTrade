"""알림 채널 end-to-end 검증.

활성 채널 (DISCORD_WEBHOOK_URL / SLACK_WEBHOOK_URL / stdout) 각각에
4 종류 (info/warn/error/trade) 테스트 메시지 발송.

사용:
  1. Discord 채널 → Edit Channel → Integrations → Webhooks → New Webhook
     → "Copy Webhook URL" → trading/.env 의 DISCORD_WEBHOOK_URL 에 붙여넣기
  2. Slack: Slack 앱 추가 또는 https://api.slack.com/messaging/webhooks
  3. python scripts/check_alerts.py
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_PROJ = Path(__file__).resolve().parents[1]
load_dotenv(_PROJ / ".env")
sys.path.insert(0, str(_PROJ / "src"))


async def main():
    from velotrade_trading.runner.alerts import AlertManager

    mgr = AlertManager.from_env()
    print(f"active channels: {mgr.channel_names()}")
    ts = datetime.utcnow().strftime("%H:%M:%S UTC")

    if "discordwebhook" not in mgr.channel_names():
        print("  [info] Discord 비활성 — DISCORD_WEBHOOK_URL 설정 시 자동 활성")
    if "slackwebhook" not in mgr.channel_names():
        print("  [info] Slack 비활성 — SLACK_WEBHOOK_URL 설정 시 자동 활성")

    print(f"\nsending 4 test alerts ({ts})...")
    await mgr.info(
        "alerts check — info",
        f"VeloTrade 알림 시스템 동작 검증 ({ts})\n채널: {mgr.channel_names()}",
    )
    await mgr.warn(
        "alerts check — warn",
        "예시 경고: signal rejected by RiskManager — short not allowed: AAPL",
    )
    await mgr.error(
        "alerts check — error",
        "예시 에러: order submission failed: connection timeout to broker",
    )
    await mgr.trade(
        "alerts check — trade",
        "예시 거래: BUY 0.001 BTCUSDT @ ~76,941.29 USDT\n"
        "strategy=rsi | status=filled | exchange_order_id=7440595",
    )

    print("\n[OK] 4 messages dispatched (best-effort).")
    print("    Discord/Slack 활성 시 채널 확인. stdout 은 위에 출력됨.")


if __name__ == "__main__":
    asyncio.run(main())
