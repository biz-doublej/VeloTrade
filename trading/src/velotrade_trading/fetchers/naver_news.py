"""네이버 검색 API — 뉴스 fetcher.

API: https://openapi.naver.com/v1/search/news.json
- Client ID + Secret 필수 (NAVER_CLIENT_ID, NAVER_CLIENT_SECRET)
- 키워드 기반 — 종목명/티커 매핑 필요
- 응답 description 은 HTML 태그 포함 (<b> 등) — strip
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx
import structlog

from velotrade_trading.fetchers.base import Fetcher, MarketEvent

log = structlog.get_logger("naver_news")


# 종목 키워드 매핑 — symbol → [검색어 후보] (한·영 혼합 가능).
# 사용자 watchlist 와 별도. 향후 vt.watchlist_items 에 search_terms 컬럼 추가 가능.
_DEFAULT_KEYWORDS: dict[str, list[str]] = {
    # 한국 주식
    "005930": ["삼성전자"],
    "000660": ["SK하이닉스"],
    "035420": ["네이버"],
    "035720": ["카카오"],
    # 미국 주식 (한국어 + 영문 둘 다)
    "AAPL": ["애플", "Apple Inc"],
    "MSFT": ["마이크로소프트", "Microsoft"],
    "NVDA": ["엔비디아", "NVIDIA"],
    "GOOGL": ["구글", "Alphabet"],
    "TSLA": ["테슬라", "Tesla"],
    # 코인
    "BTCUSDT": ["비트코인", "Bitcoin"],
    "KRW-BTC": ["비트코인", "Bitcoin"],
    "ETHUSDT": ["이더리움", "Ethereum"],
    "KRW-ETH": ["이더리움", "Ethereum"],
}


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return _HTML_TAG_RE.sub("", s or "").replace("&quot;", '"').replace("&amp;", "&")


class NaverNewsFetcher(Fetcher):
    name = "naver_news"

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        symbols: list[str] | None = None,
        per_symbol_limit: int = 10,
    ) -> None:
        self.client_id = client_id or os.getenv("NAVER_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("NAVER_CLIENT_SECRET", "")
        self.symbols = symbols or list(_DEFAULT_KEYWORDS.keys())
        self.per_symbol_limit = per_symbol_limit
        if not (self.client_id and self.client_secret):
            log.warning("naver_news.disabled.no_key")

    async def fetch(self) -> list[MarketEvent]:
        if not (self.client_id and self.client_secret):
            return []

        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }

        out: list[MarketEvent] = []
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as c:
            for symbol in self.symbols:
                keywords = _DEFAULT_KEYWORDS.get(symbol, [symbol])
                # 핵심 키워드 1개만 (rate limit 보호)
                query = keywords[0]
                try:
                    r = await c.get(
                        "https://openapi.naver.com/v1/search/news.json",
                        params={
                            "query": query,
                            "display": self.per_symbol_limit,
                            "sort": "date",
                        },
                    )
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    log.warning(
                        "naver.fetch.failed", symbol=symbol, error=str(e)[:200]
                    )
                    continue

                for item in data.get("items", []):
                    try:
                        published_at = parsedate_to_datetime(item.get("pubDate", ""))
                    except Exception:
                        published_at = datetime.utcnow()
                    title = _strip_html(item.get("title", ""))
                    desc = _strip_html(item.get("description", ""))
                    out.append(
                        MarketEvent(
                            source="naver_news",
                            category="news",
                            symbol=symbol,
                            title=title,
                            summary=desc[:500],
                            url=item.get("originallink") or item.get("link", ""),
                            published_at=(
                                published_at.replace(tzinfo=None)
                                if published_at.tzinfo
                                else published_at
                            ),
                            raw={"query": query, **item},
                        )
                    )
                # rate limit (Naver: 약 10 req/sec)
                await asyncio.sleep(0.15)

        log.info("naver.fetched", count=len(out), symbols=len(self.symbols))
        return out
