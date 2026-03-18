"""FINRA 4210 Margin Engine — computes maintenance margin on all positions.

FINRA Rule 4210 governs maintenance margin requirements for the entire portfolio.
This engine:

1. Takes ALL positions in the account as input (SOD + intraday changes)
2. Runs strategy recognition on the full position book
3. Calculates FINRA 4210 maintenance margin per strategy or per position
4. Uses EOD/market price as the margin basis
5. Applies house margin rules (must be >= regulatory)

This engine operates independently from the Reg T engine.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from paragraph_margin.models.accounts import Account
from paragraph_margin.models.margin import MarginRequirement, MarginSummary
from paragraph_margin.models.positions import Position
from paragraph_margin.models.strategies import RecognizedStrategy, StrategyGroup
from paragraph_margin.calculators.finra_4210 import FINRA4210Calculator
from paragraph_margin.calculators.strategy_margin import StrategyMarginCalculator
from paragraph_margin.calculators.strategy_recognizer import StrategyRecognizer
from paragraph_margin.engine.context import build_position_context
from paragraph_margin.engine.evaluator import evaluate_formula
from paragraph_margin.engine.matcher import find_matching_rules
from paragraph_margin.rules.registry import MarginRulesRegistry
from paragraph_margin.money import ZERO, max_of, round_margin


class FINRA4210Engine:
    """FINRA 4210 maintenance margin engine — operates on all positions."""

    def __init__(self, registry: MarginRulesRegistry) -> None:
        self._registry = registry
        self._calculator = FINRA4210Calculator(registry)
        self._strategy_recognizer = StrategyRecognizer()
        self._strategy_calculator = StrategyMarginCalculator(registry)
        self._house_rules = registry.house_rules

    @property
    def strategy_recognizer(self) -> StrategyRecognizer:
        return self._strategy_recognizer

    @property
    def strategy_calculator(self) -> StrategyMarginCalculator:
        return self._strategy_calculator

    def calculate_account_margin(
        self,
        account: Account,
        underlying_prices: Optional[dict[str, Decimal]] = None,
    ) -> tuple[MarginSummary, StrategyGroup]:
        """Calculate FINRA 4210 maintenance margin for the full portfolio."""
        prices = underlying_prices or {}
        requirements: list[MarginRequirement] = []
        total_maintenance = ZERO
        total_house = ZERO

        # Step 1: Recognize strategies from ALL positions
        strategy_group = self._strategy_recognizer.recognize(
            account.positions, underlying_prices=prices
        )

        # Step 2: Calculate margin for each recognized strategy
        for strategy in strategy_group.strategies:
            u_price = prices.get(strategy.underlying_symbol, ZERO)
            req = self._strategy_calculator.calculate(strategy, u_price)
            requirements.append(req)
            total_maintenance += req.finra_4210_maintenance
            total_house += req.house_margin

        # Step 3: Calculate per-position margin for unmatched positions
        for position in strategy_group.unmatched_positions:
            u_price = self._get_underlying_price(position, prices)
            req = self._calculate_position_margin(position, u_price)
            requirements.append(req)
            total_maintenance += req.finra_4210_maintenance
            total_house += req.house_margin

        summary = MarginSummary(
            account_id=account.account_id,
            as_of=datetime.now(),
            long_market_value=account.long_market_value,
            short_market_value=account.short_market_value,
            cash_balance=account.cash_balance,
            maintenance_requirement=round_margin(total_maintenance),
            house_requirement=round_margin(total_house),
            sma_balance=account.sma.balance,
            requirements=requirements,
        )
        return summary, strategy_group

    def _calculate_position_margin(
        self, position: Position, underlying_price: Decimal = ZERO
    ) -> MarginRequirement:
        """Calculate FINRA 4210 + house margin for a single position."""
        finra_req = self._calculator.calculate(position, underlying_price)

        # House margin
        context = build_position_context(position, underlying_price)
        house_matching = find_matching_rules(self._house_rules, context, self._registry.disabled_rule_ids)
        house_margin = ZERO
        for rule in house_matching:
            amount = evaluate_formula(rule, context)
            house_margin = max_of(house_margin, amount)

        return MarginRequirement(
            position_id=position.position_id,
            finra_4210_maintenance=finra_req.finra_4210_maintenance,
            house_margin=house_margin,
            rule_ids=finra_req.rule_ids,
            citations=finra_req.citations,
            calculation_detail=finra_req.calculation_detail,
        )

    @staticmethod
    def _get_underlying_price(
        position: Position, prices: dict[str, Decimal]
    ) -> Decimal:
        price = prices.get(position.security.symbol, ZERO)
        if price > ZERO:
            return price
        if hasattr(position.security, "underlying_symbol"):
            return prices.get(position.security.underlying_symbol, ZERO)
        return ZERO
