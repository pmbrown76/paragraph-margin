"""Shared test fixtures for paragraph-margin."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from paragraph_margin import (
    Account,
    Equity,
    Option,
    Position,
    PositionSide,
    SecurityType,
    OptionType,
    ExerciseStyle,
    SettlementType,
    RuleConfig,
    FormulaConfig,
    MinimumConfig,
    MarginRulesRegistry,
)
from paragraph_margin.money import ZERO


@pytest.fixture
def aapl_equity():
    return Equity(
        security_id="AAPL",
        symbol="AAPL",
        description="Apple Inc.",
    )


@pytest.fixture
def aapl_long_position(aapl_equity):
    return Position(
        position_id="pos_aapl_long",
        account_id="acct_001",
        security=aapl_equity,
        side=PositionSide.LONG,
        quantity=Decimal("100"),
        average_cost=Decimal("150.00"),
        market_price=Decimal("175.00"),
    )


@pytest.fixture
def aapl_short_position(aapl_equity):
    return Position(
        position_id="pos_aapl_short",
        account_id="acct_001",
        security=aapl_equity,
        side=PositionSide.SHORT,
        quantity=Decimal("100"),
        average_cost=Decimal("175.00"),
        market_price=Decimal("175.00"),
    )


@pytest.fixture
def aapl_call_option(aapl_equity):
    return Option(
        security_id="AAPL_C_180_20250620",
        symbol="AAPL250620C00180000",
        underlying=aapl_equity,
        underlying_symbol="AAPL",
        option_type=OptionType.CALL,
        strike=Decimal("180"),
        expiration=date(2025, 6, 20),
    )


@pytest.fixture
def aapl_put_option(aapl_equity):
    return Option(
        security_id="AAPL_P_170_20250620",
        symbol="AAPL250620P00170000",
        underlying=aapl_equity,
        underlying_symbol="AAPL",
        option_type=OptionType.PUT,
        strike=Decimal("170"),
        expiration=date(2025, 6, 20),
    )


@pytest.fixture
def reg_t_equity_rule():
    """Standard Reg T 50% initial margin rule for equities."""
    return RuleConfig(
        id="reg_t_equity_long",
        description="Reg T initial margin for long equity positions",
        citation="Reg T 220.12 Supplement",
        conditions={"security_type": "equity", "position_side": "long", "marginable": True},
        formula=FormulaConfig(type="percentage_of_trade_value", rate=0.50),
    )


@pytest.fixture
def reg_t_short_equity_rule():
    """Standard Reg T 50% initial margin for short equities."""
    return RuleConfig(
        id="reg_t_equity_short",
        description="Reg T initial margin for short equity positions",
        citation="Reg T 220.12 Supplement",
        conditions={"security_type": "equity", "position_side": "short", "marginable": True},
        formula=FormulaConfig(type="percentage_of_trade_value", rate=0.50),
    )


@pytest.fixture
def finra_equity_long_rule():
    """FINRA 4210 25% maintenance margin for long equities."""
    return RuleConfig(
        id="4210_equity_long",
        description="FINRA 4210 maintenance for long equity >= $5",
        citation="FINRA 4210(c)(1)",
        conditions={"security_type": "equity", "position_side": "long", "marginable": True, "price_gte": 5.0},
        formula=FormulaConfig(type="percentage_of_market_value", rate=0.25),
    )


@pytest.fixture
def finra_equity_short_rule():
    """FINRA 4210 30% maintenance for short equities."""
    return RuleConfig(
        id="4210_equity_short",
        description="FINRA 4210 maintenance for short equity",
        citation="FINRA 4210(c)(1)",
        conditions={"security_type": "equity", "position_side": "short", "marginable": True},
        formula=FormulaConfig(type="percentage_of_market_value", rate=0.30),
        minimum=MinimumConfig(type="fixed_per_share", amount=5.0),
    )


@pytest.fixture
def finra_naked_call_rule():
    """FINRA 4210 naked call option rule."""
    return RuleConfig(
        id="4210_f_2_E_i_call",
        description="Naked call option — 20% of underlying + premium - OTM",
        citation="FINRA 4210(f)(2)(E)(i)",
        conditions={"security_type": "option", "option_type": "call", "position_side": "short", "covered": False},
        formula=FormulaConfig(
            type="naked_option",
            underlying_pct=0.20,
            otm_deduction=True,
            minimum_underlying_pct=0.10,
            minimum_per_contract=250,
        ),
    )


@pytest.fixture
def basic_registry(
    reg_t_equity_rule,
    reg_t_short_equity_rule,
    finra_equity_long_rule,
    finra_equity_short_rule,
    finra_naked_call_rule,
):
    """A basic MarginRulesRegistry with core rules for testing."""
    registry = MarginRulesRegistry()
    registry.add_rules("reg_t", [reg_t_equity_rule, reg_t_short_equity_rule])
    registry.add_rules("finra_4210", [
        finra_equity_long_rule,
        finra_equity_short_rule,
        finra_naked_call_rule,
    ])
    return registry
