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


if __name__ == "__main__":
    main()
