"""Central registry of all loaded margin rules, organized by regulation."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

from paragraph_margin.rules.schema import CrossReference, FormulaConfig, RuleConfig, RuleSet
from paragraph_margin.rules.loader import load_rules_directory

logger = logging.getLogger(__name__)


def _parse_numeric(val: Any) -> float | None:
    """Convert a value to float, handling percentage strings like '40%' -> 0.40."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip()
        if val.endswith("%"):
            try:
                return float(val[:-1]) / 100.0
            except ValueError:
                return None
        try:
            return float(val)
        except ValueError:
            return None
    return None


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

    def load_from_paragraphmargin(
        self,
        template_name: str,
        *,
        fetch_fn: Callable[[str], list[dict]] | None = None,
    ) -> int:
        """Load rules from the ParagraphMargin API.

        Fetches the named waterfall template, extracts all rule/strategy
        entries from its sections, and converts them into RuleConfig objects.
        Rules are bucketed into the appropriate regulation list based on
        their rule_id prefix.

        Args:
            template_name: The waterfall template name to fetch.
            fetch_fn: Callable(template_name) -> list[dict].  If not provided,
                      attempts a lazy import of ``fetch_rule_configs`` from
                      ``src.clients.paragraphmargin_client`` (works when called
                      from within TPM at runtime).

        Returns the number of rules loaded (0 means nothing was loaded,
        caller should fall back to local YAML).
        """
        if fetch_fn is None:
            from src.clients.paragraphmargin_client import fetch_rule_configs
            fetch_fn = fetch_rule_configs

        entries = fetch_fn(template_name)
        if not entries:
            return 0

        count = 0
        for entry in entries:
            rule = self._api_entry_to_rule_config(entry)
            if rule is None:
                continue

            # Bucket by regulation prefix in the rule_id
            rid = rule.id
            if rid.startswith("4210_"):
                self.finra_4210_rules.append(rule)
            elif rid.startswith("reg_t_") or rid.startswith("220_"):
                self.reg_t_rules.append(rule)
            elif rid.startswith("house_"):
                self.house_rules.append(rule)
            elif rid.startswith("sho_") or rid.startswith("reg_sho_"):
                self.reg_sho_rules.append(rule)
            elif rid.startswith("15c3_"):
                self.sec_rules.append(rule)
            else:
                # Default to FINRA 4210 for unrecognised prefixes
                self.finra_4210_rules.append(rule)

            self._all_rules[rule.id] = rule
            count += 1

        if count:
            self.resolve_cross_references()
            logger.info(
                "Loaded %d rules from ParagraphMargin template '%s'",
                count,
                template_name,
            )
        return count

    @staticmethod
    def _api_entry_to_rule_config(entry: dict[str, Any]) -> RuleConfig | None:
        """Convert a ParagraphMargin waterfall entry dict to a RuleConfig.

        The waterfall entries have flat fields from the YAML plus enriched
        ParagraphReg formula fields (rate, amount, multiplier, etc.).
        We map these to the Pydantic models that the rest of the engine expects.
        """
        rule_id = entry.get("rule_id")
        if not rule_id:
            return None

        # --- Build FormulaConfig from flat enriched fields ---
        formula_type = (
            entry.get("type")
            or entry.get("formula_type")
            or "percentage_of_market_value"
        )
        formula_kwargs: dict[str, Any] = {"type": formula_type}
        # Map enriched ParagraphReg fields to FormulaConfig fields
        _FORMULA_FIELD_MAP = {
            "rate": "rate",
            "amount": "amount",
            "premium_pct": "premium_pct",
            "underlying_pct": "underlying_pct",
            "otm_deduction": "otm_deduction",
            "minimum_underlying_pct": "minimum_underlying_pct",
            "minimum_per_contract": "minimum_per_contract",
            "multiplier": "multiplier",
            "floor_rate": "floor_rate",
            "per_contract_minimum": "per_contract_minimum",
            "calculation": "calculation",
            # ParagraphMargin waterfall entries use finra_maintenance as the rate
            "finra_maintenance": "rate",
        }
        for src_key, dst_key in _FORMULA_FIELD_MAP.items():
            val = entry.get(src_key)
            if val is not None:
                # Don't overwrite rate if already set from enriched "rate"
                if dst_key == "rate" and "rate" in formula_kwargs and formula_kwargs["rate"]:
                    continue
                # Convert percentage strings like "40%" to 0.40
                if dst_key in ("rate", "amount", "premium_pct", "underlying_pct",
                               "minimum_underlying_pct", "minimum_per_contract",
                               "multiplier", "floor_rate", "per_contract_minimum"):
                    val = _parse_numeric(val)
                    if val is None:
                        continue
                formula_kwargs[dst_key] = val

        formula = FormulaConfig(**formula_kwargs)

        # --- Build conditions dict ---
        raw_conditions = entry.get("conditions", [])
        conditions: dict[str, Any] = {}
        if isinstance(raw_conditions, list):
            for cond in raw_conditions:
                if isinstance(cond, str) and "=" in cond:
                    k, _, v = cond.partition("=")
                    k, v = k.strip(), v.strip()
                    # Convert boolean-ish strings
                    if v.lower() == "true":
                        conditions[k] = True
                    elif v.lower() == "false":
                        conditions[k] = False
                    else:
                        conditions[k] = v
                elif isinstance(cond, dict):
                    conditions.update(cond)
        elif isinstance(raw_conditions, dict):
            conditions = raw_conditions

        # --- Description / source_quote ---
        description = entry.get("description") or entry.get("name") or ""
        source_quote = entry.get("source_quote") or entry.get("definition") or ""

        # --- Citation ---
        citation_section = entry.get("section") or ""
        citation = entry.get("citation") or ""
        if not citation and citation_section:
            regulation = entry.get("regulation") or ""
            # Build citation from regulation + section, e.g. "FINRA 4210(c)(6)"
            if "4210" in regulation or "FINRA" in regulation:
                # IM-4210-2 is already a full section ref; don't double-prefix
                if citation_section.startswith("IM-") or citation_section.startswith("4210"):
                    citation = f"FINRA {citation_section}"
                else:
                    citation = f"FINRA 4210{citation_section}"
            elif "220" in regulation or "reg_t" in regulation.lower():
                citation = f"Reg T 220{citation_section}"
            else:
                citation = citation_section

        # --- Auto-detect calculation_status ---
        calc_status = "active"
        produces_calc = True
        if formula.type.startswith("TODO_"):
            calc_status = "not_implemented"
            produces_calc = False
        elif formula.type == "informational":
            calc_status = "informational"
            produces_calc = False

        return RuleConfig(
            id=rule_id,
            description=description,
            citation=citation,
            conditions=conditions,
            formula=formula,
            source_quote=source_quote,
            produces_calculation=produces_calc,
            calculation_status=calc_status,
        )

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
