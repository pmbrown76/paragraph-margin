"""Regulation T initial margin calculator.

Per 12 CFR Part 220 (Reg T):
- Equity securities: 50% initial margin (Section 220.12 Supplement)
- Exempt securities (treasuries, munis): good faith margin (Section 220.6)
- Options: per exchange/SRO rules (Section 220.12)
- Non-marginable securities: 100% (full payment)
"""

from decimal import Decimal
from typing import Optional

from paragraph_margin.models.margin import MarginRequirement
from paragraph_margin.models.positions import Position
from paragraph_margin.engine.context import build_position_context
from paragraph_margin.engine.evaluator import evaluate_formula
from paragraph_margin.engine.matcher import find_matching_rules
from paragraph_margin.rules.registry import MarginRulesRegistry
from paragraph_margin.rules.schema import RuleConfig
from paragraph_margin.money import ZERO, max_of, round_margin


class RegTCalculator:
    """Calculates Regulation T initial margin requirements."""

    def __init__(self, registry: Optional[MarginRulesRegistry] = None) -> None:
        self._registry = registry
        self._rules: list[RuleConfig] = []
        if registry:
            self._rules = registry.reg_t_rules

    def set_rules(self, rules: list[RuleConfig]) -> None:
        self._rules = rules

    def calculate(
        self,
        position: Position,
        underlying_price: Decimal = ZERO,
    ) -> MarginRequirement:
        """Calculate Reg T initial margin for a single position."""
        context = build_position_context(position, underlying_price)
        disabled = self._registry.disabled_rule_ids if self._registry else None
        matching = find_matching_rules(self._rules, context, disabled)

        margin = ZERO
        best_rule: Optional[RuleConfig] = None
        all_rule_ids: list[str] = []
        all_citations: list[str] = []

        for rule in matching:
            # Skip account_minimum type rules
            if rule.type == "account_minimum":
                continue
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
                f"Reg T | Rule: {best_rule.id} | "
                f"{best_rule.description} | "
                f"Citation: {best_rule.citation} | "
                f"Margin: ${margin}"
            )
        elif margin == ZERO:
            detail = "Reg T | No matching rules — no initial margin calculated"

        return MarginRequirement(
            position_id=position.position_id,
            reg_t_initial=margin,
            rule_ids=all_rule_ids,
            citations=list(set(all_citations)),
            calculation_detail=detail,
        )

    def calculate_batch(
        self,
        positions: list[Position],
        underlying_prices: Optional[dict[str, Decimal]] = None,
    ) -> list[MarginRequirement]:
        """Calculate Reg T initial margin for multiple positions."""
        results = []
        for pos in positions:
            u_price = ZERO
            if underlying_prices and pos.security.symbol in underlying_prices:
                u_price = underlying_prices[pos.security.symbol]
            results.append(self.calculate(pos, u_price))
        return results
