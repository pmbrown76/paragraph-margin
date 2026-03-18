"""Tests for all formula types in the evaluator."""

from decimal import Decimal

import pytest

from paragraph_margin import (
    RuleConfig,
    FormulaConfig,
    MinimumConfig,
    evaluate_formula,
)
from paragraph_margin.money import ZERO


class TestPercentageOfMarketValue:
    def test_basic(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="percentage_of_market_value", rate=0.25),
        )
        ctx = {"market_value": Decimal("50000"), "quantity": Decimal("100")}
        assert evaluate_formula(rule, ctx) == Decimal("12500.00")

    def test_with_fixed_per_share_minimum(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="percentage_of_market_value", rate=0.25),
            minimum=MinimumConfig(type="fixed_per_share", amount=2.50),
        )
        # $250 market value, 25% = $62.50, but min $2.50 * 100 = $250
        ctx = {"market_value": Decimal("250"), "quantity": Decimal("100")}
        assert evaluate_formula(rule, ctx) == Decimal("250.00")


class TestPercentageOfTradeValue:
    def test_basic(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="percentage_of_trade_value", rate=0.50),
        )
        ctx = {"trade_value": Decimal("15000"), "quantity": Decimal("100")}
        assert evaluate_formula(rule, ctx) == Decimal("7500.00")


class TestPercentageOfPrincipal:
    def test_basic(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="percentage_of_principal", rate=0.07),
        )
        ctx = {"par_value": Decimal("1000"), "quantity": Decimal("10")}
        assert evaluate_formula(rule, ctx) == Decimal("700.00")


class TestFixedPerShare:
    def test_basic(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="fixed_per_share", rate=5.0),
        )
        ctx = {"quantity": Decimal("100")}
        assert evaluate_formula(rule, ctx) == Decimal("500.00")


class TestNakedOption:
    def test_itm_call(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(
                type="naked_option",
                underlying_pct=0.20,
                otm_deduction=True,
                minimum_underlying_pct=0.10,
                minimum_per_contract=250,
            ),
        )
        ctx = {
            "market_value": Decimal("500"),  # premium = 5.00 * 100
            "quantity": Decimal("1"),
            "underlying_price": Decimal("180"),
            "strike": Decimal("175"),
            "contract_multiplier": 100,
            "option_type": "call",
        }
        # Premium = $500
        # 20% of underlying = 0.20 * 180 * 100 * 1 = $3600
        # OTM = 0 (ITM)
        # Main = 3600 - 0 = 3600
        # Min 10% = 0.10 * 18000 = 1800
        # Min $250 per contract = 250
        # Max(3600, 1800, 250) = 3600
        # Total = 500 + 3600 = 4100
        assert evaluate_formula(rule, ctx) == Decimal("4100.00")

    def test_otm_call(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(
                type="naked_option",
                underlying_pct=0.20,
                otm_deduction=True,
                minimum_underlying_pct=0.10,
                minimum_per_contract=250,
            ),
        )
        ctx = {
            "market_value": Decimal("200"),  # premium
            "quantity": Decimal("1"),
            "underlying_price": Decimal("170"),
            "strike": Decimal("180"),
            "contract_multiplier": 100,
            "option_type": "call",
        }
        # Premium = $200
        # 20% of underlying = 0.20 * 170 * 100 = $3400
        # OTM = (180 - 170) * 100 = $1000
        # Main = 3400 - 1000 = 2400
        # Min 10% = 0.10 * 17000 = 1700
        # Min per contract = 250
        # Max(2400, 1700, 250) = 2400
        # Total = 200 + 2400 = 2600
        assert evaluate_formula(rule, ctx) == Decimal("2600.00")


class TestFullPayment:
    def test_basic(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="full_payment"),
        )
        ctx = {"trade_value": Decimal("5000")}
        assert evaluate_formula(rule, ctx) == Decimal("5000.00")


class TestGoodFaith:
    def test_with_rate(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="good_faith", rate=0.05),
        )
        ctx = {"market_value": Decimal("100000")}
        assert evaluate_formula(rule, ctx) == Decimal("5000.00")

    def test_zero_rate(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="good_faith", rate=0.0),
        )
        ctx = {"market_value": Decimal("100000")}
        assert evaluate_formula(rule, ctx) == ZERO


class TestDebitSpread:
    def test_basic(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="debit_spread"),
        )
        ctx = {"net_debit": Decimal("350")}
        assert evaluate_formula(rule, ctx) == Decimal("350.00")


class TestCreditSpread:
    def test_basic(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="credit_spread"),
        )
        ctx = {
            "strike_width": Decimal("5"),
            "contract_multiplier": 100,
            "contracts": Decimal("1"),
            "net_credit": Decimal("150"),
        }
        # Width * mult * qty - credit = 5 * 100 * 1 - 150 = 350
        assert evaluate_formula(rule, ctx) == Decimal("350.00")


class TestShortStraddleStrangle:
    def test_call_dominant(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="short_straddle_strangle"),
        )
        ctx = {
            "naked_call_margin": Decimal("3000"),
            "naked_put_margin": Decimal("2000"),
            "call_premium": Decimal("500"),
            "put_premium": Decimal("300"),
        }
        # Call dominant: 3000 + 300 = 3300
        assert evaluate_formula(rule, ctx) == Decimal("3300.00")


class TestIronCondor:
    def test_basic(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="iron_condor"),
        )
        ctx = {
            "put_wing": Decimal("500"),
            "call_wing": Decimal("500"),
            "put_net_credit": Decimal("100"),
            "call_net_credit": Decimal("150"),
        }
        # Put margin = 500 - 100 = 400
        # Call margin = 500 - 150 = 350
        # Max = 400
        assert evaluate_formula(rule, ctx) == Decimal("400.00")


class TestCoveredEquity:
    def test_basic(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="covered_equity", rate=0.25),
        )
        ctx = {"stock_market_value": Decimal("17500")}
        assert evaluate_formula(rule, ctx) == Decimal("4375.00")


class TestConversion:
    def test_basic(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(
                type="conversion",
                rate=0.10,
                per_contract_minimum=250,
            ),
        )
        ctx = {
            "option_strike": Decimal("175"),
            "contract_multiplier": 100,
            "contracts": Decimal("1"),
        }
        # 10% * 175 * 100 * 1 = 1750
        # Min = 250 * 1 = 250
        # Max(1750, 250) = 1750
        assert evaluate_formula(rule, ctx) == Decimal("1750.00")


class TestSyntheticStock:
    def test_basic(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="synthetic_stock", rate=0.25),
        )
        ctx = {"notional": Decimal("17500")}
        assert evaluate_formula(rule, ctx) == Decimal("4375.00")


class TestUnknownFormula:
    def test_returns_zero(self):
        rule = RuleConfig(
            id="test",
            formula=FormulaConfig(type="unknown_formula_type"),
        )
        ctx = {"market_value": Decimal("10000")}
        assert evaluate_formula(rule, ctx) == ZERO
