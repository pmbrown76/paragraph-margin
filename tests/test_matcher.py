"""Tests for condition matching."""

from decimal import Decimal

import pytest

from margin_calc_engine import (
    RuleConfig,
    FormulaConfig,
    matches_conditions,
    find_matching_rules,
)


class TestMatchesConditions:
    def test_empty_conditions_match_everything(self):
        rule = RuleConfig(id="test", conditions={})
        assert matches_conditions(rule, {"security_type": "equity"})

    def test_exact_match(self):
        rule = RuleConfig(
            id="test",
            conditions={"security_type": "equity", "position_side": "long"},
        )
        assert matches_conditions(rule, {"security_type": "equity", "position_side": "long"})

    def test_exact_mismatch(self):
        rule = RuleConfig(
            id="test",
            conditions={"security_type": "equity"},
        )
        assert not matches_conditions(rule, {"security_type": "option"})

    def test_missing_context_key(self):
        rule = RuleConfig(
            id="test",
            conditions={"security_type": "equity", "concentrated": True},
        )
        assert not matches_conditions(rule, {"security_type": "equity"})

    def test_boolean_match(self):
        rule = RuleConfig(
            id="test",
            conditions={"marginable": True},
        )
        assert matches_conditions(rule, {"marginable": True})
        assert not matches_conditions(rule, {"marginable": False})

    def test_price_gte(self):
        rule = RuleConfig(
            id="test",
            conditions={"price_gte": 5.0},
        )
        assert matches_conditions(rule, {"market_price": Decimal("10")})
        assert matches_conditions(rule, {"market_price": Decimal("5")})
        assert not matches_conditions(rule, {"market_price": Decimal("4.99")})

    def test_price_lt(self):
        rule = RuleConfig(
            id="test",
            conditions={"price_lt": 5.0},
        )
        assert matches_conditions(rule, {"market_price": Decimal("4.99")})
        assert not matches_conditions(rule, {"market_price": Decimal("5.00")})

    def test_none_condition(self):
        rule = RuleConfig(
            id="test",
            conditions={"index_type": None},
        )
        # Matches when key is absent or value is None
        assert matches_conditions(rule, {})
        assert matches_conditions(rule, {"index_type": None})
        # Does not match when key has a value
        assert not matches_conditions(rule, {"index_type": "broad_based"})


class TestFindMatchingRules:
    def test_finds_matching(self):
        rule1 = RuleConfig(
            id="r1",
            conditions={"security_type": "equity"},
            formula=FormulaConfig(type="percentage_of_market_value", rate=0.25),
        )
        rule2 = RuleConfig(
            id="r2",
            conditions={"security_type": "option"},
            formula=FormulaConfig(type="naked_option"),
        )
        ctx = {"security_type": "equity"}
        matched = find_matching_rules([rule1, rule2], ctx)
        assert len(matched) == 1
        assert matched[0].id == "r1"

    def test_skips_non_producing(self):
        rule = RuleConfig(
            id="stub",
            conditions={"security_type": "equity"},
            produces_calculation=False,
        )
        ctx = {"security_type": "equity"}
        assert find_matching_rules([rule], ctx) == []

    def test_skips_disabled(self):
        rule = RuleConfig(
            id="r1",
            conditions={"security_type": "equity"},
            formula=FormulaConfig(type="percentage_of_market_value", rate=0.25),
        )
        ctx = {"security_type": "equity"}
        assert find_matching_rules([rule], ctx, disabled_rule_ids={"r1"}) == []
