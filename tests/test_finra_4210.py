"""Tests for FINRA 4210 calculator."""

from decimal import Decimal

import pytest

from paragraph_margin import FINRA4210Calculator
from paragraph_margin.money import ZERO


class TestFINRA4210Calculator:
    def test_long_equity_25pct(self, aapl_long_position, basic_registry):
        calc = FINRA4210Calculator(basic_registry)
        req = calc.calculate(aapl_long_position)
        # 25% of market value = 0.25 * 100 * 175 = $4375
        assert req.finra_4210_maintenance == Decimal("4375.00")
        assert "4210_equity_long" in req.rule_ids

    def test_short_equity_30pct(self, aapl_short_position, basic_registry):
        calc = FINRA4210Calculator(basic_registry)
        req = calc.calculate(aapl_short_position)
        # 30% of market value = 0.30 * 100 * 175 = $5250
        # Min $5/share = $500 — 5250 wins
        assert req.finra_4210_maintenance == Decimal("5250.00")

    def test_no_matching_rules(self, aapl_long_position):
        calc = FINRA4210Calculator()
        req = calc.calculate(aapl_long_position)
        assert req.finra_4210_maintenance == ZERO
