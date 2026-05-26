"""TradingBot — 어댑터·전략·리스크매니저를 결합한 이벤트 루프.

루프 개요:
  - 시작 시 portfolio 동기화 + 각 전략 warmup
  - 시세 스트림 구독 → 매 quote 마다 전략 호출 → 시그널 생성
  - 시그널 → RiskManager.validate → Order
  - --dry-run: 시그널만 출력, 주문 차단
  - paper 모드: 어댑터가 paper/testnet 이면 자동 안전
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog

from velotrade_trading.adapters.base import ExchangeAdapter
from velotrade_trading.core.portfolio import Portfolio
from velotrade_trading.core.risk import RiskManager, RiskRejected
from velotrade_trading.core.types import Quote, Signal
from velotrade_trading.runner.alerts import AlertManager
from velotrade_trading.strategies.base import Strategy, StrategyContext

log = structlog.get_logger("bot")


@dataclass
class BotConfig:
    symbols: list[str]
    dry_run: bool = False
    require_paper: bool = True
    """True 면 어댑터의 is_paper == False 일 때 시작 거부 (안전 가드)."""
    refresh_portfolio_every_sec: int = 30


class TradingBot:
    def __init__(
        self,
        *,
        adapter: ExchangeAdapter,
        strategies: list[Strategy],
        risk: RiskManager,
        config: BotConfig,
        alerts: AlertManager | None = None,
    ) -> None:
        self.adapter = adapter
        self.strategies = strategies
        self.risk = risk
        self.config = config
        self.alerts = alerts or AlertManager()
        self.portfolio = Portfolio(exchange=adapter.name, currency=adapter.quote_currency)
        self._ctx: StrategyContext | None = None
        self._stopping = False

    # --- 수명주기 -----------------------------------------------------------

    async def start(self) -> None:
        if self.config.require_paper and not self.adapter.is_paper:
            raise RuntimeError(
                f"adapter {self.adapter.name} is LIVE — pass --live explicitly to override"
            )

        await self._refresh_portfolio()
        await self.alerts.info(
            f"VeloTrade bot started ({self.adapter.name})",
            f"mode={'paper' if self.adapter.is_paper else 'LIVE'}, "
            f"dry_run={self.config.dry_run}, symbols={self.config.symbols}, "
            f"equity={self.portfolio.equity}",
        )

        self._ctx = StrategyContext(
            adapter=self.adapter,
            portfolio=self.portfolio,
            params={},
        )

        # warmup
        for strat in self.strategies:
            for sym in self.config.symbols:
                try:
                    await strat.warmup(sym, self._ctx)
                except Exception as e:
                    log.warning("warmup.failed", strategy=strat.name, symbol=sym, error=str(e))

        # 동시 실행: 시세 루프 + 포트폴리오 주기 동기화
        await asyncio.gather(
            self._quote_loop(),
            self._portfolio_loop(),
        )

    async def stop(self) -> None:
        self._stopping = True
        await self.adapter.close()
        await self.alerts.info("VeloTrade bot stopped")

    # --- 메인 루프 ----------------------------------------------------------

    async def _quote_loop(self) -> None:
        assert self._ctx is not None
        async for quote in self.adapter.stream_quotes(self.config.symbols):
            if self._stopping:
                break
            await self._handle_quote(quote, self._ctx)

    async def _portfolio_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.config.refresh_portfolio_every_sec)
            try:
                await self._refresh_portfolio()
            except Exception as e:
                log.warning("portfolio.refresh.failed", error=str(e))

    async def _refresh_portfolio(self) -> None:
        cash, positions = await asyncio.gather(
            self.adapter.get_cash(),
            self.adapter.get_positions(),
        )
        self.portfolio.set_cash(cash)
        self.portfolio.replace_positions(positions)

    # --- 시그널 → 주문 ------------------------------------------------------

    async def _handle_quote(self, quote: Quote, ctx: StrategyContext) -> None:
        for strat in self.strategies:
            try:
                sig = await strat.on_quote(quote, ctx)
            except Exception as e:
                log.warning("strategy.failed", strategy=strat.name, error=str(e))
                continue
            if sig is None:
                continue
            await self._process_signal(sig, quote)

    async def handle_event(self, event: dict) -> None:
        """외부에서 호출 가능한 이벤트 진입점 (LLM signal 용)."""
        assert self._ctx is not None
        for strat in self.strategies:
            try:
                sig = await strat.on_event(event, self._ctx)
            except Exception as e:
                log.warning("strategy.event.failed", strategy=strat.name, error=str(e))
                continue
            if sig is None or not sig.is_actionable:
                continue
            quote = await self.adapter.get_quote(sig.symbol)
            await self._process_signal(sig, quote)

    async def _process_signal(self, signal: Signal, quote: Quote) -> None:
        log.info(
            "signal",
            symbol=signal.symbol,
            side=signal.side,
            size_pct=str(signal.size_pct),
            confidence=signal.confidence,
            strategy=signal.strategy,
            reasoning=signal.reasoning,
        )

        try:
            order = self.risk.validate(signal, self.portfolio, quote)
        except RiskRejected as e:
            await self.alerts.warn(
                f"Signal rejected by RiskManager: {signal.symbol}",
                f"strategy={signal.strategy}, reason={e}, signal={signal.reasoning}",
            )
            return

        if self.config.dry_run:
            await self.alerts.info(
                f"[DRY-RUN] Would submit: {order.side.upper()} {order.qty} {order.symbol}",
                f"strategy={signal.strategy}, reasoning={signal.reasoning}",
            )
            return

        try:
            result = await self.adapter.submit_order(order)
        except Exception as e:
            await self.alerts.error(
                f"Order submission failed: {order.symbol}",
                f"error={e!r}, order={order}",
            )
            return

        await self.alerts.trade(
            f"{order.side.upper()} {order.qty} {order.symbol} @ ~{quote.last}",
            f"strategy={signal.strategy} | status={result.status} | "
            f"exchange_order_id={result.exchange_order_id} | reasoning={signal.reasoning}",
        )
