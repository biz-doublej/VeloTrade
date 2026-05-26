"""EventDispatcher — fetchers → dedupe → bot.handle_event + DB 기록.

설계:
  - N분마다 모든 fetcher 실행
  - 메모리 LRU 로 content_hash dedupe (재시작 시 vt.documents 에서 backfill)
  - dispatch 대상 봇이 여러 개면 모두에게 전달 (각 봇이 자기 watchlist 필터링)
  - 이벤트 자체는 vt.documents 에 기록 (Day 1 schema 그대로 활용)
    + url_hash, content_hash, entity_tags={"symbol": ..., "category": ...}
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from typing import Awaitable, Callable

import structlog

from velotrade_trading.db.client import DBRecorder
from velotrade_trading.fetchers.base import Fetcher, MarketEvent

log = structlog.get_logger("dispatcher")


class _LRUSet:
    """간단한 LRU 캐시 — content_hash 기반 dedupe (메모리)."""

    def __init__(self, maxsize: int = 5000) -> None:
        self._d: OrderedDict[str, None] = OrderedDict()
        self._max = maxsize

    def add(self, key: str) -> bool:
        """True 면 신규(추가됨), False 면 중복."""
        if key in self._d:
            self._d.move_to_end(key)
            return False
        self._d[key] = None
        if len(self._d) > self._max:
            self._d.popitem(last=False)
        return True


EventHandler = Callable[[MarketEvent], Awaitable[None]]


class EventDispatcher:
    def __init__(
        self,
        *,
        fetchers: list[Fetcher],
        handlers: list[EventHandler],
        db: DBRecorder | None = None,
        poll_interval_sec: int = 300,
        dedupe_size: int = 5000,
    ) -> None:
        self.fetchers = fetchers
        self.handlers = handlers
        self.db = db
        self.poll_interval = poll_interval_sec
        self._seen = _LRUSet(maxsize=dedupe_size)
        self._stopping = False

    async def run(self) -> None:
        log.info(
            "dispatcher.start",
            fetchers=[f.name for f in self.fetchers],
            handlers=len(self.handlers),
            interval_sec=self.poll_interval,
        )
        # 첫 사이클은 즉시
        while not self._stopping:
            await self._cycle()
            if self._stopping:
                break
            await asyncio.sleep(self.poll_interval)

    async def stop(self) -> None:
        self._stopping = True
        for f in self.fetchers:
            try:
                await f.close()
            except Exception:
                pass

    async def _cycle(self) -> None:
        try:
            results = await asyncio.gather(
                *(self._fetch_safe(f) for f in self.fetchers),
                return_exceptions=False,
            )
        except Exception as e:
            log.warning("dispatcher.cycle.failed", error=str(e))
            return

        all_events: list[MarketEvent] = []
        for r in results:
            all_events.extend(r)

        # dedupe
        new_events = [e for e in all_events if self._seen.add(e.content_hash)]
        if not new_events:
            return

        log.info(
            "dispatcher.new_events",
            total=len(all_events),
            new=len(new_events),
        )

        # DB 기록 (best-effort, 비동기)
        if self.db:
            await asyncio.gather(
                *(self._persist(e) for e in new_events),
                return_exceptions=True,
            )

        # 핸들러 dispatch (각 핸들러는 봇 1개에 해당)
        for event in new_events:
            for handler in self.handlers:
                try:
                    await handler(event)
                except Exception as e:
                    log.warning(
                        "dispatcher.handler.failed",
                        event_symbol=event.symbol,
                        error=str(e)[:200],
                    )

    async def _fetch_safe(self, fetcher: Fetcher) -> list[MarketEvent]:
        try:
            return await fetcher.fetch()
        except Exception as e:
            log.warning("fetcher.failed", fetcher=fetcher.name, error=str(e)[:200])
            return []

    async def _persist(self, event: MarketEvent) -> None:
        """vt.documents 에 INSERT — 추후 RAG·차트 시각화 자원."""
        if not self.db:
            return
        url_hash = hashlib.sha256((event.url or event.title).encode()).hexdigest()[:32]
        try:
            await self.db._insert(
                "documents",
                {
                    "url": event.url or "",
                    "url_hash": url_hash,
                    "title": event.title[:500],
                    "published_at": event.published_at.isoformat(),
                    "lang": "ko" if event.source in ("dart", "naver_news") else "en",
                    "raw_text_min": event.summary[:5000],
                    "content_hash": event.content_hash,
                    "entity_tags": {
                        "source": event.source,
                        "category": event.category,
                        "symbol": event.symbol,
                    },
                },
            )
        except Exception as e:
            # 중복 url_hash 면 자연스럽게 unique constraint 실패 — 무시
            log.debug("dispatcher.persist.skipped", error=str(e)[:120])
