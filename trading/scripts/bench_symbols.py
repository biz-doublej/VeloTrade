"""다양한 종목 × RSI grid 백테스트 → DB 저장 + 종목별 best 추출."""

import asyncio
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_PROJ = Path(__file__).resolve().parents[1]
load_dotenv(_PROJ / ".env")
sys.path.insert(0, str(_PROJ / "src"))


# 종목군
US_STOCKS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]  # Mag 7
ETF = ["SPY", "QQQ", "IWM", "DIA"]                                     # 인덱스 ETF
SECTORS = ["XLF", "XLE", "XLK", "XLV", "JPM", "JNJ", "XOM"]           # 섹터
ALPACA_ALL = US_STOCKS + ETF + SECTORS

CRYPTO_BINANCE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
CRYPTO_UPBIT = ["KRW-BTC", "KRW-ETH"]

# RSI grid (압축 — 9 조합)
RSI_PARAMS = [
    {"period": 14, "oversold": 25, "overbought": 75, "size_pct": 0.05},
    {"period": 14, "oversold": 30, "overbought": 70, "size_pct": 0.05},
    {"period": 14, "oversold": 30, "overbought": 75, "size_pct": 0.05},
    {"period": 14, "oversold": 30, "overbought": 80, "size_pct": 0.05},
    {"period": 21, "oversold": 25, "overbought": 75, "size_pct": 0.05},
    {"period": 21, "oversold": 30, "overbought": 70, "size_pct": 0.05},
    {"period": 21, "oversold": 30, "overbought": 75, "size_pct": 0.05},
    {"period": 9, "oversold": 30, "overbought": 70, "size_pct": 0.05},
    {"period": 9, "oversold": 25, "overbought": 75, "size_pct": 0.05},
]


async def run_for_exchange(exchange: str, symbols: list[str], start: date, end: date):
    from velotrade_trading.backtest import BacktestConfig, BacktestEngine
    from velotrade_trading.core.risk import RiskConfig, RiskManager
    from velotrade_trading.db.client import DBRecorder
    from velotrade_trading.strategies import STRATEGY_REGISTRY

    # 어댑터
    if exchange == "alpaca":
        from velotrade_trading.adapters.alpaca import AlpacaExchange
        adapter = AlpacaExchange(is_paper=True)
    elif exchange == "binance":
        from velotrade_trading.adapters.binance import BinanceExchange
        # testnet 사용 (klines 시세는 testnet 에도 같은 데이터 제공)
        adapter = BinanceExchange(use_testnet=True)
    elif exchange == "upbit":
        from velotrade_trading.adapters.upbit import UpbitExchange
        adapter = UpbitExchange(public_only=True)
    else:
        raise SystemExit(exchange)

    db = DBRecorder()
    print(f"\n=== {exchange.upper()} × {len(symbols)} symbols × {len(RSI_PARAMS)} params "
          f"= {len(symbols) * len(RSI_PARAMS)} backtests ===")

    try:
        for sym in symbols:
            best = None
            for params in RSI_PARAMS:
                strat = STRATEGY_REGISTRY["rsi"](params)
                risk = RiskManager(RiskConfig())
                engine = BacktestEngine(strategy=strat, risk=risk)
                cfg = BacktestConfig(
                    strategy_name="rsi",
                    strategy_params=params,
                    symbols=[sym],
                    start=start,
                    end=end,
                    interval="1d",
                    initial_capital=Decimal("10000"),
                )
                try:
                    result = await engine.run(adapter=adapter, config=cfg)
                except Exception as e:
                    print(f"  {sym:8s} params={params} → ERROR: {str(e)[:80]}")
                    continue

                # DB
                try:
                    await db.record_backtest(
                        strategy_type="rsi",
                        symbols=[sym],
                        start_date=start.isoformat(),
                        end_date=end.isoformat(),
                        initial_capital=Decimal("10000"),
                        final_value=result.final_value,
                        total_return_pct=result.total_return_pct,
                        sharpe=result.sharpe,
                        max_drawdown_pct=result.max_drawdown_pct,
                        trade_count=result.trade_count,
                        win_rate_pct=result.win_rate_pct,
                        params=params,
                        trades_summary=[],
                    )
                except Exception:
                    pass

                if best is None or result.sharpe > best.sharpe:
                    best = result

            if best:
                p = best.config.strategy_params
                print(
                    f"  {sym:9s} best: RSI({p['period']:>2d}, {p['oversold']:>2d}/{p['overbought']:>2d}) "
                    f"sharpe={best.sharpe:>+5.2f} return={best.total_return_pct:>+7.2f}% "
                    f"dd={best.max_drawdown_pct:>5.2f}% trades={best.trade_count:>3d}"
                )

    finally:
        await adapter.close()
        await db.close()


async def main():
    end = date.today() - timedelta(days=2)        # 어제까지
    start = end - timedelta(days=365 * 2)         # 2년치

    await run_for_exchange("alpaca", ALPACA_ALL, start, end)
    await run_for_exchange("binance", CRYPTO_BINANCE, start, end)
    await run_for_exchange("upbit", CRYPTO_UPBIT, start, end)


if __name__ == "__main__":
    asyncio.run(main())
