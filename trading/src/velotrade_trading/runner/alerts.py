"""알림 매니저 — Discord / Slack / Stdout.

모든 채널은 best-effort. 실패해도 봇은 멈추지 않음.

Discord: Rich embed (level→color), 2000자 안전 truncate, 코드블록 본문.
Slack:   mrkdwn, attachment color, 본문 1800자 안전.
Stdout:  단순 prefix, 항상 동작 (fallback).
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger("alerts")


# Discord embed color (decimal RGB)
_DISCORD_COLORS = {
    "info":  0x3B82F6,   # blue
    "warn":  0xF59E0B,   # amber
    "error": 0xEF4444,   # red
    "trade": 0x10B981,   # emerald
}
_SLACK_COLORS = {
    "info":  "#3B82F6",
    "warn":  "#F59E0B",
    "error": "#EF4444",
    "trade": "#10B981",
}
_EMOJI = {"info": "ℹ️", "warn": "⚠️", "error": "🛑", "trade": "💱"}

_DISCORD_BODY_LIMIT = 1900   # embed description 4096 가능하지만 안전치
_SLACK_BODY_LIMIT = 1800


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


@dataclass
class AlertMessage:
    title: str
    body: str
    level: str = "info"   # info | warn | error | trade


class AlertChannel(ABC):
    @abstractmethod
    async def send(self, msg: AlertMessage) -> None: ...

    @property
    def name(self) -> str:
        return self.__class__.__name__.replace("Channel", "").lower()


def _mask_url(url: str) -> str:
    """URL 끝 12자만 표시 (로그에 webhook 노출 방지)."""
    if not url:
        return ""
    return "…" + url[-12:] if len(url) > 12 else url


class DiscordWebhook(AlertChannel):
    """Discord webhook — rich embed, 429 자동 재시도 + 마스킹된 에러 로그."""

    def __init__(self, webhook_url: str) -> None:
        self.url = webhook_url

    async def send(self, msg: AlertMessage) -> None:
        emoji = _EMOJI.get(msg.level, "•")
        color = _DISCORD_COLORS.get(msg.level, 0x6B7280)
        body = _truncate(msg.body or "", _DISCORD_BODY_LIMIT)
        embed = {
            "title": f"{emoji} {msg.title[:240]}",
            "color": color,
            "footer": {"text": f"VeloTrade · {msg.level}"},
        }
        if body:
            embed["description"] = f"```\n{body}\n```"
        payload = {"embeds": [embed]}

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=10.0) as c:
                    r = await c.post(self.url, json=payload)
                if r.status_code == 429:
                    # rate limit — Retry-After 헤더 만큼 대기 (최대 5초)
                    try:
                        retry_after = float(r.headers.get("Retry-After", "1"))
                    except ValueError:
                        retry_after = 1.0
                    await asyncio.sleep(min(retry_after, 5.0))
                    continue
                r.raise_for_status()
                return
            except Exception as e:
                # URL 노출 방지 — error 메시지에서 URL 제거하고 status 만
                err = type(e).__name__
                status = getattr(getattr(e, "response", None), "status_code", None)
                log.warning(
                    "discord.send.failed",
                    error=err,
                    status=status,
                    url=_mask_url(self.url),
                    attempt=attempt + 1,
                )
                if attempt < 2:
                    await asyncio.sleep(0.5)
                    continue
                return


class SlackWebhook(AlertChannel):
    """Slack incoming webhook — attachment with color, 429 재시도 + 마스킹."""

    def __init__(self, webhook_url: str) -> None:
        self.url = webhook_url

    async def send(self, msg: AlertMessage) -> None:
        body = _truncate(msg.body or "", _SLACK_BODY_LIMIT)
        payload = {
            "attachments": [
                {
                    "color": _SLACK_COLORS.get(msg.level, "#6B7280"),
                    "title": f"{_EMOJI.get(msg.level, '•')} {msg.title[:240]}",
                    "text": f"```{body}```" if body else "",
                    "footer": f"VeloTrade · {msg.level}",
                    "mrkdwn_in": ["text"],
                }
            ],
        }
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=10.0) as c:
                    r = await c.post(self.url, json=payload)
                if r.status_code == 429:
                    try:
                        retry_after = float(r.headers.get("Retry-After", "1"))
                    except ValueError:
                        retry_after = 1.0
                    await asyncio.sleep(min(retry_after, 5.0))
                    continue
                r.raise_for_status()
                return
            except Exception as e:
                err = type(e).__name__
                status = getattr(getattr(e, "response", None), "status_code", None)
                log.warning(
                    "slack.send.failed",
                    error=err,
                    status=status,
                    url=_mask_url(self.url),
                    attempt=attempt + 1,
                )
                if attempt < 2:
                    await asyncio.sleep(0.5)
                    continue
                return


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

    # 편의 메서드
    async def info(self, title: str, body: str = "") -> None:
        await self.send(AlertMessage(title=title, body=body, level="info"))

    async def warn(self, title: str, body: str = "") -> None:
        await self.send(AlertMessage(title=title, body=body, level="warn"))

    async def error(self, title: str, body: str = "") -> None:
        await self.send(AlertMessage(title=title, body=body, level="error"))

    async def trade(self, title: str, body: str = "") -> None:
        await self.send(AlertMessage(title=title, body=body, level="trade"))

    # 메타
    def channel_names(self) -> list[str]:
        return [c.name for c in self.channels]
