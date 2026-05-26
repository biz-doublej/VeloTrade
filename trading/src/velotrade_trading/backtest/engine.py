"""백테스트 엔진 — production Strategy 코드를 그대로 검증.

설계 원칙:
- live runner/bot.py 와 동일한 Strategy/RiskManager 사용
  → 백테스트가 통과한 전략이 production 에서 다른 동작 안 함
- historical close 시간순 재생, 각 close → Quote → strategy.on_quote → Signal
- 가상 fill: market 가격 = close * (1 ± slippage_bps/10000), 수수료 fee_bps
- equity curve 매 step 기록 → Sharpe / max drawdown 계산
- 분/시 데이터는 별도 (Day 4 에선 일봉 1d 만 지원)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import structlog

from velotrade_trading.adapters.base import ExchangeAdapter
from velotrade_trading.core.portfolio import Portfolio
from velotrade_trading.core.risk import RiskManager, RiskRejected
from velotrade_trading.core.types import (
    AssetClass,
    Position,
    Quote,
    Signal,
)
from velotrade_trading.strategies.base import Strategy, StrategyContext

log = structlog.get_logger("backtest")


@dataclass
class Trade:
    """체결된 가상 거래."""

    timestamp: datetime
    symbol: str
    side: str               # 'buy' | 'sell'
    qty: Decimal
    price: Decimal
    fee: Decimal
    pnl: Decimal = Decimal(0)       # sell 시에만 (실현 손익)
    reasoning: str = ""
    strategy: str = ""


@dataclass
class BacktestConfig:
    strategy_name: str
    strategy_params: dict[str, Any]
    symbols: list[str]
    start: date
    end: date
    interval: str = "1d"
    initial_capital: Decimal = Decimal(10_000)
    fee_bps: int = 5
    slippage_bps: int = 5
    base_currency: str = "USD"
    exchange_label: str = ""        # 라벨 (DB 저장용, 빈 문자열 가능)


@dataclass
class BacktestResult:
    config: BacktestConfig
    final_value: Decimal
    total_return_pct: float
    sharpe: float
    max_drawdown_pct: float
    trade_count: int
    win_rate_pct: float
    trades: list[Trade] = field(default_factory=list)
    # 일자별 equity (datetime, value)
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"[{self.config.strategy_name}({self.config.strategy_params})] "
            f"symbols={self.config.symbols} "
            f"period={self.config.start}→{self.config.end} | "
            f"return={self.total_return_pct:+.2f}% sharpe={self.sharpe:+.2f} "
            f"max_dd={self.max_drawdown_pct:.2f}% trades={self.trade_count} "
            f"win={self.win_rate_pct:.1f}%"
        )


class BacktestEngine:
    """단순·정확 우선 — vectorized 아님 (수년 일봉 × 수십 종목까지 OK)."""

    def __init__(self, *, strategy: Strategy, risk: RiskManager) -> None:
        self.strategy = strategy
        self.risk = risk

    async def run(
        self, *, adapter: ExchangeAdapter, config: BacktestConfig
    ) -> BacktestResult:
        # 1. 종목별 historical close 로드
        closes_by_symbol: dict[str, list[Decimal]] = {}
        for sym in config.symbols:
            try:
                series = await adapter.get_historical_closes(
                    sym, limit=2000, interval=config.interval
                )
            except Exception as e:
                log.warning("backtest.fetch.failed", symbol=sym, error=str(e)[:200])
                continue
            if series:
                closes_by_symbol[sym] = series

        if not closes_by_symbol:
            raise RuntimeError("no historical data for any symbol")

        # 가장 짧은 시리즈 길이에 맞춤 (시간 정렬 단순화)
        min_len = min(len(s) for s in closes_by_symbol.values())
        for sym in closes_by_symbol:
            closes_by_symbol[sym] = closes_by_symbol[sym][-min_len:]
        steps = min_len
        log.info("backtest.loaded", symbols=list(closes_by_symbol.keys()), steps=steps)

        # 2. warmup — 첫 30% 또는 전략 window_size 만큼 (시그널 생성 없이 RSI/MA 충전)
        warmup_n = min(
            max(int(steps * 0.3), 30),
            self.strategy.window_size,
            steps - 1,
        )

        portfolio = Portfolio(
            exchange=config.exchange_label or "backtest",
            cash=config.initial_capital,
            currency=config.base_currency,
        )
        ctx = StrategyContext(adapter=adapter, portfolio=portfolio, params={})

        # warmup: 전략의 종가 윈도우 채우기
        for sym, series in closes_by_symbol.items():
            for price in series[:warmup_n]:
                self.strategy._push_close(sym, price)

        trades: list[Trade] = []
        equity_curve: list[tuple[datetime, Decimal]] = []

        # 3. step 반복 — warmup 이후부터
        for step in range(warmup_n, steps):
            # 가상 시각 — 실제 timestamp 없으므로 step 기반 (date 보간은 추후)
            ts = datetime.combine(config.start, datetime.min.time())  # placeholder

            # 각 종목에 대해 quote 생성 → strategy.on_quote
            for sym, series in closes_by_symbol.items():
                price = series[step]
                # 슬리피지 적용 quote (bid/ask 차이는 fill 시 적용)
                quote = Quote(
                    symbol=sym,
                    bid=price,
                    ask=price,
                    last=price,
                    timestamp=ts,
                    exchange=config.exchange_label or "backtest",
                    asset_class=AssetClass.US_STOCK,
                    raw={},
                )

                signal: Signal | None = await self.strategy.on_quote(quote, ctx)
                if signal is None:
                    continue

                # RiskManager 통과 시도
                try:
                    order = self.risk.validate(signal, portfolio, quote)
                except RiskRejected:
                    continue

                # 가상 fill (close ± slippage)
                slip = Decimal(config.slippage_bps) / Decimal(10_000)
                fee_rate = Decimal(config.fee_bps) / Decimal(10_000)
                if order.side == "buy":
                    fill_price = price * (Decimal(1) + slip)
                else:
                    fill_price = price * (Decimal(1) - slip)
                notional = order.qty * fill_price
                fee = notional * fee_rate

                # 잔고 / 포지션 갱신
                if order.side == "buy":
                    cost = notional + fee
                    if cost > portfolio.cash:
                        # 잔고 부족 — skip
                        continue
                    portfolio.cash -= cost
                    self._apply_buy(portfolio, sym, order.qty, fill_price)
                    trades.append(
                        Trade(
                            timestamp=ts,
                            symbol=sym,
                            side="buy",
                            qty=order.qty,
                            price=fill_price,
                            fee=fee,
                            reasoning=signal.reasoning,
                            strategy=signal.strategy,
                        )
                    )
                else:  # sell
                    held = portfolio.positions.get(sym)
                    if held is None or held.qty <= 0:
                        continue
                    qty_to_sell = min(order.qty, held.qty)
                    proceeds = qty_to_sell * fill_price - fee
                    realized_pnl = (
                        (fill_price - held.avg_entry_price) * qty_to_sell - fee
                    )
                    portfolio.cash += proceeds
                    held.qty -= qty_to_sell
                    if held.qty == 0:
                        portfolio.positions.pop(sym, None)
                    self.risk.record_realized_pnl(realized_pnl)
                    trades.append(
                        Trade(
                            timestamp=ts,
                            symbol=sym,
                            side="sell",
                            qty=qty_to_sell,
                            price=fill_price,
                            fee=fee,
                            pnl=realized_pnl,
                            reasoning=signal.reasoning,
                            strategy=signal.strategy,
                        )
                    )

            # equity 기록 (현재가 기준)
            equity = portfolio.cash
            for sym, series in closes_by_symbol.items():
                pos = portfolio.positions.get(sym)
                if pos:
                    equity += pos.qty * series[step]
            equity_curve.append((ts, equity))

        # 4. 마지막 step 에서 강제 청산 (남은 포지션을 마지막 가격에 매도)
        last_step = steps - 1
        for sym, series in list(closes_by_symbol.items()):
            pos = portfolio.positions.get(sym)
            if pos is None or pos.qty == 0:
                continue
            last_price = series[last_step]
            proceeds = pos.qty * last_price
            portfolio.cash += proceeds
            portfolio.positions.pop(sym, None)
            trades.append(
                Trade(
                    timestamp=datetime.combine(config.end, datetime.min.time()),
                    symbol=sym,
                    side="sell",
                    qty=pos.qty,
                    price=last_price,
                    fee=Decimal(0),
                    pnl=(last_price - pos.avg_entry_price) * pos.qty,
                    reasoning="forced liquidation (end of backtest)",
                    strategy=self.strategy.name,
                )
            )

        # 5. 통계 계산
        final_value = portfolio.cash
        total_return = (final_value - config.initial_capital) / config.initial_capital * Decimal(100)
        sharpe = _calc_sharpe(equity_curve, config.initial_capital)
        max_dd_pct = _calc_max_drawdown(equity_curve)

        sells = [t for t in trades if t.side == "sell"]
        wins = [t for t in sells if t.pnl > 0]
        win_rate = (len(wins) / len(sells) * 100) if sells else 0.0

        return BacktestResult(
            config=config,
            final_value=final_value,
            total_return_pct=float(total_return),
            sharpe=sharpe,
            max_drawdown_pct=max_dd_pct,
            trade_count=len(trades),
            win_rate_pct=win_rate,
            trades=trades,
            equity_curve=equity_curve,
        )

    # --- 헬퍼 ----------------------------------------------------------------

    def _apply_buy(
        self,
        portfolio: Portfolio,
        symbol: str,
        qty: Decimal,
        price: Decimal,
    ) -> None:
        existing = portfolio.positions.get(symbol)
        if existing is None:
            portfolio.positions[symbol] = Position(
                symbol=symbol,
                qty=qty,
                avg_entry_price=price,
                current_price=price,
                exchange=portfolio.exchange,
                asset_class=AssetClass.US_STOCK,
            )
        else:
            total_cost = existing.avg_entry_price * existing.qty + price * qty
            total_qty = existing.qty + qty
            existing.avg_entry_price = total_cost / total_qty
            existing.qty = total_qty
            existing.current_price = price


# --- 통계 헬퍼 --------------------------------------------------------------


def _calc_sharpe(
    equity_curve: list[tuple[datetime, Decimal]], initial_capital: Decimal
) -> float:
    """일별 수익률 기준 annualized Sharpe (rf=0)."""
    if len(equity_curve) < 2:
        return 0.0
    values = [float(v) for _, v in equity_curve]
    returns = []
    for i in range(1, len(values)):
        if values[i - 1] <= 0:
            continue
        returns.append((values[i] - values[i - 1]) / values[i - 1])
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / len(returns)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    # 일별 → 연간 환산 (√252)
    return (mean / std) * math.sqrt(252)


def _calc_max_drawdown(equity_curve: list[tuple[datetime, Decimal]]) -> float:
    """최대 낙폭 (%)."""
    if not equity_curve:
        return 0.0
    peak = float(equity_curve[0][1])
    max_dd = 0.0
    for _, v in equity_curve:
        val = float(v)
        peak = max(peak, val)
        if peak <= 0:
            continue
        dd = (peak - val) / peak * 100
        max_dd = max(max_dd, dd)
    return max_dd
