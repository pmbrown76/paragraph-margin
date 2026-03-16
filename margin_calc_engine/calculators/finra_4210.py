"""FINRA Rule 4210 maintenance margin calculator."""

from decimal import Decimal
from typing import Optional

from margin_calc_engine.models.margin import MarginRequirement
from margin_calc_engine.models.positions import Position
from margin_calc_engine.engine.context import build_position_context
from margin_calc_engine.engine.evaluator import evaluate_formula
from margin_calc_engine.engine.matcher import find_matching_rules
from margin_calc_engine.rules.registry import MarginRulesRegistry
from margin_calc_engine.rules.schema import RuleConfig
from margin_calc_engine.money import ZERO, max_of, round_margin


class FINRA4210Calculator:
    """Calculates FINRA 4210 maintenance margin requirements."""

    def __init__(self, registry: Optional[MarginRulesRegistry] = None) -> None:
        self._registry = registry
        self._rules: list[RuleConfig] = []
        if registry:
            self._rules = registry.finra_4210_rules

    def set_rules(self, rules: list[RuleConfig]) -> None:
        self._rules = rules

    def calculate(
        self,
        position: Position,
        underlying_price: Decimal = ZERO,
    ) -> MarginRequirement:
        """Calculate FINRA 4210 maintenance margin for a single position."""
        context = build_position_context(position, underlying_price)
        disabled = self._registry.disabled_rule_ids if self._registry else None
        matching = find_matching_rules(self._rules, context, disabled)

        margin = ZERO
        best_rule: Optional[RuleConfig] = None
        all_rule_ids: list[str] = []
        all_citations: list[str] = []

        for rule in matching:
            amount = evaluate_formula(rule, context)
            all_rule_ids.append(rule.id)
            if rule.citation:
                all_citations.append(rule.citation)
            if amount > margin:
                margin = amount
                best_rule = rule

        detail = ""
        if best_rule:
            detail = (
                f"FINRA 4210 | Rule: {best_rule.id} | "
                f"{best_rule.description} | "
                f"Citation: {best_rule.citation} | "
                f"Maintenance: ${margin}"
            )
        elif margin == ZERO:
            detail = "FINRA 4210 | No matching rules — no maintenance margin calculated"

        return MarginRequirement(
            position_id=position.position_id,
            finra_4210_maintenance=margin,
            rule_ids=all_rule_ids,
            citations=list(set(all_citations)),
            calculation_detail=detail,
        )

    def calculate_batch(
        self,
        positions: list[Position],
        underlying_prices: Optional[dict[str, Decimal]] = None,
    ) -> list[MarginRequirement]:
        """Calculate FINRA 4210 maintenance margin for multiple positions."""
        results = []
        for pos in positions:
            u_price = ZERO
            if underlying_prices and pos.security.symbol in underlying_prices:
                u_price = underlying_prices[pos.security.symbol]
            results.append(self.calculate(pos, u_price))
        return results
