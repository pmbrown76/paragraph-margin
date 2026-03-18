"""ParagraphMargin — Rule Editor & Tester API."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from paragraph_margin import (
    MarginRulesRegistry,
    RuleConfig,
    FormulaConfig,
    MinimumConfig,
    evaluate_formula,
)
from api.paragraphreg_client import get_rule_lookup, translate_rule_to_formula, PARAGRAPHREG_URL

# ---------------------------------------------------------------------------
# Registry singleton
# ---------------------------------------------------------------------------

_registry = MarginRulesRegistry()
_rules_dir: Path | None = None

def _default_rules_dir() -> str:
    """Resolve the default margin rules directory.

    Checks in order:
    1. config/margin_rules/ relative to the repo root (containerized layout)
    2. ../Transaction Position Manager/config/margin_rules (local dev sibling layout)
    """
    repo_root = Path(__file__).resolve().parent.parent
    local = repo_root / "config" / "margin_rules"
    if local.is_dir():
        return str(local)
    sibling = repo_root.parent / "Transaction Position Manager" / "config" / "margin_rules"
    return str(sibling)


RULES_DIR_ENV = os.environ.get("MARGIN_RULES_DIR", _default_rules_dir())


def _load_rules(directory: str | None = None) -> dict:
    """(Re)load rules from YAML directory into the registry."""
    global _registry, _rules_dir
    _registry = MarginRulesRegistry()
    path = Path(directory) if directory else Path(RULES_DIR_ENV)
    if not path.is_dir():
        return {"loaded": False, "error": f"Directory not found: {path}", "total": 0}
    _rules_dir = path
    _registry.load_from_directory(path)
    return {"loaded": True, "directory": str(path), "total": _registry.total_rules}


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class FormulaUpdate(BaseModel):
    type: str | None = None
    rate: float | None = None
    amount: float | None = None
    premium_pct: float | None = None
    underlying_pct: float | None = None
    otm_deduction: bool | None = None
    minimum_underlying_pct: float | None = None
    minimum_per_contract: float | None = None
    multiplier: float | None = None
    floor_rate: float | None = None
    per_contract_minimum: float | None = None
    description: str | None = None


class MinimumUpdate(BaseModel):
    type: str | None = None
    amount: float | None = None


class RuleUpdate(BaseModel):
    formula: FormulaUpdate | None = None
    minimum: MinimumUpdate | None = None
    description: str | None = None
    conditions: dict[str, Any] | None = None
    produces_calculation: bool | None = None


class TestRequest(BaseModel):
    rule_id: str | None = None
    formula: FormulaUpdate | None = None
    context: dict[str, Any]


class ReloadRequest(BaseModel):
    directory: str | None = None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="ParagraphMargin", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
    _load_rules()


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "paragraph-margin", "total_rules": _registry.total_rules}


_ASSET_CLASS_LABELS: dict[str, str] = {
    "equity": "Equity",
    "option": "Option",
    "corporate_bond": "Corporate Bond",
    "bond": "Bond",
    "municipal_bond": "Municipal Bond",
    "us_treasury": "US Treasury",
    "agency_debt": "Agency Debt",
    "etf": "ETF",
    "etp": "ETP",
    "security_future": "Security Future",
    "money_market_fund": "Money Market Fund",
    "exempt_fund": "Exempt Fund",
}


def _extract_asset_class(rule: RuleConfig) -> str:
    """Derive human-readable asset class from conditions.security_type."""
    st = rule.conditions.get("security_type", "")
    if not st or not isinstance(st, str):
        return ""
    return _ASSET_CLASS_LABELS.get(st, "")


def _rule_to_dict(rule: RuleConfig, regulation: str = "") -> dict:
    """Serialize a RuleConfig to a JSON-friendly dict."""
    d = {
        "id": rule.id,
        "description": rule.description,
        "citation": rule.citation,
        "conditions": rule.conditions,
        "asset_class": _extract_asset_class(rule),
        "produces_calculation": rule.produces_calculation,
        "calculation_status": rule.calculation_status,
        "notes": rule.notes,
        "source_quote": rule.source_quote,
        "type": rule.type,
        "rule_category": rule.rule_category,
        "rule_group": rule.rule_group,
        "regulation": regulation,
    }
    if rule.formula:
        d["formula"] = {
            "type": rule.formula.type,
            "rate": rule.formula.rate,
            "amount": rule.formula.amount,
            "premium_pct": rule.formula.premium_pct,
            "underlying_pct": rule.formula.underlying_pct,
            "otm_deduction": rule.formula.otm_deduction,
            "minimum_underlying_pct": rule.formula.minimum_underlying_pct,
            "minimum_per_contract": rule.formula.minimum_per_contract,
            "multiplier": rule.formula.multiplier,
            "floor_rate": rule.formula.floor_rate,
            "per_contract_minimum": rule.formula.per_contract_minimum,
            "calculation": rule.formula.calculation,
            "description": rule.formula.description,
        }
    else:
        d["formula"] = None
    if rule.minimum:
        d["minimum"] = {"type": rule.minimum.type, "amount": rule.minimum.amount}
    else:
        d["minimum"] = None
    return d


def _get_regulation_for_rule(rule_id: str) -> str:
    """Determine which regulation a rule belongs to."""
    for reg, rules in [
        ("reg_t", _registry.reg_t_rules),
        ("finra_4210", _registry.finra_4210_rules),
        ("house", _registry.house_rules),
        ("reg_sho", _registry.reg_sho_rules),
        ("finra_reporting", _registry.finra_reporting_rules),
        ("sec", _registry.sec_rules),
    ]:
        for r in rules:
            if r.id == rule_id:
                return reg
    return ""


# --- Rules CRUD ---

@app.get("/api/rules")
def list_rules(regulation: str | None = None, formula_type: str | None = None, q: str | None = None):
    """List all rules, optionally filtered."""
    reg_map = {
        "reg_t": _registry.reg_t_rules,
        "finra_4210": _registry.finra_4210_rules,
        "house": _registry.house_rules,
        "reg_sho": _registry.reg_sho_rules,
        "finra_reporting": _registry.finra_reporting_rules,
        "sec": _registry.sec_rules,
    }
    results = []
    for reg_name, rule_list in reg_map.items():
        if regulation and reg_name != regulation:
            continue
        for rule in rule_list:
            if formula_type and (not rule.formula or rule.formula.type != formula_type):
                continue
            if q:
                q_lower = q.lower()
                searchable = f"{rule.id} {rule.description} {rule.citation}".lower()
                if q_lower not in searchable:
                    continue
            results.append(_rule_to_dict(rule, reg_name))
    return {"rules": results, "total": len(results)}


@app.get("/api/rules/{rule_id}")
def get_rule(rule_id: str):
    """Get a single rule by ID."""
    rule = _registry.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    regulation = _get_regulation_for_rule(rule_id)
    return _rule_to_dict(rule, regulation)


@app.put("/api/rules/{rule_id}")
def update_rule(rule_id: str, body: RuleUpdate):
    """Update a rule's formula, minimum, conditions, or description."""
    rule = _registry.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")

    if body.description is not None:
        rule.description = body.description
    if body.produces_calculation is not None:
        rule.produces_calculation = body.produces_calculation
    if body.conditions is not None:
        rule.conditions = body.conditions

    if body.formula is not None:
        if rule.formula is None:
            rule.formula = FormulaConfig(type=body.formula.type or "percentage_of_market_value")
        updates = body.formula.model_dump(exclude_none=True)
        for k, v in updates.items():
            setattr(rule.formula, k, v)

    if body.minimum is not None:
        if rule.minimum is None:
            rule.minimum = MinimumConfig()
        updates = body.minimum.model_dump(exclude_none=True)
        for k, v in updates.items():
            setattr(rule.minimum, k, v)

    regulation = _get_regulation_for_rule(rule_id)
    return _rule_to_dict(rule, regulation)


