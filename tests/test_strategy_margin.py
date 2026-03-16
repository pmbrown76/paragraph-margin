"""Tests for strategy margin calculations."""

from datetime import date
from decimal import Decimal

import pytest

from margin_calc_engine import (
    Equity,
    Option,
    Position,
    PositionSide,
    OptionType,
    StrategyType,
    StrategyMarginCalculator,
    MarginRulesRegistry,
    RuleConfig,
    FormulaConfig,
)
from margin_calc_engine.models.strategies import RecognizedStrategy, StrategyLeg
from margin_calc_engine.money import ZERO


@pytest.fixture
def aapl():
    return Equity(security_id="AAPL", symbol="AAPL")


@pytest.fixture
def registry(basic_registry):
    return basic_registry


def _make_option_position(aapl, opt_type, strike, side, qty=1, price=Decimal("5.00")):
    opt = Option(
        security_id=f"AAPL_{opt_type.value}_{strike}",
        symbol=f"AAPL_{opt_type.value}_{strike}",
        underlying=aapl,
        underlying_symbol="AAPL",
        option_type=opt_type,
        strike=Decimal(str(strike)),
        expiration=date(2025, 6, 20),
    )
    return Position(
        position_id=f"pos_{opt_type.value}_{strike}_{side.value}",
        account_id="acct_001",
        security=opt,
        side=side,
        quantity=Decimal(str(qty)),
        average_cost=price,
        market_price=price,
    )


class TestBullCallSpreadMargin:
    def test_debit_spread(self, aapl, registry):
        calc = StrategyMarginCalculator(registry)
        long_call = _make_option_position(aapl, OptionType.CALL, 170, PositionSide.LONG, 1, Decimal("8.00"))
        short_call = _make_option_position(aapl, OptionType.CALL, 180, PositionSide.SHORT, 1, Decimal("3.00"))

        strategy = RecognizedStrategy(
            strategy_id="test_bull_call",
            strategy_type=StrategyType.BULL_CALL_SPREAD,
            legs=[
                StrategyLeg(position=long_call, role="long_call", ratio=1),
                StrategyLeg(position=short_call, role="short_call", ratio=1),
            ],
            underlying_symbol="AAPL",
        )
        req = calc.calculate(strategy, Decimal("175"))
        # Net debit = (8 - 3) * 100 = $500
        # Strike width = (180 - 170) * 100 = $1000
        # Margin = min($500, $1000) = $500
        assert req.finra_4210_maintenance == Decimal("500.00")
