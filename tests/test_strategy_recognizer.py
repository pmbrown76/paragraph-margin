"""Tests for strategy pattern matching."""

from datetime import date
from decimal import Decimal

import pytest

from paragraph_margin import (
    Equity,
    Option,
    Position,
    PositionSide,
    OptionType,
    StrategyType,
    StrategyRecognizer,
)


@pytest.fixture
def recognizer():
    return StrategyRecognizer()


@pytest.fixture
def aapl():
    return Equity(security_id="AAPL", symbol="AAPL")


@pytest.fixture
def make_option(aapl):
    def _make(opt_type, strike, side, qty=1, expiry=date(2025, 6, 20)):
        opt = Option(
            security_id=f"AAPL_{opt_type.value}_{strike}",
            symbol=f"AAPL_{opt_type.value}_{strike}",
            underlying=aapl,
            underlying_symbol="AAPL",
            option_type=opt_type,
            strike=Decimal(str(strike)),
            expiration=expiry,
        )
        return Position(
            position_id=f"pos_{opt_type.value}_{strike}_{side.value}",
            account_id="acct_001",
            security=opt,
            side=side,
            quantity=Decimal(str(qty)),
            average_cost=Decimal("5.00"),
            market_price=Decimal("5.00"),
        )
    return _make


class TestCoveredCall:
    def test_basic(self, recognizer, aapl, make_option):
        stock = Position(
            position_id="pos_stock",
            account_id="acct_001",
            security=aapl,
            side=PositionSide.LONG,
            quantity=Decimal("100"),
            average_cost=Decimal("175"),
            market_price=Decimal("175"),
        )
        short_call = make_option(OptionType.CALL, 180, PositionSide.SHORT, 1)
        group = recognizer.recognize([stock, short_call])
        assert len(group.strategies) == 1
        assert group.strategies[0].strategy_type == StrategyType.COVERED_CALL
        assert len(group.unmatched_positions) == 0


class TestBullCallSpread:
    def test_basic(self, recognizer, make_option):
        long_call = make_option(OptionType.CALL, 170, PositionSide.LONG, 1)
        short_call = make_option(OptionType.CALL, 180, PositionSide.SHORT, 1)
        group = recognizer.recognize([long_call, short_call])
        assert len(group.strategies) == 1
        assert group.strategies[0].strategy_type == StrategyType.BULL_CALL_SPREAD


class TestIronCondor:
    def test_basic(self, recognizer, make_option):
        lp = make_option(OptionType.PUT, 160, PositionSide.LONG, 1)
        sp = make_option(OptionType.PUT, 170, PositionSide.SHORT, 1)
        sc = make_option(OptionType.CALL, 180, PositionSide.SHORT, 1)
        lc = make_option(OptionType.CALL, 190, PositionSide.LONG, 1)
        group = recognizer.recognize([lp, sp, sc, lc])
        assert len(group.strategies) == 1
        assert group.strategies[0].strategy_type == StrategyType.IRON_CONDOR


class TestStraddle:
    def test_long_straddle(self, recognizer, make_option):
        lc = make_option(OptionType.CALL, 175, PositionSide.LONG, 1)
        lp = make_option(OptionType.PUT, 175, PositionSide.LONG, 1)
        group = recognizer.recognize([lc, lp])
        assert len(group.strategies) == 1
        assert group.strategies[0].strategy_type == StrategyType.LONG_STRADDLE


class TestUnmatchedPositions:
    def test_single_option_unmatched(self, recognizer, make_option):
        lc = make_option(OptionType.CALL, 175, PositionSide.LONG, 1)
        group = recognizer.recognize([lc])
        assert len(group.strategies) == 0
        assert len(group.unmatched_positions) == 1