# --- Formula tester ---

@app.post("/api/test")
def test_formula(body: TestRequest):
    """Test a formula against a position context.

    Supply either rule_id (to test an existing rule) or formula (ad-hoc).
    """
    # Build context with Decimals
    ctx: dict[str, Any] = {}
    for k, v in body.context.items():
        try:
            ctx[k] = Decimal(str(v))
        except Exception:
            ctx[k] = v

    if body.rule_id:
        rule = _registry.get_rule(body.rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail=f"Rule '{body.rule_id}' not found")
    elif body.formula:
        formula_dict = body.formula.model_dump(exclude_none=True)
        formula_dict.setdefault("type", "percentage_of_market_value")
        rule = RuleConfig(id="_test", formula=FormulaConfig(**formula_dict))
    else:
        raise HTTPException(status_code=400, detail="Provide rule_id or formula")

    try:
        margin = evaluate_formula(rule, ctx)
        return {
            "margin": str(margin),
            "margin_float": float(margin),
            "rule_id": rule.id,
            "formula_type": rule.formula.type if rule.formula else None,
            "context_used": {k: str(v) for k, v in ctx.items()},
        }
    except Exception as e:
        return {
            "margin": None,
            "error": str(e),
            "rule_id": rule.id,
            "formula_type": rule.formula.type if rule.formula else None,
        }


