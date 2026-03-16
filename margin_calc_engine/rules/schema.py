"""Pydantic models for the YAML rule DSL."""

from typing import Any

from pydantic import BaseModel


class CrossReference(BaseModel):
    """A cross-reference from one rule to another."""

    text: str = ""  # The text snippet in source_quote that references another rule
    target_citation: str = ""  # The citation being referenced (e.g., "FINRA 4210(f)(2)(E)")
    target_rule_id: str = ""  # Resolved rule ID (auto-populated by citation resolver)


class FormulaConfig(BaseModel):
    """Configuration for a margin calculation formula."""

    type: str
    rate: float = 0.0
    amount: float = 0.0
    premium_pct: float = 0.0
    underlying_pct: float = 0.0
    otm_deduction: bool = False
    minimum_underlying_pct: float = 0.0
    minimum_per_contract: float = 0.0
    multiplier: float = 0.0  # For buying_power_multiplier, conversion rates, etc.
    floor_rate: float = 0.0  # Floor rate (e.g., 10% of exercise price for protective puts)
    per_contract_minimum: float = 0.0  # Per-contract minimum (e.g., $250 for conversions)
    calculation: str = ""
    description: str = ""


class MinimumConfig(BaseModel):
    """Configuration for a minimum margin requirement."""

    type: str = ""
    amount: float = 0.0


class RuleConfig(BaseModel):
    """A single margin rule from the YAML DSL."""

    id: str
    description: str = ""
    citation: str = ""
    conditions: dict[str, Any] = {}
    formula: FormulaConfig = FormulaConfig(type="percentage_of_market_value")
    minimum: MinimumConfig | None = None
    minimum_of_standard: bool = False
    notes: str = ""
    source_quote: str = ""  # Verbatim text from the regulation establishing this rule
    produces_calculation: bool = True  # True if this rule generates a computable margin number
    calculation_status: str = "active"  # active, not_implemented, informational
    cross_references: list[CrossReference] = []  # Links to other rules referenced in source text
    type: str = ""  # For special rules like account_minimum
    value: float = 0.0
    rule_category: str = "margin"  # margin, locate, close_out, reporting, order_marking, price_restriction, anti_fraud, delivery
    rule_group: str = ""  # Higher-level grouping: margin, short_selling, compliance, etc.


class RuleSetMetadata(BaseModel):
    """Metadata about a rule set."""

    regulation: str = ""
    authority: str = ""
    cfr: str = ""
    section: str = ""
    description: str = ""
    effective_date: str = ""
    last_amended: str = ""
    notes: str = ""


class RuleSet(BaseModel):
    """A complete rule set loaded from a YAML file."""

    metadata: RuleSetMetadata
    rules: list[RuleConfig]
    source_file: str = ""
