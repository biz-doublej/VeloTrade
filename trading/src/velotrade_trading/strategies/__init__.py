"""매매 전략 — Strategy 추상 + 구현체.

전략은 거래소를 모른다. Quote/이벤트 → Signal 만 발생시킨다.
"""

from velotrade_trading.strategies.base import Strategy, StrategyContext
from velotrade_trading.strategies.llm_signal import LLMSignalStrategy
from velotrade_trading.strategies.ma_cross import MACrossStrategy
from velotrade_trading.strategies.rsi import RSIStrategy

__all__ = [
    "LLMSignalStrategy",
    "MACrossStrategy",
    "RSIStrategy",
    "Strategy",
    "StrategyContext",
]


STRATEGY_REGISTRY = {
    "rsi": RSIStrategy,
    "ma_cross": MACrossStrategy,
    "llm_signal": LLMSignalStrategy,
}
