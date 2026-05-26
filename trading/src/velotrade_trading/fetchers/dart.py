"""DART OpenAPI 공시 fetcher (한국 금감원 전자공시).

API: https://opendart.fss.or.kr/api/list.json
- 인증키 필수 (DART_API_KEY)
- 종목코드(stock_code, 6자리) 또는 기업코드(corp_code, 8자리) 필수
- 우리는 워치리스트의 한국 종목만 추적 (수동 매핑 — 추후 corpCode.xml 자동화)

응답 예 (단건):
{
  "corp_code": "00126380",
  "corp_name": "삼성전자",
  "stock_code": "005930",
  "corp_cls": "Y",
  "report_nm": "주요사항보고서(자기주식취득결정)",
  "rcept_no": "20260501000123",
  "flr_nm": "삼성전자",
  "rcept_dt": "20260501",
  "rm": ""
}
url: https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import httpx
import structlog

from velotrade_trading.fetchers.base import Fetcher, MarketEvent

log = structlog.get_logger("dart")


# 종목코드 → corp_code (8자리) 매핑.
# 정식으로는 https://opendart.fss.or.kr/api/corpCode.xml 다운 후 파싱.
# 14일 MVP — 핵심 한국 종목 수동 매핑 (사용자가 watchlist 에 추가하면 자동 시도).
_KNOWN_CORP_CODES: dict[str, str] = {
    # stock_code: corp_code
    "005930": "00126380",   # 삼성전자
    "000660": "00164779",   # SK하이닉스
    "035420": "00266961",   # NAVER
    "035720": "00258801",   # 카카오
    "207940": "00880979",   # 삼성바이오로직스
    "005380": "00164742",   # 현대차
    "051910": "00356370",   # LG화학
}


class DartFetcher(Fetcher):
    """DART 최근 공시 fetcher.

    매 호출 시 추적 종목별로 최근 N일 공시를 가져온다.
    """

    name = "dart"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        stock_codes: list[str] | None = None,
        lookback_days: int = 1,
    ) -> None:
        self.api_key = api_key or os.getenv("DART_API_KEY", "")
        self.stock_codes = stock_codes or list(_KNOWN_CORP_CODES.keys())
        self.lookback_days = lookback_days
        if not self.api_key:
            log.warning("dart.disabled.no_key")

    async def fetch(self) -> list[MarketEvent]:
        if not self.api_key:
            return []

        bgn = (datetime.utcnow() - timedelta(days=self.lookback_days)).strftime("%Y%m%d")
        end = datetime.utcnow().strftime("%Y%m%d")

        out: list[MarketEvent] = []
        async with httpx.AsyncClient(timeout=15.0) as c:
            for stock_code in self.stock_codes:
                corp_code = _KNOWN_CORP_CODES.get(stock_code)
                if not corp_code:
                    continue
                try:
                    r = await c.get(
                        "https://opendart.fss.or.kr/api/list.json",
                        params={
                            "crtfc_key": self.api_key,
                            "corp_code": corp_code,
                            "bgn_de": bgn,
                            "end_de": end,
                            "page_count": 50,
                        },
                    )
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    log.warning("dart.fetch.failed", stock_code=stock_code, error=str(e)[:200])
                    continue

                if data.get("status") != "000":
                    # "013": no data — 정상. 다른 코드는 에러.
                    if data.get("status") not in ("013",):
                        log.warning(
                            "dart.status.non-ok",
                            status=data.get("status"),
                            message=data.get("message"),
                        )
                    continue

                for item in data.get("list", []):
                    rcept_no = item.get("rcept_no", "")
                    title = item.get("report_nm", "(no title)")
                    try:
                        published_at = datetime.strptime(item["rcept_dt"], "%Y%m%d")
                    except Exception:
                        published_at = datetime.utcnow()
                    out.append(
                        MarketEvent(
                            source="dart",
                            category="disclosure",
                            symbol=stock_code,
                            title=title,
                            summary=item.get("flr_nm", "") or title,
                            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                            published_at=published_at,
                            raw=item,
                        )
                    )
                # rate limit 회피
                await asyncio.sleep(0.2)

        log.info("dart.fetched", count=len(out), symbols=len(self.stock_codes))
        return out
