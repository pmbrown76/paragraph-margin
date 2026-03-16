"""Load and validate margin rules from YAML DSL files."""

from pathlib import Path

import yaml

from margin_calc_engine.rules.schema import (
    CrossReference,
    FormulaConfig,
    MinimumConfig,
    RuleConfig,
    RuleSet,
    RuleSetMetadata,
)


def load_rule_file(file_path: Path) -> RuleSet:
    """Load a single YAML rule file and return a RuleSet."""
    with open(file_path) as f:
        data = yaml.safe_load(f)

    metadata = RuleSetMetadata(**(data.get("rule_set", {})))
    rules = []
    for rule_data in data.get("rules", []):
        # Handle formula as a dict
        if "formula" in rule_data and isinstance(rule_data["formula"], dict):
            rule_data["formula"] = FormulaConfig(**rule_data["formula"])
        # Handle minimum as a dict
        if "minimum" in rule_data and isinstance(rule_data["minimum"], dict):
            rule_data["minimum"] = MinimumConfig(**rule_data["minimum"])
        # Handle cross_references as list of dicts
        if "cross_references" in rule_data and isinstance(rule_data["cross_references"], list):
            rule_data["cross_references"] = [
                CrossReference(**cr) if isinstance(cr, dict) else cr
                for cr in rule_data["cross_references"]
            ]
        # Auto-detect calculation_status from formula type
        if "calculation_status" not in rule_data:
            ftype = ""
            if isinstance(rule_data.get("formula"), FormulaConfig):
                ftype = rule_data["formula"].type
            elif isinstance(rule_data.get("formula"), dict):
                ftype = rule_data["formula"].get("type", "")
            if ftype.startswith("TODO_"):
                rule_data["calculation_status"] = "not_implemented"
                rule_data.setdefault("produces_calculation", False)
            elif ftype == "informational":
                rule_data["calculation_status"] = "informational"
                rule_data.setdefault("produces_calculation", False)
        rules.append(RuleConfig(**rule_data))

    return RuleSet(metadata=metadata, rules=rules, source_file=str(file_path))


def load_rules_directory(dir_path: Path, include_subdirs: bool = False) -> list[RuleSet]:
    """Load all YAML rule files from a directory.

    Args:
        dir_path: Directory containing YAML rule files.
        include_subdirs: If True, also load from subdirectories (e.g., stubs/).
    """
    rule_sets = []
    if not dir_path.exists():
        return rule_sets
    for yaml_file in sorted(dir_path.glob("*.yaml")):
        rule_sets.append(load_rule_file(yaml_file))
    if include_subdirs:
        for subdir in sorted(dir_path.iterdir()):
            if subdir.is_dir():
                for yaml_file in sorted(subdir.glob("*.yaml")):
                    rule_sets.append(load_rule_file(yaml_file))
    return rule_sets
