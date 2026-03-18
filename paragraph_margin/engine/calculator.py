"""Per-position margin calculation using the rule engine."""

from decimal import Decimal
from typing import Any

from paragraph_margin.models.margin import MarginRequirement
from paragraph_margin.models.positions import Position
from paragraph_margin.rules.schema import RuleConfig
from paragraph_margin.rules.registry import MarginRulesRegistry
from paragraph_margin.engine.context import build_position_context
from paragraph_margin.engine.matcher import find_matching_rules
from paragraph_margin.engine.evaluator import evaluate_formula
from paragraph_margin.money import ZERO, max_of


def evaluate_position_margin(
    position: Position,
    rules: list[RuleConfig],
    underlying_price: Decimal = ZERO,
) -> tuple[MarginRequirement, Decimal]:
    """Evaluate margin for a single position against a set of rules.

    Returns the highest margin from all matching rules (conservative approach).
    """
    context = build_position_context(position, underlying_price)
    matching = find_matching_rules(rules, context)

    if not matching:
        return (
            MarginRequirement(
                position_id=position.position_id,
                calculation_detail="No matching rules found",
            ),
            ZERO,
        )

    # Evaluate each matching rule and take the maximum
    best_margin = ZERO
    best_rule: RuleConfig | None = None
    all_rule_ids = []
    all_citations = []

    for rule in matching:
        margin = evaluate_formula(rule, context)
        all_rule_ids.append(rule.id)
        if rule.citation:
            all_citations.append(rule.citation)
        if margin > best_margin:
            best_margin = margin
            best_rule = rule

    detail = ""
    if best_rule:
        detail = (
            f"Rule: {best_rule.id} | {best_rule.description} | "
            f"Formula: {best_rule.formula.type} @ {best_rule.formula.rate} | "
            f"Result: ${best_margin}"
        )

    return (
        MarginRequirement(
            position_id=position.position_id,
            rule_ids=all_rule_ids,
            citations=all_citations,
            calculation_detail=detail,
        ),
        best_margin,
    )


def evaluate_position_margin_full(
    position: Position,
    registry: MarginRulesRegistry,
    underlying_price: Decimal = ZERO,
) -> MarginRequirement:
    """Evaluate full margin (Reg T + 4210 + house) for a single position."""
    context = build_position_context(position, underlying_price)

    # Reg T initial
    disabled = registry.disabled_rule_ids
    reg_t_matching = find_matching_rules(registry.reg_t_rules, context, disabled)
    reg_t_margin = ZERO
    reg_t_citations: list[str] = []
    reg_t_rule_ids: list[str] = []
    for rule in reg_t_matching:
        margin = evaluate_formula(rule, context)
        reg_t_rule_ids.append(rule.id)
        if rule.citation:
            reg_t_citations.append(rule.citation)
        reg_t_margin = max_of(reg_t_margin, margin)

    # FINRA 4210 maintenance
    finra_matching = find_matching_rules(registry.finra_4210_rules, context, disabled)
    finra_margin = ZERO
    finra_citations: list[str] = []
    finra_rule_ids: list[str] = []
    for rule in finra_matching:
        margin = evaluate_formula(rule, context)
        finra_rule_ids.append(rule.id)
        if rule.citation:
            finra_citations.append(rule.citation)
        finra_margin = max_of(finra_margin, margin)

    # House margin
    house_matching = find_matching_rules(registry.house_rules, context, disabled)
    house_margin = ZERO
    for rule in house_matching:
        margin = evaluate_formula(rule, context)
        house_margin = max_of(house_margin, margin)

    all_citations = reg_t_citations + finra_citations
    all_rule_ids = reg_t_rule_ids + finra_rule_ids

    detail_parts = []
    if reg_t_margin > ZERO:
        detail_parts.append(f"Reg T Initial: ${reg_t_margin}")
    if finra_margin > ZERO:
        detail_parts.append(f"FINRA 4210 Maintenance: ${finra_margin}")
    if house_margin > ZERO:
        detail_parts.append(f"House: ${house_margin}")

    return MarginRequirement(
        position_id=position.position_id,
        reg_t_initial=reg_t_margin,
        finra_4210_maintenance=finra_margin,
        house_margin=house_margin,
        rule_ids=all_rule_ids,
        citations=list(set(all_citations)),
        calculation_detail=" | ".join(detail_parts),
    )
