"""Tests for Reg T calculator."""

from decimal import Decimal

import pytest

from margin_calc_engine import RegTCalculator
from margin_calc_engine.money import ZERO


class TestRegTCalculator:
    def test_long_equity_50pct(self, aapl_long_position, basic_registry):
        calc = RegTCalculator(basic_registry)
        req = calc.calculate(aapl_long_position)
        # 50% of trade value = 0.50 * 100 * 150 = $7500
        assert req.reg_t_initial == Decimal("7500.00")
        assert "reg_t_equity_long" in req.rule_ids

    def test_short_equity_50pct(self, aapl_short_position, basic_registry):
        calc = RegTCalculator(basic_registry)
        req = calc.calculate(aapl_short_position)
        # 50% of trade value = 0.50 * 100 * 175 = $8750
        assert req.reg_t_initial == Decimal("8750.00")

    def test_no_matching_rules(self, aapl_long_position):
        calc = RegTCalculator()
        req = calc.calculate(aapl_long_position)
        assert req.reg_t_initial == ZERO
