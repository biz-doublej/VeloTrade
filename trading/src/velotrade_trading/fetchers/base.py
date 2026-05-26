"""Fetcher 인터페이스 + MarketEvent 도메인 모델.

이벤트 흐름:
  Fetcher.fetch() → list[MarketEvent]
       ↓
  EventDispatcher (dedupe by content_hash)
       ↓
  bot.handle_event(event.as_strategy_input())
       ↓
  LLMSignalStrategy.on_event → Signal
       ↓
  RiskManager → Order → adapter.submit_order
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class MarketEvent:
    """외부 이벤트 (공시·뉴스·매크로).

    LLMSignalStrategy 가 받는 event dict 와 호환되도록 as_strategy_input() 제공.
    """

    source: str                    # 'dart' | 'naver_news' | ...
    category: str                  # 'disclosure' | 'news' | 'macro' | ...
    symbol: str | None             # 종목 코드 (예: 'AAPL', 'KRW-BTC', '005930'), 매크로면 None
    title: str
    summary: str
    url: str
    published_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    """근거 URL 들 (LLM signal 의 'sources' meta 로 전달)."""

    # --- 정형화 ----------------------------------------------------------------

    @property
    def content_hash(self) -> str:
        """source+symbol+title+url 기반 dedupe key."""
        material = f"{self.source}|{self.symbol or ''}|{self.title}|{self.url}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def as_strategy_input(self) -> dict[str, Any]:
        """LLMSignalStrategy.on_event 가 받는 dict 형식."""
        return {
            "source": self.source,
            "category": self.category,
            "symbol": self.symbol,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "published_at": self.published_at.isoformat(),
            "sources": self.sources or ([self.url] if self.url else []),
        }


class Fetcher(ABC):
    """외부 이벤트 폴러."""

    name: str = "abstract"
    """source 식별자 — MarketEvent.source 와 동일."""

    @abstractmethod
    async def fetch(self) -> list[MarketEvent]:
        """주기적으로 호출 — 최근 이벤트 (정상 시 0건 ~ 수십 건)."""

    async def close(self) -> None:  # noqa: B027
        return None
