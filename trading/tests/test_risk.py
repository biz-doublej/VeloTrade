"""RiskManager 위반 시나리오 차단 검증.

production code 의 안전 가드가 의도적 위반 시그널을 모두 막는지 확인.
모든 테스트는 RiskRejected 예외 발생을 확인.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from velotrade_trading.core.portfolio import Portfolio
from velotrade_trading.core.risk import RiskConfig, RiskManager, RiskRejected
from velotrade_trading.core.types import AssetClass, Position, Quote, Signal


# --- 픽스처 ----------------------------------------------------------------


@pytest.fixture
def quote_aapl() -> Quote:
    return Quote(
        symbol="AAPL",
        bid=Decimal("100"),
        ask=Decimal("100.10"),
        last=Decimal("100.05"),
        timestamp=datetime.utcnow(),
        exchange="alpaca",
        asset_class=AssetClass.US_STOCK,
    )


@pytest.fixture
def empty_portfolio() -> Portfolio:
    return Portfolio(exchange="alpaca", cash=Decimal("10000"), currency="USD")


@pytest.fixture
def conservative_risk() -> RiskManager:
    return RiskManager(
        RiskConfig(
            max_position_pct=Decimal("0.05"),
            max_per_symbol_pct=Decimal("0.20"),
            daily_loss_pct=Decimal("0.02"),
            min_order_value=Decimal("10"),
            allow_short=False,
        )
    )


def _signal(side: str, *, symbol="AAPL", size_pct="0.05", confidence=0.8) -> Signal:
    return Signal(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        size_pct=Decimal(size_pct),
        confidence=confidence,
        reasoning="test",
        strategy="test",
    )


# --- 정상 케이스 (sanity check) ---------------------------------------------


def test_normal_buy_passes(conservative_risk, empty_portfolio, quote_aapl):
    """공매도 X, daily loss 한도 내, max pos pct 내 → 통과."""
    order = conservative_risk.validate(_signal("buy"), empty_portfolio, quote_aapl)
    assert order.side == "buy"
    assert order.symbol == "AAPL"
    assert order.qty > 0
    # 5% 자본 = $500, ask=100.10 → qty ≈ 4.99
    notional = order.qty * quote_aapl.ask
    assert Decimal("450") < notional < Decimal("510")


# --- 공매도 차단 ------------------------------------------------------------


def test_short_sell_blocked_no_position(conservative_risk, empty_portfolio, quote_aapl):
    """포지션 없는데 sell → 공매도 → 차단."""
    with pytest.raises(RiskRejected, match="short not allowed"):
        conservative_risk.validate(_signal("sell"), empty_portfolio, quote_aapl)


def test_short_sell_allowed_when_flag_on(empty_portfolio, quote_aapl):
    """allow_short=True 면 통과."""
    risk = RiskManager(
        RiskConfig(
            max_position_pct=Decimal("0.05"),
            max_per_symbol_pct=Decimal("0.20"),
            daily_loss_pct=Decimal("0.02"),
            min_order_value=Decimal("10"),
            allow_short=True,
        )
    )
    # 보유 0 인데 sell — allow_short 라도 잔고 검증에서 또 잡음
    with pytest.raises(RiskRejected, match="no position to sell"):
        risk.validate(_signal("sell"), empty_portfolio, quote_aapl)


# --- 일일 손실 한도 --------------------------------------------------------


def test_daily_loss_limit_blocks_new_orders(conservative_risk, empty_portfolio, quote_aapl):
    """누적 손실이 한도 도달 → 모든 buy 차단."""
    # equity=10000, daily_loss_pct=0.02 → 한도 -200
    conservative_risk.record_realized_pnl(Decimal("-200"))
    with pytest.raises(RiskRejected, match="daily loss limit"):
        conservative_risk.validate(_signal("buy"), empty_portfolio, quote_aapl)


def test_daily_loss_under_limit_still_passes(conservative_risk, empty_portfolio, quote_aapl):
    """한도 미달이면 통과."""
    conservative_risk.record_realized_pnl(Decimal("-100"))   # 절반만 도달
    order = conservative_risk.validate(_signal("buy"), empty_portfolio, quote_aapl)
    assert order.qty > 0


# --- 종목 집중도 -----------------------------------------------------------


def test_per_symbol_cap_partial_fill(conservative_risk, empty_portfolio, quote_aapl):
    """이미 15% 보유 + 추가 5% 시그널 → 5% (max 20%) 까지만."""
    # AAPL 1500 USD 보유 (15%)
    empty_portfolio.positions["AAPL"] = Position(
        symbol="AAPL",
        qty=Decimal("15"),
        avg_entry_price=Decimal("100"),
        current_price=Decimal("100"),
        exchange="alpaca",
        asset_class=AssetClass.US_STOCK,
    )
    empty_portfolio.cash = Decimal("8500")

    order = conservative_risk.validate(_signal("buy", size_pct="0.05"), empty_portfolio, quote_aapl)
    # max_per_symbol_pct=0.20, 현재 15% → 추가 5% 만 허용
    # qty 계산: 5% × 10000 / 100.10 = 4.99
    notional = order.qty * quote_aapl.ask
    assert notional < Decimal("510")


def test_per_symbol_cap_full_reject(conservative_risk, empty_portfolio, quote_aapl):
    """이미 20% 보유 → 추가 buy 완전 차단."""
    empty_portfolio.positions["AAPL"] = Position(
        symbol="AAPL",
        qty=Decimal("20"),
        avg_entry_price=Decimal("100"),
        current_price=Decimal("100"),
        exchange="alpaca",
        asset_class=AssetClass.US_STOCK,
    )
    empty_portfolio.cash = Decimal("8000")
    with pytest.raises(RiskRejected, match="per-symbol cap reached"):
        conservative_risk.validate(_signal("buy"), empty_portfolio, quote_aapl)


# --- 최소 주문 금액 ---------------------------------------------------------


def test_min_order_value_blocks_dust(empty_portfolio, quote_aapl):
    """notional < 10 USD 면 차단 (수수료 효율)."""
    risk = RiskManager(
        RiskConfig(
            max_position_pct=Decimal("0.001"),     # 0.1% 매우 작음
            max_per_symbol_pct=Decimal("0.20"),
            daily_loss_pct=Decimal("0.02"),
            min_order_value=Decimal("10"),
        )
    )
    empty_portfolio.cash = Decimal("1000")
    # 0.1% × 1000 = $1, min=$10 → 거부
    with pytest.raises(RiskRejected, match="notional"):
        risk.validate(_signal("buy"), empty_portfolio, quote_aapl)


# --- 보유 초과 매도 자동 보정 ----------------------------------------------


def test_sell_clamp_to_held_qty(quote_aapl):
    """sell 시그널의 cap 후 qty 가 보유분 초과 → 보유 전량으로 조정."""
    # cap 을 충분히 크게 잡아 시도 qty 가 보유 초과하는 시나리오
    risk = RiskManager(
        RiskConfig(
            max_position_pct=Decimal("0.50"),
            max_per_symbol_pct=Decimal("1.0"),
            daily_loss_pct=Decimal("0.02"),
            min_order_value=Decimal("10"),
            allow_short=False,
        )
    )
    pf = Portfolio(exchange="alpaca", cash=Decimal("800"), currency="USD")
    pf.positions["AAPL"] = Position(
        symbol="AAPL",
        qty=Decimal("2"),                  # 2주만 보유
        avg_entry_price=Decimal("100"),
        current_price=Decimal("100"),
        exchange="alpaca",
        asset_class=AssetClass.US_STOCK,
    )
    # equity=1000, size_pct=0.50 → 시도 5주, 하지만 보유 2주로 clamp
    order = risk.validate(_signal("sell", size_pct="0.50"), pf, quote_aapl)
    assert order.side == "sell"
    assert order.qty == Decimal("2")


# --- 잘못된 가격 ----------------------------------------------------------


def test_zero_price_rejected(conservative_risk, empty_portfolio):
    bad_quote = Quote(
        symbol="AAPL",
        bid=Decimal("0"),
        ask=Decimal("0"),
        last=Decimal("0"),
        timestamp=datetime.utcnow(),
        exchange="alpaca",
        asset_class=AssetClass.US_STOCK,
    )
    with pytest.raises(RiskRejected, match="invalid price"):
        conservative_risk.validate(_signal("buy"), empty_portfolio, bad_quote)


# --- hold / 0 사이즈 ------------------------------------------------------


def test_hold_signal_rejected(conservative_risk, empty_portfolio, quote_aapl):
    """side='hold' 는 actionable 아니라 거부."""
    sig = Signal(
        symbol="AAPL",
        side="hold",  # type: ignore[arg-type]
        size_pct=Decimal("0"),
        confidence=0.5,
        reasoning="hold",
        strategy="test",
    )
    with pytest.raises(RiskRejected, match="hold"):
        conservative_risk.validate(sig, empty_portfolio, quote_aapl)


def test_zero_size_signal_rejected(conservative_risk, empty_portfolio, quote_aapl):
    sig = _signal("buy", size_pct="0")
    with pytest.raises(RiskRejected, match="hold|0-size"):
        conservative_risk.validate(sig, empty_portfolio, quote_aapl)


# --- max_position_pct 상한 강제 -------------------------------------------


def test_max_position_pct_caps_oversized_signal(
    conservative_risk, empty_portfolio, quote_aapl
):
    """size_pct=0.50 시그널이라도 max_position_pct=0.05 로 cap."""
    sig = _signal("buy", size_pct="0.50")
    order = conservative_risk.validate(sig, empty_portfolio, quote_aapl)
    # equity × 0.05 = $500 → qty ≈ 4.99
    notional = order.qty * quote_aapl.ask
    assert notional < Decimal("510"), f"notional {notional} 가 5% cap 초과"
