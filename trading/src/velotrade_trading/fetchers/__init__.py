"""외부 이벤트 fetcher — DART 공시, 네이버 뉴스, 추후 매크로 지표 등.

각 fetcher 는 주기적으로 호출되어 MarketEvent 리스트를 반환.
중복은 EventDispatcher 가 content_hash 로 dedupe.
"""

from velotrade_trading.fetchers.base import Fetcher, MarketEvent
from velotrade_trading.fetchers.dart import DartFetcher
from velotrade_trading.fetchers.naver_news import NaverNewsFetcher

__all__ = ["Fetcher", "MarketEvent", "DartFetcher", "NaverNewsFetcher"]
