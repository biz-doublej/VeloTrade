"""알림 매니저 — Discord / Slack / Email.

모든 채널은 best-effort. 실패해도 봇은 계속 돈다.
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger("alerts")


@dataclass
class AlertMessage:
    title: str
    body: str
    level: str = "info"  # info | warn | error | trade


class AlertChannel(ABC):
    @abstractmethod
    async def send(self, msg: AlertMessage) -> None: ...


class DiscordWebhook(AlertChannel):
    def __init__(self, webhook_url: str) -> None:
        self.url = webhook_url

    async def send(self, msg: AlertMessage) -> None:
        emoji = {"info": "ℹ️", "warn": "⚠️", "error": "🛑", "trade": "💱"}.get(msg.level, "•")
        payload = {"content": f"{emoji} **{msg.title}**\n{msg.body[:1800]}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(self.url, json=payload)
                r.raise_for_status()
        except Exception as e:
            log.warning("discord.send.failed", error=str(e))


class SlackWebhook(AlertChannel):
    def __init__(self, webhook_url: str) -> None:
        self.url = webhook_url

    async def send(self, msg: AlertMessage) -> None:
        payload = {"text": f"*{msg.title}* [{msg.level}]\n{msg.body[:1800]}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(self.url, json=payload)
                r.raise_for_status()
        except Exception as e:
            log.warning("slack.send.failed", error=str(e))


class StdoutChannel(AlertChannel):
    """기본 fallback. 항상 출력."""

    async def send(self, msg: AlertMessage) -> None:
        print(f"[{msg.level.upper()}] {msg.title}: {msg.body}")


class AlertManager:
    def __init__(self, channels: list[AlertChannel] | None = None) -> None:
        self.channels: list[AlertChannel] = channels or []
        if not self.channels:
            self.channels.append(StdoutChannel())

    @classmethod
    def from_env(cls) -> "AlertManager":
        chans: list[AlertChannel] = []
        if url := os.getenv("DISCORD_WEBHOOK_URL"):
            chans.append(DiscordWebhook(url))
        if url := os.getenv("SLACK_WEBHOOK_URL"):
            chans.append(SlackWebhook(url))
        chans.append(StdoutChannel())
        return cls(chans)

    async def send(self, msg: AlertMessage) -> None:
        await asyncio.gather(
            *(c.send(msg) for c in self.channels),
            return_exceptions=True,
        )

    async def info(self, title: str, body: str = "") -> None:
        await self.send(AlertMessage(title=title, body=body, level="info"))

    async def warn(self, title: str, body: str = "") -> None:
        await self.send(AlertMessage(title=title, body=body, level="warn"))

    async def error(self, title: str, body: str = "") -> None:
        await self.send(AlertMessage(title=title, body=body, level="error"))

    async def trade(self, title: str, body: str = "") -> None:
        await self.send(AlertMessage(title=title, body=body, level="trade"))