# --- Registry management ---

@app.get("/api/stats")
def registry_stats():
    """Get registry statistics."""
    formula_types: dict[str, int] = {}
    all_rules = (
        _registry.reg_t_rules + _registry.finra_4210_rules + _registry.house_rules
        + _registry.reg_sho_rules + _registry.finra_reporting_rules + _registry.sec_rules
    )
    for r in all_rules:
        ft = r.formula.type if r.formula else "none"
        formula_types[ft] = formula_types.get(ft, 0) + 1

    return {
        "total": _registry.total_rules,
        "rules_dir": str(_rules_dir) if _rules_dir else None,
        "by_regulation": {
            "reg_t": len(_registry.reg_t_rules),
            "finra_4210": len(_registry.finra_4210_rules),
            "house": len(_registry.house_rules),
            "reg_sho": len(_registry.reg_sho_rules),
            "finra_reporting": len(_registry.finra_reporting_rules),
            "sec": len(_registry.sec_rules),
        },
        "by_formula_type": dict(sorted(formula_types.items(), key=lambda x: -x[1])),
        "disabled_count": len(_registry.disabled_rule_ids),
    }


@app.post("/api/reload")
def reload_rules(body: ReloadRequest | None = None):
    """Reload rules from YAML directory."""
    directory = body.directory if body else None
    return _load_rules(directory)


# --- ParagraphReg enrichment ---

def _enrich_waterfall(data: dict) -> dict:
    """Merge ParagraphReg rule data into a waterfall dict.

    For each rule/strategy entry in each category, if the entry's ``rule_id``
    exists in the ParagraphReg lookup, merge the pre-translated ParagraphReg
    fields into the entry.  The lookup values have already been run through
    ``translate_rule_to_formula()`` by ``get_rule_lookup()``, so the merged
    keys are FormulaConfig-compatible (type, rate, per_contract_minimum, etc.)
    rather than nested under a ``calculation`` sub-dict.

    Returns a new dict with ``_meta`` metadata indicating the data source.
    """
    lookup = get_rule_lookup()
    enriched_count = 0
    categories = data.get("categories", [])

    if lookup:
        for category in categories:
            # Waterfall YAMLs use either "rules" or "strategies" as the list key
            for list_key in ("rules", "strategies"):
                entries = category.get(list_key, [])
                for entry in entries:
                    rid = entry.get("rule_id")
                    if rid and rid in lookup:
                        translated = lookup[rid]
                        # Merge: translated ParagraphReg fields supplement/override YAML.
                        # Fields are already flat and FormulaConfig-compatible.
                        for k, v in translated.items():
                            entry[k] = v
                        enriched_count += 1

    source = "paragraphreg" if lookup else "local_yaml"
    data["_meta"] = {
        "source": source,
        "paragraphreg_rules_loaded": len(lookup),
        "paragraphreg_rules_enriched": enriched_count,
        "paragraphreg_url": PARAGRAPHREG_URL,
    }
    return data


