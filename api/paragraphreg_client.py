"""ParagraphReg client — fetches published rules for the paragraph-margin consumer."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests
import yaml

logger = logging.getLogger(__name__)

PARAGRAPHREG_URL: str = os.environ.get("PARAGRAPHREG_URL", "http://localhost:8001")

# ---------------------------------------------------------------------------
# FormulaConfig-compatible field names extracted from calculation sub-dict
# ---------------------------------------------------------------------------

_FORMULA_FIELDS: set[str] = {
    "type", "rate", "amount", "premium_pct", "underlying_pct",
    "minimum_underlying_pct", "minimum_per_contract", "multiplier",
    "floor_rate", "per_contract_minimum", "description",
    "otm_deduction", "calculation",
}

# Top-level rule_yaml fields preserved alongside the flattened formula
_TOP_LEVEL_FIELDS: set[str] = {
    "rule_id", "regulation", "section", "source_quote", "conditions", "description",
}


def translate_rule_to_formula(rule_data: dict) -> dict:
    """Translate a parsed ParagraphReg rule_yaml dict to FormulaConfig-flat keys.

    ParagraphReg stores calculation parameters in a nested ``calculation``
    sub-dict.  FormulaConfig expects those same parameters as flat top-level
    fields.  This function:

    1. Extracts fields from ``rule_data["calculation"]`` and maps them to
       FormulaConfig-compatible keys.
    2. Preserves selected top-level metadata fields (rule_id, regulation,
       section, source_quote, conditions, description).
    3. Returns a single flat dict ready for merging into waterfall entries.

    If ``rule_data`` has no ``calculation`` key the top-level metadata is
    still returned so enrichment is never lossy.
    """
    result: dict = {}

    # --- Top-level metadata ---
    for field in _TOP_LEVEL_FIELDS:
        if field in rule_data:
            result[field] = rule_data[field]

    # --- Flatten calculation sub-dict ---
    calc = rule_data.get("calculation")
    if isinstance(calc, dict):
        for key, value in calc.items():
            if key in _FORMULA_FIELDS:
                result[key] = value
        # If calculation has a "description" and the top-level also has one,
        # keep both: top-level as "description", calculation's as
        # "formula_description" to avoid silent overwrite.
        if "description" in calc and "description" in rule_data:
            result["formula_description"] = calc["description"]
            # The top-level description wins for the "description" key
            result["description"] = rule_data["description"]

    return result

# ---------------------------------------------------------------------------
# In-memory cache with TTL
# ---------------------------------------------------------------------------

_cache: dict[str, Any] | None = None
_cache_ts: float = 0.0
_CACHE_TTL: float = 300.0  # 5 minutes


def _cache_is_valid() -> bool:
    return _cache is not None and (time.monotonic() - _cache_ts) < _CACHE_TTL


def invalidate_cache() -> None:
    """Force next call to re-fetch from ParagraphReg."""
    global _cache, _cache_ts
    _cache = None
    _cache_ts = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_rules_for_consumer(consumer: str) -> dict:
    """Call GET {PARAGRAPHREG_URL}/api/v1/rules/by-consumer/{consumer}.

    Returns the JSON response as a dict, or an empty dict on failure.
    """
    url = f"{PARAGRAPHREG_URL}/api/v1/rules/by-consumer/{consumer}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.warning("ParagraphReg unreachable at %s: %s", url, exc)
        return {}


def get_rule_lookup() -> dict[str, dict]:
    """Return a dict keyed by rule_key with parsed rule data from ParagraphReg.

    Each rule in the ParagraphReg response has a ``rule_yaml`` field (a YAML
    string). We parse that string and key the result by ``rule_key``.

    Results are cached in memory for up to 5 minutes.  If ParagraphReg is
    unreachable, returns an empty dict (graceful degradation).
    """
    global _cache, _cache_ts

    if _cache_is_valid():
        return _cache  # type: ignore[return-value]

    # Fetch from all known consumers so enrichment covers 15c3 rules too
    _CONSUMERS = ("paragraph-margin", "paragraph-capital", "paragraph-segregation")
    rules_list: list[dict] = []
    for consumer in _CONSUMERS:
        data = fetch_rules_for_consumer(consumer)
        if data:
            for regulation in data.get("regulations", []):
                rules_list.extend(regulation.get("rules", []))

    if not rules_list:
        # Don't cache failures — retry on next call
        return {}
    lookup: dict[str, dict] = {}
    for entry in rules_list:
        rule_key = entry.get("rule_key")
        if not rule_key:
            continue
        # Parse the YAML content embedded in rule_yaml
        rule_yaml_str = entry.get("rule_yaml")
        if rule_yaml_str and isinstance(rule_yaml_str, str):
            try:
                parsed = yaml.safe_load(rule_yaml_str)
                if isinstance(parsed, dict):
                    lookup[rule_key] = translate_rule_to_formula(parsed)
                    continue
            except yaml.YAMLError as exc:
                logger.warning("Failed to parse rule_yaml for %s: %s", rule_key, exc)
        # Fall back to using the entry's top-level fields (minus internal ones)
        fallback = {k: v for k, v in entry.items() if k not in ("rule_yaml",)}
        if fallback:
            lookup[rule_key] = translate_rule_to_formula(fallback)

    _cache = lookup
    _cache_ts = time.monotonic()
    logger.info("ParagraphReg rule lookup cached: %d rules", len(lookup))
    return lookup
