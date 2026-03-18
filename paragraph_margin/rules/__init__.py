"""YAML rule DSL for margin calculations."""

from paragraph_margin.rules.schema import (
    CrossReference,
    FormulaConfig,
    MinimumConfig,
    RuleConfig,
    RuleSet,
    RuleSetMetadata,
)
from paragraph_margin.rules.loader import load_rule_file, load_rules_directory
from paragraph_margin.rules.registry import MarginRulesRegistry