# --- Option strategy waterfall ---

@app.get("/api/option-strategy-waterfall")
def option_strategy_waterfall():
    """Return the option strategy margin recognition waterfall."""
    import yaml as _yaml
    waterfall_path = Path(__file__).parent.parent / "data" / "option_strategy_waterfall.yaml"
    if not waterfall_path.exists():
        return {"categories": [], "_meta": {"source": "local_yaml", "paragraphreg_rules_loaded": 0, "paragraphreg_rules_enriched": 0, "paragraphreg_url": PARAGRAPHREG_URL}}
    with open(waterfall_path) as f:
        data = _yaml.safe_load(f)
    return _enrich_waterfall(data)


# --- Asset class waterfalls ---

WATERFALL_FILES = {
    "equity": "equity_margin_waterfall.yaml",
    "fixed-income": "fixed_income_margin_waterfall.yaml",
    "etf": "etf_margin_waterfall.yaml",
    "concentrated": "concentrated_margin_waterfall.yaml",
    "day-trading": "day_trading_margin_waterfall.yaml",
    "portfolio-margin": "portfolio_margin_waterfall.yaml",
    "reg-t-equity": "reg_t_equity_margin_waterfall.yaml",
    "reg-t-fixed-income": "reg_t_fixed_income_margin_waterfall.yaml",
    "reg-t-options": "reg_t_options_margin_waterfall.yaml",
    "reg-t-special-accounts": "reg_t_special_accounts_waterfall.yaml",
    "sec-15c3-1": "15c3_1_net_capital_waterfall.yaml",
    "sec-15c3-3": "15c3_3_customer_protection_waterfall.yaml",
}


@app.get("/api/waterfall")
def waterfall_index():
    """Return the list of available asset class waterfalls."""
    import yaml as _yaml
    data_dir = Path(__file__).parent.parent / "data"
    waterfalls = []
    for key, filename in WATERFALL_FILES.items():
        path = data_dir / filename
        info = {"asset_class": key, "filename": filename, "exists": path.exists()}
        if path.exists():
            with open(path) as f:
                data = _yaml.safe_load(f) or {}
            categories = data.get("categories", [])
            info["categories"] = len(categories)
            info["total_rules"] = sum(len(c.get("rules", [])) for c in categories)
        waterfalls.append(info)
    return {"waterfalls": waterfalls}


@app.get("/api/waterfall/{asset_class}")
def asset_class_waterfall(asset_class: str):
    """Return the margin waterfall for a specific asset class."""
    import yaml as _yaml
    filename = WATERFALL_FILES.get(asset_class)
    if not filename:
        raise HTTPException(status_code=404, detail=f"Unknown asset class: {asset_class}")
    waterfall_path = Path(__file__).parent.parent / "data" / filename
    if not waterfall_path.exists():
        return {"categories": [], "_meta": {"source": "local_yaml", "paragraphreg_rules_loaded": 0, "paragraphreg_rules_enriched": 0, "paragraphreg_url": PARAGRAPHREG_URL}}
    with open(waterfall_path) as f:
        data = _yaml.safe_load(f)
    return _enrich_waterfall(data)


# --- Regulatory timeline ---

@app.get("/api/regulatory-timeline")
def regulatory_timeline():
    """Return the full regulatory timeline data."""
    import yaml as _yaml
    timeline_path = Path(__file__).parent.parent / "data" / "regulatory_timeline.yaml"
    if not timeline_path.exists():
        return {"sections": {}, "cross_cutting_amendments": [], "reference_sources": []}
    with open(timeline_path) as f:
        data = _yaml.safe_load(f)
    return data


@app.get("/api/regulatory-timeline/reg-t")
def reg_t_regulatory_timeline():
    """Return the full Reg T regulatory timeline data."""
    import yaml as _yaml
    timeline_path = Path(__file__).parent.parent / "data" / "reg_t_regulatory_timeline.yaml"
    if not timeline_path.exists():
        return {"sections": {}, "cross_cutting_amendments": [], "reference_sources": []}
    with open(timeline_path) as f:
        data = _yaml.safe_load(f)
    return data


