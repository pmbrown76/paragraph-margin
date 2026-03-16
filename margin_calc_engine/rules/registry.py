"""Central registry of all loaded margin rules, organized by regulation."""

import re
from pathlib import Path

from margin_calc_engine.rules.schema import CrossReference, RuleConfig, RuleSet
from margin_calc_engine.rules.loader import load_rules_directory


class MarginRulesRegistry:
    """Central registry of all loaded margin rules, organized by regulation."""

    def __init__(self) -> None:
        self.reg_t_rules: list[RuleConfig] = []
        self.finra_4210_rules: list[RuleConfig] = []
        self.house_rules: list[RuleConfig] = []
        self.reg_sho_rules: list[RuleConfig] = []
        self.finra_reporting_rules: list[RuleConfig] = []
        self.sec_rules: list[RuleConfig] = []
        self._all_rules: dict[str, RuleConfig] = {}
        self._rule_sets: list[RuleSet] = []
        self.disabled_rule_ids: set[str] = set()

    def load_from_directory(self, base_dir: Path) -> None:
        """Load all margin rules from the config directory structure."""
        # Load Reg T rules
        for rule_set in load_rules_directory(base_dir / "reg_t"):
            self._rule_sets.append(rule_set)
            for rule in rule_set.rules:
                self.reg_t_rules.append(rule)
                self._all_rules[rule.id] = rule

        # Load FINRA 4210 rules (including stubs/ subdirectory)
        for rule_set in load_rules_directory(base_dir / "finra_4210", include_subdirs=True):
            self._rule_sets.append(rule_set)
            for rule in rule_set.rules:
                self.finra_4210_rules.append(rule)
                self._all_rules[rule.id] = rule

        # Load house rules
        for rule_set in load_rules_directory(base_dir / "house"):
            self._rule_sets.append(rule_set)
            for rule in rule_set.rules:
                self.house_rules.append(rule)
                self._all_rules[rule.id] = rule

        # Load Reg SHO rules
        for rule_set in load_rules_directory(base_dir / "reg_sho"):
            self._rule_sets.append(rule_set)
            for rule in rule_set.rules:
                self.reg_sho_rules.append(rule)
                self._all_rules[rule.id] = rule

        # Load FINRA reporting/compliance rules
        for rule_set in load_rules_directory(base_dir / "finra_reporting"):
            self._rule_sets.append(rule_set)
            for rule in rule_set.rules:
                self.finra_reporting_rules.append(rule)
                self._all_rules[rule.id] = rule

        # Load SEC rules (anti-fraud, financial responsibility, etc.)
        for rule_set in load_rules_directory(base_dir / "sec"):
            self._rule_sets.append(rule_set)
            for rule in rule_set.rules:
                self.sec_rules.append(rule)
                self._all_rules[rule.id] = rule

        # Auto-resolve cross-references between rules
        self.resolve_cross_references()

    def add_rules(self, regulation: str, rules: list[RuleConfig]) -> None:
        """Add rules programmatically (no filesystem required).

        Args:
            regulation: One of 'reg_t', 'finra_4210', 'house', 'reg_sho',
                        'finra_reporting', 'sec'.
            rules: List of RuleConfig objects to add.
        """
        rule_list_map = {
            "reg_t": self.reg_t_rules,
            "finra_4210": self.finra_4210_rules,
            "house": self.house_rules,
            "reg_sho": self.reg_sho_rules,
            "finra_reporting": self.finra_reporting_rules,
            "sec": self.sec_rules,
        }
        target = rule_list_map.get(regulation)
        if target is None:
            raise ValueError(f"Unknown regulation: {regulation}. Use one of: {list(rule_list_map.keys())}")
        for rule in rules:
            target.append(rule)
            self._all_rules[rule.id] = rule

    def get_rule(self, rule_id: str) -> RuleConfig | None:
        """Look up a rule by ID. Returns None if the rule is disabled."""
        if rule_id in self.disabled_rule_ids:
            return None
        return self._all_rules.get(rule_id)

    def is_rule_disabled(self, rule_id: str) -> bool:
        """Check if a rule is disabled."""
        return rule_id in self.disabled_rule_ids

    def disable_rules(self, rule_ids: set[str]) -> None:
        """Disable a set of rules by ID."""
        self.disabled_rule_ids |= rule_ids

    def enable_rules(self, rule_ids: set[str]) -> None:
        """Re-enable a set of rules by ID."""
        self.disabled_rule_ids -= rule_ids

    def get_rule_by_citation(self, citation: str) -> RuleConfig | None:
        """Look up a rule by its citation string."""
        if not hasattr(self, "_citation_index"):
            self._citation_index: dict[str, RuleConfig] = {}
            for rule in self._all_rules.values():
                if rule.citation:
                    self._citation_index[rule.citation] = rule
        return self._citation_index.get(citation)

    def resolve_cross_references(self) -> None:
        """Auto-populate cross_references by parsing source_quote text for citation patterns."""
        # Build citation -> rule_id index
        cit_to_id: dict[str, str] = {}
        for rule in self._all_rules.values():
            if rule.citation:
                cit_to_id[rule.citation] = rule.id

        # Patterns for FINRA 4210 cross-references in source text
        para_pattern = re.compile(
            r"paragraph\s+(\([a-zA-Z0-9.]+\)(?:\([a-zA-Z0-9.]+\))*)\s+(?:of\s+this\s+Rule)?",
            re.IGNORECASE,
        )
        rule_pattern = re.compile(
            r"(?:Rule\s+)?4210(\([a-zA-Z0-9.]+\)(?:\([a-zA-Z0-9.]+\))*)",
        )

        for rule in self._all_rules.values():
            if not rule.source_quote:
                continue

            existing_targets = {cr.target_citation for cr in rule.cross_references}

            for match in para_pattern.finditer(rule.source_quote):
                section_ref = match.group(1)
                target_cit = f"FINRA 4210{section_ref}"
                if target_cit == rule.citation or target_cit in existing_targets:
                    continue
                target_id = cit_to_id.get(target_cit, "")
                if target_cit not in existing_targets:
                    rule.cross_references.append(CrossReference(
                        text=match.group(0).strip(),
                        target_citation=target_cit,
                        target_rule_id=target_id,
                    ))
                    existing_targets.add(target_cit)

            for match in rule_pattern.finditer(rule.source_quote):
                section_ref = match.group(1)
                target_cit = f"FINRA 4210{section_ref}"
                if target_cit == rule.citation or target_cit in existing_targets:
                    continue
                target_id = cit_to_id.get(target_cit, "")
                rule.cross_references.append(CrossReference(
                    text=match.group(0).strip(),
                    target_citation=target_cit,
                    target_rule_id=target_id,
                ))
                existing_targets.add(target_cit)

    @property
    def total_rules(self) -> int:
        return len(self._all_rules)
