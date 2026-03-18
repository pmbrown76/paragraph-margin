"""Rule condition matching logic."""

from typing import Any

from paragraph_margin.rules.schema import RuleConfig


def matches_conditions(rule: RuleConfig, context: dict[str, Any]) -> bool:
    """Check if a position context matches a rule's conditions."""
    # Map from YAML condition suffix to (base_field, comparison_fn)
    COMPARISON_SUFFIXES = {
        "_gte": ("market_price", lambda actual, exp: float(actual) >= float(exp)),
        "_lt": ("market_price", lambda actual, exp: float(actual) < float(exp)),
        "_gt": ("market_price", lambda actual, exp: float(actual) > float(exp)),
        "_lte": ("market_price", lambda actual, exp: float(actual) <= float(exp)),
    }

    for key, expected in rule.conditions.items():
        if expected is None:
            if key in context and context[key] is not None:
                return False
            continue

        # Check if this is a comparison operator condition (price_gte, price_lt, etc.)
        is_comparison = False
        for suffix, (base_field, cmp_fn) in COMPARISON_SUFFIXES.items():
            if key.endswith(suffix):
                # For "price_gte", look up "market_price" in context
                field_name = key[: -len(suffix)]
                # Map condition field names to context field names
                context_field = {
                    "price": "market_price",
                    "years_to_maturity": "years_to_maturity",
                }.get(field_name, field_name)

                actual = context.get(context_field)
                if actual is None or not cmp_fn(actual, expected):
                    return False
                is_comparison = True
                break

        if is_comparison:
            continue

        # Standard exact match
        if key not in context:
            return False

        actual = context[key]
        if isinstance(expected, bool):
            if actual != expected:
                return False
        elif actual != expected:
            return False

    return True


def find_matching_rules(
    rules: list[RuleConfig],
    context: dict[str, Any],
    disabled_rule_ids: set[str] | None = None,
) -> list[RuleConfig]:
    """Find all rules that match a given position context.

    Only considers rules that produce calculations (excludes stubs and informational rules).
    """
    results = []
    for rule in rules:
        if not rule.produces_calculation:
            continue
        if disabled_rule_ids and rule.id in disabled_rule_ids:
            continue
        if matches_conditions(rule, context):
            results.append(rule)
    return results