@app.get("/api/regulatory-timeline/15c3-1")
def sec_15c3_1_regulatory_timeline():
    """Return the full SEC 15c3-1 (Net Capital) regulatory timeline data."""
    import yaml as _yaml
    timeline_path = Path(__file__).parent.parent / "data" / "15c3_1_regulatory_timeline.yaml"
    if not timeline_path.exists():
        return {"sections": {}, "cross_cutting_amendments": [], "reference_sources": []}
    with open(timeline_path) as f:
        data = _yaml.safe_load(f)
    return data


@app.get("/api/regulatory-timeline/15c3-3")
def sec_15c3_3_regulatory_timeline():
    """Return the full SEC 15c3-3 (Customer Protection) regulatory timeline data."""
    import yaml as _yaml
    timeline_path = Path(__file__).parent.parent / "data" / "15c3_3_regulatory_timeline.yaml"
    if not timeline_path.exists():
        return {"sections": {}, "cross_cutting_amendments": [], "reference_sources": []}
    with open(timeline_path) as f:
        data = _yaml.safe_load(f)
    return data


def _resolve_timeline_section(section: str) -> dict:
    """Resolve a section citation to timeline data.

    Routes sections to the appropriate timeline file based on prefix:
    - 220.x / Reg T → Reg T timeline
    - 15c3-1 → SEC 15c3-1 (Net Capital) timeline
    - 15c3-3 / Exhibit A → SEC 15c3-3 (Customer Protection) timeline
    - Otherwise → FINRA 4210 timeline
    """
    import yaml as _yaml
    data_dir = Path(__file__).parent.parent / "data"

    # Determine which timeline file to use
    stripped = section.strip()
    if stripped.startswith("220.") or stripped.startswith("Reg T "):
        timeline_path = data_dir / "reg_t_regulatory_timeline.yaml"
    elif stripped.startswith("15c3-1"):
        timeline_path = data_dir / "15c3_1_regulatory_timeline.yaml"
    elif stripped.startswith("15c3-3") or stripped.startswith("Exhibit A"):
        timeline_path = data_dir / "15c3_3_regulatory_timeline.yaml"
    else:
        timeline_path = data_dir / "regulatory_timeline.yaml"

    if not timeline_path.exists():
        return {}
    with open(timeline_path) as f:
        data = _yaml.safe_load(f)
    return data


@app.get("/api/regulatory-timeline/{section:path}")
def regulatory_timeline_section(section: str):
    """Return timeline for a specific section.

    Routes sections to the appropriate timeline:
    - 220.x → Reg T
    - 15c3-1 → SEC 15c3-1 (Net Capital)
    - 15c3-3 / Exhibit A → SEC 15c3-3 (Customer Protection)
    - Others → FINRA 4210
    Handles compound sections like '4210(f)(2)(H)(i) + (E)' by trying
    the primary section, then walking up the hierarchy.
    """
    data = _resolve_timeline_section(section)
    if not data:
        raise HTTPException(status_code=404, detail="Timeline data not found")
    sections = data.get("sections", {})

    # Try exact match, then primary part of compound citations, then parent sections
    candidates = [section]
    if " + " in section or " / " in section:
        candidates.append(section.split(" + ")[0].split(" / ")[0].strip())
    # Walk up: 4210(f)(2)(H)(v)(b) -> 4210(f)(2)(H)(v) -> 4210(f)(2)(H) -> ...
    base = candidates[-1]
    while "(" in base:
        base = base.rsplit("(", 1)[0].rstrip()
        if base:
            candidates.append(base + ")")
            candidates.append(base.rstrip(")"))

    matched_key = None
    for c in candidates:
        if c in sections:
            matched_key = c
            break

    if matched_key is None:
        raise HTTPException(status_code=404, detail=f"Section '{section}' not found")
    return {
        "section": section,
        "matched_section": matched_key,
        **sections[matched_key],
        "cross_cutting_amendments": data.get("cross_cutting_amendments", []),
        "reference_sources": data.get("reference_sources", []),
    }


# --- Waterfall templates (for TPM) ---

