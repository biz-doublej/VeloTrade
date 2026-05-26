"""TradingBot — 어댑터·전략·리스크매니저를 결합한 이벤트 루프.

루프 개요:
  - 시작 시 portfolio 동기화 + 각 전략 warmup
  - 시세 스트림 구독 → 매 quote 마다 전략 호출 → 시그널 생성
  - 시그널 → DBRecorder.record_signal → RiskManager.validate → Order
  - paper 모드: 어댑터가 paper/testnet 이면 자동 안전
  - 주문 결과·포지션·알림 → Supabase 기록 (best-effort)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

from velotrade_trading.adapters.base import ExchangeAdapter
from velotrade_trading.core.portfolio import Portfolio
from velotrade_trading.core.risk import RiskManager, RiskRejected
from velotrade_trading.core.types import Quote, Signal
from velotrade_trading.db.client import DBRecorder
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
    reload_watchlist_every_sec: int = 30
    """DB 의 watchlist_items 를 N초마다 다시 fetch — 즉시 반영."""


class TradingBot:
    def __init__(
        self,
        *,
        adapter: ExchangeAdapter,
        strategies: list[Strategy],
        risk: RiskManager,
        config: BotConfig,
        alerts: AlertManager | None = None,
        db: DBRecorder | None = None,
        account_id: str | None = None,
    ) -> None:
        self.adapter = adapter
        self.strategies = strategies
        self.risk = risk
        self.config = config
        self.alerts = alerts or AlertManager()
        self.db = db                       # None 이면 DB 기록 안 함 (백테스트·임시 실행용)
        self.account_id = account_id       # DB 의 vt.exchange_accounts.account_id
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

        startup_msg = (
            f"mode={'paper' if self.adapter.is_paper else 'LIVE'}, "
            f"dry_run={self.config.dry_run}, symbols={self.config.symbols}, "
            f"equity={self.portfolio.equity}, db={'ON' if self.db else 'OFF'}"
        )
        await self.alerts.info(
            f"VeloTrade bot started ({self.adapter.name})",
            startup_msg,
        )
        if self.db:
            await self.db.record_alert(
                level="info",
                alert_type="bot_lifecycle",
                title=f"bot started ({self.adapter.name})",
                body=startup_msg,
                meta={"account_id": self.account_id},
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

        # 동시 실행: 시세 루프 + 포트폴리오 주기 동기화 + watchlist 주기 reload
        await asyncio.gather(
            self._quote_loop(),
            self._portfolio_loop(),
            self._watchlist_loop(),
        )

    async def stop(self) -> None:
        self._stopping = True
        if self.db:
            await self.db.record_alert(
                level="info",
                alert_type="bot_lifecycle",
                title=f"bot stopped ({self.adapter.name})",
                body=f"final equity={self.portfolio.equity}",
                meta={"account_id": self.account_id},
            )
            await self.db.close()
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

    async def _watchlist_loop(self) -> None:
        """DB watchlist 를 주기적으로 다시 fetch, 변경 감지 시 self.config.symbols 갱신.

        WebSocket 재구독은 다음 connection cycle 에서 자연 처리 — 봇은 멈춤 없음.
        DB 없거나 watchlist 비어있으면 변경 안 함.
        """
        from velotrade_trading.db.client import get_watchlist
        if not self.db:
            return
        while not self._stopping:
            await asyncio.sleep(self.config.reload_watchlist_every_sec)
            try:
                new_symbols = await get_watchlist(self.db, exchange=self.adapter.name)
            except Exception as e:
                log.warning("watchlist.reload.failed", error=str(e))
                continue
            if not new_symbols:
                continue
            current = set(self.config.symbols)
            incoming = set(new_symbols)
            if current == incoming:
                continue
            added = incoming - current
            removed = current - incoming
            self.config.symbols = sorted(incoming)
            log.info(
                "watchlist.reload",
                added=sorted(added),
                removed=sorted(removed),
                total=len(incoming),
            )
            await self.alerts.info(
                "Watchlist updated",
                f"added={sorted(added)} removed={sorted(removed)} → {sorted(incoming)}",
            )
            # warmup 새 종목 (시그널이 즉시 가능하도록)
            if self._ctx is not None:
                for sym in added:
                    for strat in self.strategies:
                        try:
                            await strat.warmup(sym, self._ctx)
                        except Exception as e:
                            log.warning("watchlist.warmup.failed", symbol=sym, error=str(e))

    async def _refresh_portfolio(self) -> None:
        cash, positions = await asyncio.gather(
            self.adapter.get_cash(),
            self.adapter.get_positions(),
        )
        self.portfolio.set_cash(cash)
        self.portfolio.replace_positions(positions)

        # DB 동기화 (best-effort)
        if self.db and self.account_id:
            for pos in positions:
                await self.db.upsert_position(account_id=self.account_id, position=pos)

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

        # 시그널 자체는 DB 에 항상 기록 (risk 거부 여부와 무관하게 trace)
        signal_id: str | None = None
        try:
            order_attempt = self.risk.validate(signal, self.portfolio, quote)
        except RiskRejected as e:
            if self.db:
                signal_id = await self.db.record_signal(
                    signal,
                    rejected_by_risk=True,
                    reject_reason=str(e),
                )
            await self.alerts.warn(
                f"Signal rejected by RiskManager: {signal.symbol}",
                f"strategy={signal.strategy}, reason={e}, signal={signal.reasoning}",
            )
            return

        # 통과한 시그널 기록
        if self.db:
            signal_id = await self.db.record_signal(signal, rejected_by_risk=False)

        if self.config.dry_run:
            await self.alerts.info(
                f"[DRY-RUN] Would submit: {order_attempt.side.upper()} "
                f"{order_attempt.qty} {order_attempt.symbol}",
                f"strategy={signal.strategy}, reasoning={signal.reasoning}",
            )
            return

        try:
            result = await self.adapter.submit_order(order_attempt)
        except Exception as e:
            await self.alerts.error(
                f"Order submission failed: {order_attempt.symbol}",
                f"error={e!r}, order={order_attempt}",
            )
            if self.db:
                await self.db.record_alert(
                    level="error",
                    alert_type="order",
                    title=f"order submit failed: {order_attempt.symbol}",
                    body=f"error={e!r}",
                    symbol=order_attempt.symbol,
                    meta={"account_id": self.account_id, "signal_id": signal_id},
                )
            return

        # 주문 결과 DB 기록
        if self.db:
            await self.db.record_order(
                result, signal_id=signal_id, account_id=self.account_id
            )

        await self.alerts.trade(
            f"{result.side.upper()} {result.qty} {result.symbol} @ ~{quote.last}",
            f"strategy={signal.strategy} | status={result.status} | "
            f"exchange_order_id={result.exchange_order_id} | reasoning={signal.reasoning}",
        )
