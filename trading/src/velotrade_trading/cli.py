"""VeloTrade trading 봇 CLI.

사용:
  python -m velotrade_trading run --exchange alpaca --mode paper --symbols AAPL,MSFT
  python -m velotrade_trading run --exchange binance --mode paper --symbols BTCUSDT,ETHUSDT
  python -m velotrade_trading run --exchange upbit --mode paper --symbols KRW-BTC,KRW-ETH
  python -m velotrade_trading run --config configs/strategies.yaml --dry-run

기본은 paper + dry-run. --live 와 --no-dry-run 둘 다 명시해야 실거래 가능.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog
import yaml
from dotenv import load_dotenv

from velotrade_trading.adapters.base import ExchangeAdapter
from velotrade_trading.adapters.paper import PaperExchange
from velotrade_trading.backtest import BacktestConfig, BacktestEngine, BacktestResult
from velotrade_trading.core.risk import RiskConfig, RiskManager
from velotrade_trading.db.client import DBRecorder, get_or_create_account, get_watchlist
from velotrade_trading.runner.alerts import AlertManager
from velotrade_trading.runner.bot import BotConfig, TradingBot
from velotrade_trading.strategies import STRATEGY_REGISTRY
from velotrade_trading.strategies.base import Strategy

log = structlog.get_logger("cli")


# 거래소별 기본 시드 계좌 라벨 (seed_db.py 와 일치)
_DEFAULT_ACCOUNT_LABEL = {
    "alpaca": "default",
    "binance": "testnet-default",
    "upbit": "simulated-default",
}
_BASE_CURRENCY = {"alpaca": "USD", "binance": "USDT", "upbit": "KRW"}
_STARTING_CAPITAL = {
    "alpaca": Decimal("100000"),
    "binance": Decimal("10000"),
    "upbit": Decimal("10000000"),
}


def _build_adapter(exchange: str, mode: str) -> ExchangeAdapter:
    """exchange + mode 조합으로 어댑터 인스턴스 반환."""
    is_paper = mode == "paper"

    if exchange == "alpaca":
        from velotrade_trading.adapters.alpaca import AlpacaExchange

        return AlpacaExchange(is_paper=is_paper)

    if exchange == "binance":
        from velotrade_trading.adapters.binance import BinanceExchange

        return BinanceExchange(use_testnet=is_paper)

    if exchange == "upbit":
        from velotrade_trading.adapters.upbit import UpbitExchange

        # paper 모드면 키 불필요 (시세만 사용). live 면 키 필수.
        upbit = UpbitExchange(public_only=is_paper)
        if not is_paper:
            return upbit
        # Upbit 는 testnet 없음 → PaperExchange 로 감싼다.
        return PaperExchange(
            base_name="upbit",
            market_feed=upbit,
            starting_cash=Decimal(os.getenv("PAPER_STARTING_KRW", "10000000")),
            quote_currency="KRW",
        )

    raise SystemExit(f"unknown exchange: {exchange}")


def _build_strategies(spec: list[dict[str, Any]] | None) -> list[Strategy]:
    if not spec:
        # 기본: RSI 14/30/70
        return [STRATEGY_REGISTRY["rsi"]({"period": 14, "oversold": 30, "overbought": 70})]

    out: list[Strategy] = []
    for item in spec:
        name = item["name"]
        if name not in STRATEGY_REGISTRY:
            raise SystemExit(f"unknown strategy: {name}")
        params = {k: v for k, v in item.items() if k != "name"}
        out.append(STRATEGY_REGISTRY[name](params))
    return out


def _load_yaml_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _risk_from_env() -> RiskConfig:
    return RiskConfig(
        max_position_pct=Decimal(os.getenv("RISK_MAX_POSITION_PCT", "0.05")),
        max_per_symbol_pct=Decimal(os.getenv("RISK_PER_SYMBOL_PCT", "0.20")),
        daily_loss_pct=Decimal(os.getenv("RISK_DAILY_LOSS_PCT", "0.02")),
    )


async def _build_db_and_account(
    exchange: str, mode: str, disable_db: bool
) -> tuple[DBRecorder | None, str | None]:
    """Supabase 연결 + 계좌 ID 확보. 실패 시 (None, None) 으로 폴백 (DB 없이 봇 실행)."""
    if disable_db:
        return None, None
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        log.warning("db.disabled.no_env")
        return None, None
    try:
        db = DBRecorder()
        account_id = await get_or_create_account(
            db,
            exchange=exchange,
            account_type=mode,
            label=_DEFAULT_ACCOUNT_LABEL[exchange],
            base_currency=_BASE_CURRENCY[exchange],
            starting_capital=_STARTING_CAPITAL[exchange],
        )
        return db, account_id
    except Exception as e:
        log.warning("db.init.failed", error=str(e))
        return None, None


async def _resolve_symbols(
    args_symbols: str | None, config_symbols: list[str], db: DBRecorder | None, exchange: str
) -> list[str]:
    """우선순위: --symbols > config.symbols > DB watchlist."""
    if args_symbols:
        return args_symbols.split(",")
    if config_symbols:
        return config_symbols
    if db:
        wl = await get_watchlist(db, exchange=exchange)
        if wl:
            log.info("symbols.from.db", count=len(wl))
            return wl
    raise SystemExit("--symbols / config.symbols / watchlist all empty")


async def _build_bot(
    exchange: str,
    mode: str,
    *,
    args_symbols: str | None = None,
    config_data: dict[str, Any] | None = None,
    dry_run: bool = False,
    no_db: bool = False,
) -> TradingBot:
    """단일 거래소 봇 인스턴스 생성 (공용 헬퍼)."""
    config_data = config_data or {}

    db, account_id = await _build_db_and_account(exchange, mode, no_db)
    symbols = await _resolve_symbols(
        args_symbols, config_data.get("symbols", []), db, exchange
    )

    adapter = _build_adapter(exchange, mode)
    strategies = _build_strategies(config_data.get("strategies"))
    risk = RiskManager(_risk_from_env())
    alerts = AlertManager.from_env()

    return TradingBot(
        adapter=adapter,
        strategies=strategies,
        risk=risk,
        alerts=alerts,
        db=db,
        account_id=account_id,
        config=BotConfig(
            symbols=symbols,
            dry_run=dry_run,
            require_paper=(mode == "paper"),
        ),
    )


async def _run(args: argparse.Namespace) -> None:
    load_dotenv()

    config_data: dict[str, Any] = {}
    if args.config:
        config_data = _load_yaml_config(Path(args.config))

    exchange = args.exchange or config_data.get("exchange")
    if not exchange:
        raise SystemExit("--exchange or config.exchange required")

    mode = args.mode or config_data.get("mode", "paper")
    if mode == "live" and not args.live_confirm:
        raise SystemExit(
            "Refusing to run LIVE without --i-know-this-is-live. "
            "Re-run with --i-know-this-is-live to confirm."
        )

    bot = await _build_bot(
        exchange,
        mode,
        args_symbols=args.symbols,
        config_data=config_data,
        dry_run=args.dry_run,
        no_db=args.no_db,
    )

    try:
        await bot.start()
    except KeyboardInterrupt:
        log.info("bot.shutdown.keyboard")
    finally:
        await bot.stop()


async def _run_events(args: argparse.Namespace) -> None:
    """이벤트 폴러 단독 실행 — fetcher → dedupe → DB 기록 (봇 없이).

    봇과 같이 돌리려면 추후 run-all 에 통합.
    """
    from velotrade_trading.fetchers import DartFetcher, NaverNewsFetcher
    from velotrade_trading.runner.event_dispatcher import EventDispatcher

    load_dotenv()

    fetchers: list = []
    if os.getenv("DART_API_KEY"):
        fetchers.append(DartFetcher())
    else:
        log.warning("events.dart.disabled", reason="DART_API_KEY missing")
    if os.getenv("NAVER_CLIENT_ID") and os.getenv("NAVER_CLIENT_SECRET"):
        fetchers.append(NaverNewsFetcher())
    else:
        log.warning("events.naver.disabled", reason="NAVER_CLIENT_ID/SECRET missing")

    if not fetchers:
        raise SystemExit("no fetchers enabled — set DART_API_KEY or NAVER_CLIENT_ID/SECRET in .env")

    db = None if args.no_db else DBRecorder()
    dispatcher = EventDispatcher(
        fetchers=fetchers,
        handlers=[],          # bot 없음 — DB 기록만
        db=db,
        poll_interval_sec=args.interval,
    )
    try:
        await dispatcher.run()
    except KeyboardInterrupt:
        log.info("events.shutdown.keyboard")
    finally:
        await dispatcher.stop()
        if db:
            await db.close()


async def _run_backtest(args: argparse.Namespace) -> None:
    """단일 또는 grid search 백테스트 실행."""
    from datetime import date as date_cls, datetime as datetime_cls
    from decimal import Decimal as Dec

    load_dotenv()

    # date 파싱
    end = (
        datetime_cls.strptime(args.end, "%Y-%m-%d").date()
        if args.end else date_cls.today()
    )
    # start 기본: end - 365 일
    if args.start:
        start = datetime_cls.strptime(args.start, "%Y-%m-%d").date()
    else:
        from datetime import timedelta
        start = end - timedelta(days=365)

    symbols = args.symbols.split(",")

    adapter = _build_adapter(args.exchange, "paper")
    db = None if args.no_db else DBRecorder()

    # 파라미터 조합 — grid 면 cartesian product
    if args.grid and args.strategy == "rsi":
        param_sets = [
            {"period": p, "oversold": o, "overbought": ob, "size_pct": 0.05}
            for p in (9, 14, 21)
            for o in (20, 25, 30)
            for ob in (70, 75, 80)
        ]
    elif args.grid and args.strategy == "ma_cross":
        param_sets = [
            {"fast": f, "slow": s, "size_pct": 0.05}
            for f, s in [(5, 20), (10, 30), (20, 50), (20, 100), (50, 200)]
        ]
    else:
        # 단일 — 기본값 또는 --params 파싱
        if args.strategy == "rsi":
            param_sets = [{"period": 14, "oversold": 30, "overbought": 70, "size_pct": 0.05}]
        elif args.strategy == "ma_cross":
            param_sets = [{"fast": 20, "slow": 50, "size_pct": 0.05}]
        else:
            raise SystemExit(f"unsupported strategy for backtest: {args.strategy}")

    results: list[BacktestResult] = []
    print(f"\n=== backtest: strategy={args.strategy} symbols={symbols} period={start}→{end} ===\n")
    for i, params in enumerate(param_sets, 1):
        # 새 strategy + risk 인스턴스 (state 분리)
        strategy = STRATEGY_REGISTRY[args.strategy](params)
        risk = RiskManager(_risk_from_env())
        engine = BacktestEngine(strategy=strategy, risk=risk)

        config = BacktestConfig(
            strategy_name=args.strategy,
            strategy_params=params,
            symbols=symbols,
            start=start,
            end=end,
            interval=args.interval,
            initial_capital=Dec(args.capital),
        )
        try:
            result = await engine.run(adapter=adapter, config=config)
        except Exception as e:
            print(f"  [{i}/{len(param_sets)}] params={params} → ERROR: {e}")
            continue

        print(f"  [{i}/{len(param_sets)}] {result.summary()}")
        results.append(result)

        # DB 기록
        if db:
            try:
                await db.record_backtest(
                    strategy_type=args.strategy,
                    symbols=symbols,
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    initial_capital=Dec(args.capital),
                    final_value=result.final_value,
                    total_return_pct=result.total_return_pct,
                    sharpe=result.sharpe,
                    max_drawdown_pct=result.max_drawdown_pct,
                    trade_count=result.trade_count,
                    win_rate_pct=result.win_rate_pct,
                    params=params,
                    trades_summary=[
                        {
                            "symbol": t.symbol,
                            "side": t.side,
                            "qty": str(t.qty),
                            "price": str(t.price),
                            "pnl": str(t.pnl),
                            "reasoning": t.reasoning[:100],
                        }
                        for t in result.trades
                    ],
                )
            except Exception as e:
                log.warning("backtest.db.record.failed", error=str(e))

    # best 선택
    if results:
        best_return = max(results, key=lambda r: r.total_return_pct)
        best_sharpe = max(results, key=lambda r: r.sharpe)
        print(f"\n--- top by return ---\n  {best_return.summary()}")
        print(f"--- top by sharpe ---\n  {best_sharpe.summary()}")

    await adapter.close()
    if db:
        await db.close()


async def _run_all(args: argparse.Namespace) -> None:
    """3개 거래소 봇 동시 실행 (paper 전용)."""
    load_dotenv()

    if args.mode == "live":
        raise SystemExit("run-all 은 paper 전용. LIVE 는 거래소별 run 명령 사용.")

    exchanges = ["alpaca", "binance", "upbit"]
    log.info("multi-bot.start", exchanges=exchanges)

    bots: list[TradingBot] = []
    for ex in exchanges:
        try:
            bot = await _build_bot(
                ex,
                "paper",
                args_symbols=None,        # DB watchlist 자동
                dry_run=args.dry_run,
                no_db=args.no_db,
            )
            bots.append(bot)
            log.info("multi-bot.built", exchange=ex, symbols=bot.config.symbols)
        except Exception as e:
            log.warning("multi-bot.build.failed", exchange=ex, error=str(e))

    if not bots:
        raise SystemExit("no bots built — all exchanges failed")

    try:
        # 모든 봇 동시 실행
        await asyncio.gather(*(bot.start() for bot in bots))
    except KeyboardInterrupt:
        log.info("multi-bot.shutdown.keyboard")
    finally:
        # 모든 봇 정리 (한 번에 — 실패해도 다른 봇은 계속 정리)
        await asyncio.gather(
            *(bot.stop() for bot in bots),
            return_exceptions=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="velotrade-trading")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="실시간 봇 실행")
    run.add_argument("--exchange", choices=["alpaca", "binance", "upbit"], required=False)
    run.add_argument("--mode", choices=["paper", "live"], default="paper")
    run.add_argument(
        "--i-know-this-is-live",
        dest="live_confirm",
        action="store_true",
        help="LIVE 모드 확인 (이게 없으면 LIVE 시작 거부)",
    )
    run.add_argument("--symbols", help="콤마구분 (예: AAPL,MSFT). 없으면 DB watchlist 사용")
    run.add_argument("--config", help="YAML 설정 경로")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="시그널만 출력, 주문 차단",
    )
    run.add_argument(
        "--no-db",
        action="store_true",
        help="Supabase 기록 비활성 (DB 없이 봇 실행)",
    )

    # events: fetcher polling 단독 실행
    ev = sub.add_parser("events", help="DART/네이버 등 이벤트 fetcher polling")
    ev.add_argument("--interval", type=int, default=300,
                    help="polling 간격 (초, 기본 300=5분)")
    ev.add_argument("--no-db", action="store_true", help="DB 기록 비활성")

    # backtest: 단일/grid search 백테스트
    bt = sub.add_parser("backtest", help="historical 데이터로 전략 백테스트")
    bt.add_argument("--exchange", choices=["alpaca", "binance", "upbit"], default="alpaca",
                    help="historical 데이터 소스")
    bt.add_argument("--strategy", choices=["rsi", "ma_cross"], required=True)
    bt.add_argument("--symbols", required=True, help="콤마구분")
    bt.add_argument("--start", help="YYYY-MM-DD (기본: end - 365)")
    bt.add_argument("--end", help="YYYY-MM-DD (기본: today)")
    bt.add_argument("--interval", default="1d", choices=["1m", "5m", "15m", "1h", "1d"])
    bt.add_argument("--capital", default="10000", help="초기 자본")
    bt.add_argument("--grid", action="store_true", help="파라미터 grid search")
    bt.add_argument("--no-db", action="store_true", help="DB 기록 비활성")

    # run-all: 3개 거래소 (Alpaca + Binance + Upbit paper) 동시 실행
    run_all = sub.add_parser(
        "run-all",
        help="3개 거래소 paper 봇 동시 실행 (DB watchlist 자동 사용)",
    )
    run_all.add_argument("--mode", choices=["paper"], default="paper",
                        help="paper 전용 (LIVE 는 거래소별 run 명령 사용)")
    run_all.add_argument("--dry-run", action="store_true",
                        help="시그널만 출력, 주문 차단")
    run_all.add_argument("--no-db", action="store_true",
                        help="Supabase 기록 비활성")

    args = parser.parse_args()
    if args.cmd == "run":
        try:
            asyncio.run(_run(args))
        except SystemExit:
            raise
        except Exception as e:
            log.error("bot.fatal", error=repr(e))
            sys.exit(1)
    elif args.cmd == "run-all":
        try:
            asyncio.run(_run_all(args))
        except SystemExit:
            raise
        except Exception as e:
            log.error("multi-bot.fatal", error=repr(e))
            sys.exit(1)
    elif args.cmd == "backtest":
        try:
            asyncio.run(_run_backtest(args))
        except SystemExit:
            raise
        except Exception as e:
            log.error("backtest.fatal", error=repr(e))
            sys.exit(1)
    elif args.cmd == "events":
        try:
            asyncio.run(_run_events(args))
        except SystemExit:
            raise
        except Exception as e:
            log.error("events.fatal", error=repr(e))
            sys.exit(1)


if __name__ == "__main__":
    main()