WATERFALL_TEMPLATES: dict[str, dict[str, Any]] = {
    "finra_4210_standard": {
        "description": "FINRA Rule 4210 — full margin waterfall (equity, fixed-income, ETF, concentrated, day-trading, option strategies)",
        "regulation": "FINRA 4210",
        "sections": {
            "equity": "equity_margin_waterfall.yaml",
            "fixed_income": "fixed_income_margin_waterfall.yaml",
            "etf": "etf_margin_waterfall.yaml",
            "concentrated": "concentrated_margin_waterfall.yaml",
            "day_trading": "day_trading_margin_waterfall.yaml",
            "option_strategies": "option_strategy_waterfall.yaml",
        },
    },
    "reg_t_standard": {
        "description": "Regulation T — initial margin waterfalls (equity, fixed-income, options, special accounts)",
        "regulation": "Reg T (12 CFR 220)",
        "sections": {
            "equity": "reg_t_equity_margin_waterfall.yaml",
            "fixed_income": "reg_t_fixed_income_margin_waterfall.yaml",
            "options": "reg_t_options_margin_waterfall.yaml",
            "special_accounts": "reg_t_special_accounts_waterfall.yaml",
        },
    },
    "portfolio_margin": {
        "description": "FINRA 4210(g) — portfolio margin waterfall",
        "regulation": "FINRA 4210(g)",
        "sections": {
            "portfolio_margin": "portfolio_margin_waterfall.yaml",
        },
    },
    "sec_15c3_1": {
        "description": "SEC Rule 15c3-1 — net capital requirement waterfall",
        "regulation": "SEC 15c3-1",
        "sections": {
            "net_capital": "15c3_1_net_capital_waterfall.yaml",
        },
    },
    "sec_15c3_3": {
        "description": "SEC Rule 15c3-3 — customer protection waterfall",
        "regulation": "SEC 15c3-3",
        "sections": {
            "customer_protection": "15c3_3_customer_protection_waterfall.yaml",
        },
    },
}


@app.get("/api/waterfall-templates")
def list_waterfall_templates():
    """List all available waterfall template names with metadata."""
    templates = []
    for name, tmpl in WATERFALL_TEMPLATES.items():
        templates.append({
            "template_name": name,
            "description": tmpl["description"],
            "regulation": tmpl["regulation"],
            "section_keys": list(tmpl["sections"].keys()),
        })
    return {"templates": templates, "total": len(templates)}


@app.get("/api/waterfall-template/{template_name}")
def get_waterfall_template(template_name: str):
    """Return a named waterfall template with all sections loaded and enriched.

    TPM client configs reference templates like "finra_4210_standard".
    This endpoint resolves the template to its constituent waterfall YAML
    files, enriches each via ParagraphReg, and returns a combined payload.
    """
    import yaml as _yaml

    tmpl = WATERFALL_TEMPLATES.get(template_name)
    if tmpl is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown template: '{template_name}'. Available: {list(WATERFALL_TEMPLATES.keys())}",
        )

    data_dir = Path(__file__).parent.parent / "data"
    sections: dict[str, Any] = {}
    all_rule_ids: list[str] = []

    for section_key, filename in tmpl["sections"].items():
        path = data_dir / filename
        if not path.exists():
            sections[section_key] = {"categories": [], "_error": f"File not found: {filename}"}
            continue
        with open(path) as f:
            section_data = _yaml.safe_load(f) or {}
        section_data = _enrich_waterfall(section_data)

        # Collect all rule_ids from this section
        for category in section_data.get("categories", []):
            for list_key in ("rules", "strategies"):
                for entry in category.get(list_key, []):
                    rid = entry.get("rule_id")
                    if rid and rid not in all_rule_ids:
                        all_rule_ids.append(rid)

        sections[section_key] = section_data

    return {
        "template_name": template_name,
        "description": tmpl["description"],
        "regulation": tmpl["regulation"],
        "sections": sections,
        "rule_ids": all_rule_ids,
    }


# --- SPA fallback ---

_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"

if _frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        file_path = _frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_frontend_dist / "index.html")
