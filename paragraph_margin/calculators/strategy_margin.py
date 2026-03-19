"""Strategy margin calculator — computes Reg T and FINRA 4210 margin for multi-leg strategies.

Strategy margins are now driven by YAML rules (options_spreads_strategies.yaml) via the
rule engine formula evaluator. Each strategy type builds a context dict with strategy-specific
fields (net_debit, strike_width, naked margins, etc.) and evaluates the matching YAML rule.

This ensures full traceability: every margin number traces to a specific rule ID with
verbatim FINRA source text.
"""

from decimal import Decimal
from typing import Callable

from paragraph_margin.models.enums import StrategyType
from paragraph_margin.models.margin import MarginRequirement
from paragraph_margin.models.positions import Position
from paragraph_margin.models.securities import Option
from paragraph_margin.models.strategies import RecognizedStrategy, StrategyLeg
from paragraph_margin.calculators.finra_4210 import FINRA4210Calculator
from paragraph_margin.calculators.reg_t import RegTCalculator
from paragraph_margin.engine.evaluator import evaluate_formula
from paragraph_margin.engine.matcher import find_matching_rules
from paragraph_margin.rules.registry import MarginRulesRegistry
from paragraph_margin.rules.schema import RuleConfig
from paragraph_margin.money import ZERO, max_of, pct, round_margin, to_decimal


class StrategyMarginCalculator:
    """Calculates margin requirements for recognized multi-leg strategies."""

    def __init__(self, registry: MarginRulesRegistry) -> None:
        self._registry = registry
        self._reg_t = RegTCalculator(registry)
        self._finra = FINRA4210Calculator(registry)

    def calculate(
        self,
        strategy: RecognizedStrategy,
        underlying_price: Decimal = ZERO,
    ) -> MarginRequirement:
        """Calculate margin for a recognized strategy."""
        calc_fn = _STRATEGY_CALCULATORS.get(strategy.strategy_type)
        if calc_fn is None:
            return MarginRequirement(
                position_id=strategy.strategy_id,
                strategy_id=strategy.strategy_id,
                calculation_detail=f"No margin formula for strategy: {strategy.strategy_type}",
            )

        reg_t, finra, detail, rule_ids, citations = calc_fn(self, strategy, underlying_price)

        return MarginRequirement(
            position_id=strategy.strategy_id,
            strategy_id=strategy.strategy_id,
            reg_t_initial=round_margin(reg_t),
            finra_4210_maintenance=round_margin(finra),
            rule_ids=rule_ids,
            citations=citations,
            calculation_detail=detail,
        )

    def _find_strategy_rule(self, strategy_type: str) -> RuleConfig | None:
        """Find the YAML rule matching a strategy type."""
        ctx = {"security_type": "option", "strategy_type": strategy_type}
        matching = find_matching_rules(self._registry.finra_4210_rules, ctx, self._registry.disabled_rule_ids)
        # Return the first rule that produces a calculation
        for rule in matching:
            if rule.produces_calculation and rule.calculation_status == "active":
                return rule
        return matching[0] if matching else None

    # ================================================================
    # Naked (Uncovered) Options
    # ================================================================

    def _calc_naked_call(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Naked call per FINRA 4210(f)(2)(E)(i): delegates to per-position calculator.
        Reg T defers to SRO for listed options, so reg_t == finra."""
        short_leg = _find_leg(strategy, "short_call")
        req = self._finra.calculate(short_leg.position, underlying_price)
        finra = req.finra_4210_maintenance
        detail = (
            f"Naked call\n"
            f"Delegated to per-position FINRA 4210 calculator\n"
            f"{req.calculation_detail}\n"
            f"Margin = ${finra}"
        )
        rule_ids = req.rule_ids or ["4210_f_2_E_i"]
        citations = req.citations or ["FINRA 4210(f)(2)(E)(i)"]
        citations.append("Reg T 220.12(c)")
        return finra, finra, detail, rule_ids, citations

    def _calc_naked_put(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Naked put per FINRA 4210(f)(2)(E)(i): delegates to per-position calculator.
        Reg T defers to SRO for listed options, so reg_t == finra."""
        short_leg = _find_leg(strategy, "short_put")
        req = self._finra.calculate(short_leg.position, underlying_price)
        finra = req.finra_4210_maintenance
        detail = (
            f"Naked put\n"
            f"Delegated to per-position FINRA 4210 calculator\n"
            f"{req.calculation_detail}\n"
            f"Margin = ${finra}"
        )
        rule_ids = req.rule_ids or ["4210_f_2_E_i"]
        citations = req.citations or ["FINRA 4210(f)(2)(E)(i)"]
        citations.append("Reg T 220.12(c)")
        return finra, finra, detail, rule_ids, citations

    # ================================================================
    # Vertical Spreads
    # ================================================================

    def _calc_bull_call_spread(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Bull call spread (debit): margin = min(net debit, strike width)."""
        long_leg = _find_leg(strategy, "long_call")
        short_leg = _find_leg(strategy, "short_call")
        net_debit = _net_debit_from_legs(long_leg, short_leg)
        strike_width = abs(short_leg.position.security.strike - long_leg.position.security.strike)
        multiplier = _multiplier(short_leg)
        qty = short_leg.position.quantity
        strike_diff = strike_width * to_decimal(multiplier) * qty

        # Max loss cannot exceed strike width
        max_loss = min(net_debit, strike_diff)

        rule = self._find_strategy_rule("debit_spread")
        rule_ids, citations = _rule_trace(rule)

        context = {"net_debit": max_loss}
        margin = evaluate_formula(rule, context) if rule else max_loss

        detail = (
            f"Bull call spread\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = min(net debit, strike width) per 4210(f)(2)(H)(i)(b.)\n"
            f"Strikes: long {_strike(long_leg)} / short {_strike(short_leg)}\n"
            f"Strike width: ${strike_width} x {multiplier} x {qty} = ${strike_diff}\n"
            f"Net debit = ${net_debit}\n"
            f"Max loss = min(${net_debit}, ${strike_diff}) = ${max_loss}\n"
            f"Margin = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    def _calc_bear_call_spread(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Bear call spread (credit): margin = strike width - net credit."""
        long_leg = _find_leg(strategy, "long_call")
        short_leg = _find_leg(strategy, "short_call")

        rule = self._find_strategy_rule("credit_spread")
        rule_ids, citations = _rule_trace(rule)

        strike_width = abs(short_leg.position.security.strike - long_leg.position.security.strike)
        qty = short_leg.position.quantity
        multiplier = _multiplier(short_leg)
        net_credit = _leg_market_value(short_leg) - _leg_market_value(long_leg)

        context = {
            "strike_width": strike_width,
            "contract_multiplier": multiplier,
            "contracts": qty,
            "net_credit": net_credit,
        }
        margin = evaluate_formula(rule, context) if rule else _credit_spread_margin(short_leg, long_leg)

        detail = (
            f"Bear call spread\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = (strike width x {multiplier}) - net credit\n"
            f"Strikes: short {_strike(short_leg)} / long {_strike(long_leg)}\n"
            f"Strike width: ${strike_width} x {multiplier} x {qty} = ${strike_width * to_decimal(multiplier) * qty}\n"
            f"Net credit: ${max_of(net_credit, ZERO)}\n"
            f"Margin = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    def _calc_bull_put_spread(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Bull put spread (credit): margin = strike width - net credit."""
        long_leg = _find_leg(strategy, "long_put")
        short_leg = _find_leg(strategy, "short_put")

        rule = self._find_strategy_rule("credit_spread")
        rule_ids, citations = _rule_trace(rule)

        strike_width = abs(short_leg.position.security.strike - long_leg.position.security.strike)
        qty = short_leg.position.quantity
        multiplier = _multiplier(short_leg)
        net_credit = _leg_market_value(short_leg) - _leg_market_value(long_leg)

        context = {
            "strike_width": strike_width,
            "contract_multiplier": multiplier,
            "contracts": qty,
            "net_credit": net_credit,
        }
        margin = evaluate_formula(rule, context) if rule else _credit_spread_margin(short_leg, long_leg)

        detail = (
            f"Bull put spread\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = (strike width x {multiplier}) - net credit\n"
            f"Strikes: long {_strike(long_leg)} / short {_strike(short_leg)}\n"
            f"Margin = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    def _calc_bear_put_spread(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Bear put spread (debit): margin = min(net debit, strike width)."""
        long_leg = _find_leg(strategy, "long_put")
        short_leg = _find_leg(strategy, "short_put")
        net_debit = _net_debit_from_legs(long_leg, short_leg)
        strike_width = abs(long_leg.position.security.strike - short_leg.position.security.strike)
        multiplier = _multiplier(short_leg)
        qty = short_leg.position.quantity
        strike_diff = strike_width * to_decimal(multiplier) * qty

        # Max loss cannot exceed strike width
        max_loss = min(net_debit, strike_diff)

        rule = self._find_strategy_rule("debit_spread")
        rule_ids, citations = _rule_trace(rule)

        context = {"net_debit": max_loss}
        margin = evaluate_formula(rule, context) if rule else max_loss

        detail = (
            f"Bear put spread\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = min(net debit, strike width) per 4210(f)(2)(H)(i)(b.)\n"
            f"Strikes: long {_strike(long_leg)} / short {_strike(short_leg)}\n"
            f"Strike width: ${strike_width} x {multiplier} x {qty} = ${strike_diff}\n"
            f"Net debit = ${net_debit}\n"
            f"Max loss = min(${net_debit}, ${strike_diff}) = ${max_loss}\n"
            f"Margin = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    # ================================================================
    # Straddles & Strangles
    # ================================================================

    def _calc_long_straddle(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Long straddle: no margin required — long options must be paid in full."""
        total = _total_premium_paid(strategy)

        rule = self._find_strategy_rule("long_options")
        rule_ids, citations = _rule_trace(rule)

        detail = (
            f"Long straddle\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Long options paid in full — no margin requirement\n"
            f"Total premium paid = ${total}\n"
            f"Margin = $0"
        )
        return ZERO, ZERO, detail, rule_ids, citations

    def _calc_short_straddle(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Short straddle: MAX(naked call margin, naked put margin) + other premium."""
        call_leg = _find_leg(strategy, "short_call")
        put_leg = _find_leg(strategy, "short_put")
        return self._calc_short_vol_strategy(
            call_leg, put_leg, underlying_price, "Short straddle"
        )

    def _calc_long_strangle(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Long strangle: no margin required — long options must be paid in full."""
        total = _total_premium_paid(strategy)

        rule = self._find_strategy_rule("long_options")
        rule_ids, citations = _rule_trace(rule)

        detail = (
            f"Long strangle\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Long options paid in full — no margin requirement\n"
            f"Total premium paid = ${total}\n"
            f"Margin = $0"
        )
        return ZERO, ZERO, detail, rule_ids, citations

    def _calc_short_strangle(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Short strangle: MAX(naked call margin, naked put margin) + other premium."""
        call_leg = _find_leg(strategy, "short_call")
        put_leg = _find_leg(strategy, "short_put")
        return self._calc_short_vol_strategy(
            call_leg, put_leg, underlying_price, "Short strangle"
        )

    def _calc_short_vol_strategy(
        self,
        call_leg: StrategyLeg,
        put_leg: StrategyLeg,
        underlying_price: Decimal,
        name: str,
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Common calc for short straddle/strangle."""
        call_req = self._finra.calculate(call_leg.position, underlying_price)
        put_req = self._finra.calculate(put_leg.position, underlying_price)

        call_margin = call_req.finra_4210_maintenance
        put_margin = put_req.finra_4210_maintenance
        call_premium = abs(call_leg.position.market_value)
        put_premium = abs(put_leg.position.market_value)

        rule = self._find_strategy_rule("short_vol")
        rule_ids, citations = _rule_trace(rule)
        # Include the naked option rule IDs for full traceability
        rule_ids.extend(call_req.rule_ids)
        rule_ids.extend(put_req.rule_ids)

        context = {
            "naked_call_margin": call_margin,
            "naked_put_margin": put_margin,
            "call_premium": call_premium,
            "put_premium": put_premium,
        }
        finra = evaluate_formula(rule, context) if rule else (
            call_margin + put_premium if call_margin >= put_margin else put_margin + call_premium
        )

        if call_margin >= put_margin:
            detail_side = "call side dominant"
        else:
            detail_side = "put side dominant"

        detail = (
            f"{name}\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = max(naked call margin, naked put margin) + other side premium\n"
            f"Naked call margin: ${call_margin}\n"
            f"Naked put margin: ${put_margin}\n"
            f"Dominant side: {detail_side}\n"
            f"Call premium: ${call_premium}, Put premium: ${put_premium}\n"
            f"Margin = ${finra}"
        )
        return finra, finra, detail, rule_ids, citations

    # ================================================================
    # Iron Condor & Iron Butterfly
    # ================================================================

    def _calc_iron_condor(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Iron condor: treated as two credit spreads, margin = greater of the two.

        Each spread margin = spread_width - net_credit_for_that_spread.
        Per FINRA 4210(f)(2)(H), margin is the greater, not the sum.
        """
        lp = _find_leg(strategy, "long_put")
        sp = _find_leg(strategy, "short_put")
        sc = _find_leg(strategy, "short_call")
        lc = _find_leg(strategy, "long_call")

        qty = lp.position.quantity
        multiplier = _multiplier(lp)

        put_width = (sp.position.security.strike - lp.position.security.strike) * multiplier * qty
        call_width = (lc.position.security.strike - sc.position.security.strike) * multiplier * qty

        # Each spread's net credit is computed independently
        put_net_credit = _leg_market_value(sp) - _leg_market_value(lp)
        call_net_credit = _leg_market_value(sc) - _leg_market_value(lc)

        put_margin = max_of(put_width - max_of(put_net_credit, ZERO), ZERO)
        call_margin = max_of(call_width - max_of(call_net_credit, ZERO), ZERO)
        margin = max_of(put_margin, call_margin)

        rule = self._find_strategy_rule("iron_condor")
        rule_ids, citations = _rule_trace(rule)

        detail = (
            f"Iron condor\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = max(put spread margin, call spread margin)\n"
            f"Put spread: ({_strike(sp)} - {_strike(lp)}) x {multiplier} x {qty} = ${put_width}\n"
            f"Put net credit: ${put_net_credit}, Put margin: ${put_margin}\n"
            f"Call spread: ({_strike(lc)} - {_strike(sc)}) x {multiplier} x {qty} = ${call_width}\n"
            f"Call net credit: ${call_net_credit}, Call margin: ${call_margin}\n"
            f"Margin = max(${put_margin}, ${call_margin}) = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    def _calc_iron_butterfly(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Iron butterfly: treated as two credit spreads (short strikes equal).

        Same formula as iron condor: max of two spread margins.
        Since short strikes are equal, both wings extend from center.
        """
        lp = _find_leg(strategy, "long_put")
        sp = _find_leg(strategy, "short_put")
        sc = _find_leg(strategy, "short_call")
        lc = _find_leg(strategy, "long_call")

        qty = lp.position.quantity
        multiplier = _multiplier(lp)

        put_width = (sp.position.security.strike - lp.position.security.strike) * multiplier * qty
        call_width = (lc.position.security.strike - sc.position.security.strike) * multiplier * qty

        put_net_credit = _leg_market_value(sp) - _leg_market_value(lp)
        call_net_credit = _leg_market_value(sc) - _leg_market_value(lc)

        put_margin = max_of(put_width - max_of(put_net_credit, ZERO), ZERO)
        call_margin = max_of(call_width - max_of(call_net_credit, ZERO), ZERO)
        margin = max_of(put_margin, call_margin)

        rule = self._find_strategy_rule("iron_condor")
        rule_ids, citations = _rule_trace(rule)

        detail = (
            f"Iron butterfly\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = max(put spread margin, call spread margin)\n"
            f"Put spread: ({_strike(sp)} - {_strike(lp)}) x {multiplier} x {qty} = ${put_width}\n"
            f"Put net credit: ${put_net_credit}, Put margin: ${put_margin}\n"
            f"Call spread: ({_strike(lc)} - {_strike(sc)}) x {multiplier} x {qty} = ${call_width}\n"
            f"Call net credit: ${call_net_credit}, Call margin: ${call_margin}\n"
            f"Margin = max(${put_margin}, ${call_margin}) = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    # ================================================================
    # Butterflies
    # ================================================================

    def _calc_long_call_butterfly(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Long call butterfly: net debit paid."""
        net_debit = _butterfly_net_debit(strategy)
        rule = self._find_strategy_rule("debit_spread")
        rule_ids, citations = _rule_trace(rule)

        context = {"net_debit": net_debit}
        margin = evaluate_formula(rule, context) if rule else net_debit

        detail = (
            f"Long call butterfly\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = net debit paid (max loss)\n"
            f"Net debit = ${net_debit}\n"
            f"Margin = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    def _calc_long_put_butterfly(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Long put butterfly: net debit paid."""
        net_debit = _butterfly_net_debit(strategy)
        rule = self._find_strategy_rule("debit_spread")
        rule_ids, citations = _rule_trace(rule)

        context = {"net_debit": net_debit}
        margin = evaluate_formula(rule, context) if rule else net_debit

        detail = (
            f"Long put butterfly\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = net debit paid (max loss)\n"
            f"Net debit = ${net_debit}\n"
            f"Margin = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    # ================================================================
    # Cross-product (stock + options)
    # ================================================================

    def _calc_covered_call(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Covered call: equity margin on stock only (call is covered)."""
        stock_leg = _find_leg(strategy, "underlying_long")
        stock_mv = abs(stock_leg.position.market_value)

        rule = self._find_strategy_rule("covered_call")
        rule_ids, citations = _rule_trace(rule)

        context = {"stock_market_value": stock_mv}
        finra = evaluate_formula(rule, context) if rule else pct(Decimal("0.25"), stock_mv)
        reg_t = pct(Decimal("0.50"), stock_mv)

        detail = (
            f"Covered call\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Call is covered by long stock; margin on stock only\n"
            f"Stock market value: ${stock_mv}\n"
            f"Reg T initial = 50% x ${stock_mv} = ${reg_t}\n"
            f"FINRA 4210 maint = {rule.formula.rate if rule else 0.25:.0%} x ${stock_mv} = ${finra}"
        )
        return reg_t, finra, detail, rule_ids, citations

    def _calc_covered_put(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Covered put: equity short margin on stock only (put is covered)."""
        stock_leg = _find_leg(strategy, "underlying_short")
        stock_mv = abs(stock_leg.position.market_value)

        rule = self._find_strategy_rule("covered_put")
        rule_ids, citations = _rule_trace(rule)

        context = {"stock_market_value": stock_mv}
        finra = evaluate_formula(rule, context) if rule else pct(Decimal("0.30"), stock_mv)
        reg_t = pct(Decimal("0.50"), stock_mv)

        detail = (
            f"Covered put\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Put is covered by short stock; margin on stock only\n"
            f"Stock market value: ${stock_mv}\n"
            f"Reg T initial = 50% x ${stock_mv} = ${reg_t}\n"
            f"FINRA 4210 maint = {rule.formula.rate if rule else 0.30:.0%} x ${stock_mv} = ${finra}"
        )
        return reg_t, finra, detail, rule_ids, citations

    def _calc_protective_put(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Protective put per FINRA 4210(f)(2)(H)(v)(a):
        FINRA = max(put_OTM_amount, 10% of exercise_value).
        Reg T = 50% of stock value."""
        stock_leg = _find_leg(strategy, "underlying_long")
        put_leg = _find_leg(strategy, "long_put")

        stock_mv = abs(stock_leg.position.market_value)
        put_strike = put_leg.position.security.strike
        put_qty = put_leg.position.quantity
        multiplier = _multiplier(put_leg)

        u_price = underlying_price if underlying_price > ZERO else stock_leg.position.market_price
        # OTM amount = how far the put is out of the money
        put_otm = max_of(u_price - put_strike, ZERO) * to_decimal(multiplier) * put_qty
        exercise_value = put_strike * to_decimal(multiplier) * put_qty
        finra_floor = pct(Decimal("0.10"), exercise_value)

        rule = self._find_strategy_rule("protective")
        rule_ids, citations = _rule_trace(rule)

        finra = max_of(put_otm, finra_floor)
        reg_t = pct(Decimal("0.50"), stock_mv)

        detail = (
            f"Protective put\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: FINRA = max(put OTM amount, 10% of exercise value)\n"
            f"Stock market value: ${stock_mv}\n"
            f"Put strike: ${put_strike}, Underlying price: ${u_price}\n"
            f"Put OTM = max({u_price} - {put_strike}, 0) x {multiplier} x {put_qty} = ${put_otm}\n"
            f"Exercise value = {put_strike} x {multiplier} x {put_qty} = ${exercise_value}\n"
            f"Floor = 10% x ${exercise_value} = ${finra_floor}\n"
            f"FINRA 4210 maint = max(${put_otm}, ${finra_floor}) = ${finra}\n"
            f"Reg T initial = 50% x ${stock_mv} = ${reg_t}"
        )
        return reg_t, finra, detail, rule_ids, citations

    def _calc_protective_call(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Protective call per FINRA 4210(f)(2)(H)(v)(a):
        FINRA = max(call_OTM_amount, 10% of exercise_value).
        Reg T = 50% of stock value."""
        stock_leg = _find_leg(strategy, "underlying_short")
        call_leg = _find_leg(strategy, "long_call")

        stock_mv = abs(stock_leg.position.market_value)
        call_strike = call_leg.position.security.strike
        call_qty = call_leg.position.quantity
        multiplier = _multiplier(call_leg)

        u_price = underlying_price if underlying_price > ZERO else stock_leg.position.market_price
        # OTM amount = how far the call is out of the money
        call_otm = max_of(call_strike - u_price, ZERO) * to_decimal(multiplier) * call_qty
        exercise_value = call_strike * to_decimal(multiplier) * call_qty
        finra_floor = pct(Decimal("0.10"), exercise_value)

        rule = self._find_strategy_rule("protective")
        rule_ids, citations = _rule_trace(rule)

        finra = max_of(call_otm, finra_floor)
        reg_t = pct(Decimal("0.50"), stock_mv)

        detail = (
            f"Protective call\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: FINRA = max(call OTM amount, 10% of exercise value)\n"
            f"Stock market value: ${stock_mv}\n"
            f"Call strike: ${call_strike}, Underlying price: ${u_price}\n"
            f"Call OTM = max({call_strike} - {u_price}, 0) x {multiplier} x {call_qty} = ${call_otm}\n"
            f"Exercise value = {call_strike} x {multiplier} x {call_qty} = ${exercise_value}\n"
            f"Floor = 10% x ${exercise_value} = ${finra_floor}\n"
            f"FINRA 4210 maint = max(${call_otm}, ${finra_floor}) = ${finra}\n"
            f"Reg T initial = 50% x ${stock_mv} = ${reg_t}"
        )
        return reg_t, finra, detail, rule_ids, citations

    def _calc_collar(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Collar per FINRA 4210(f)(2)(H)(v)(d):
        FINRA = put OTM amount. Reg T = 50% of stock value."""
        stock_leg = _find_leg(strategy, "underlying_long")
        put_leg = _find_leg(strategy, "long_put")

        stock_mv = abs(stock_leg.position.market_value)
        put_strike = put_leg.position.security.strike
        put_qty = put_leg.position.quantity
        multiplier = _multiplier(put_leg)

        u_price = underlying_price if underlying_price > ZERO else stock_leg.position.market_price
        # OTM amount of the put
        put_otm = max_of(u_price - put_strike, ZERO) * to_decimal(multiplier) * put_qty

        rule = self._find_strategy_rule("collar")
        rule_ids, citations = _rule_trace(rule)

        finra = put_otm
        reg_t = pct(Decimal("0.50"), stock_mv)

        detail = (
            f"Collar\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: FINRA = put OTM amount per 4210(f)(2)(H)(v)(d)\n"
            f"Stock market value: ${stock_mv}\n"
            f"Put OTM = max({u_price} - {put_strike}, 0) x {multiplier} x {put_qty} = ${put_otm}\n"
            f"FINRA 4210 maint = ${finra}\n"
            f"Reg T initial = 50% x ${stock_mv} = ${reg_t}"
        )
        return reg_t, finra, detail, rule_ids, citations

    # ================================================================
    # Cross-Asset: Convertible Bond Arbitrage
    # ================================================================

    def _calc_convertible_arb(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Convertible arbitrage per FINRA 4210(e)(2)(H) / 4210(c)(1).

        Long convertible bond + short underlying equity.
        FINRA maintenance: 10% of bond market value (hedged convertible rate).
        Reg T initial: 50% of short equity market value + bond is fully paid.
        """
        bond_leg = _find_leg(strategy, "long_convertible")
        equity_leg = _find_leg(strategy, "short_equity_hedge")

        bond_mv = abs(bond_leg.position.market_value)
        equity_mv = abs(equity_leg.position.market_value)

        # No YAML rule yet — hardcoded per FINRA 4210(e)(2)(H)
        rule_ids = ["4210_e_2_H"]
        citations = ["FINRA 4210(e)(2)(H)", "FINRA 4210(c)(1)", "Reg T 220.12(c)"]

        # Hedged convertible: 10% of combined position value
        # (vs 25% bond + 30% short if margined separately)
        hedged_rate = Decimal("0.10")
        finra = round_margin(pct(hedged_rate, bond_mv + equity_mv))

        # Reg T: short equity at 50%, bond is fully paid (long, no additional margin)
        reg_t = pct(Decimal("0.50"), equity_mv)

        detail = (
            f"Convertible bond arbitrage\n"
            f"Rule: {rule_ids[0]} | {citations[0]}\n"
            f"Formula: Hedged convertible — 10% of combined position value\n"
            f"Bond market value: ${bond_mv}\n"
            f"Short equity market value: ${equity_mv}\n"
            f"Combined value: ${bond_mv + equity_mv}\n"
            f"FINRA 4210 maint = 10% x ${bond_mv + equity_mv} = ${finra}\n"
            f"Reg T initial = 50% x ${equity_mv} = ${reg_t}"
        )
        return reg_t, finra, detail, rule_ids, citations

    # ================================================================
    # Conversions & Reverse Conversions
    # ================================================================

    def _calc_conversion(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Conversion: FINRA = max(10% of strike x contracts, $250/contract).
        Reg T = 50% of stock market value."""
        put_leg = _find_leg(strategy, "long_put")
        stock_leg = _find_leg(strategy, "underlying_long")
        strike = _strike(put_leg)
        qty = put_leg.position.quantity
        multiplier = _multiplier(put_leg)
        stock_mv = abs(stock_leg.position.market_value)

        rule = self._find_strategy_rule("conversion")
        rule_ids, citations = _rule_trace(rule)

        context = {
            "option_strike": strike,
            "contract_multiplier": multiplier,
            "contracts": qty,
        }
        finra = evaluate_formula(rule, context) if rule else max_of(
            pct(Decimal("0.10"), strike * to_decimal(multiplier) * qty),
            Decimal("250") * qty,
        )
        reg_t = pct(Decimal("0.50"), stock_mv)

        strike_based = pct(Decimal("0.10"), strike * to_decimal(multiplier) * qty)
        per_contract = Decimal("250") * qty

        detail = (
            f"Conversion\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: FINRA = max(10% x strike x multiplier x contracts, $250 x contracts)\n"
            f"Reg T = 50% x stock market value\n"
            f"Strike: ${strike}, Contracts: {qty}, Multiplier: {multiplier}\n"
            f"Stock market value: ${stock_mv}\n"
            f"10% of strike value = ${strike_based}\n"
            f"$250 per contract = ${per_contract}\n"
            f"FINRA = ${finra}\n"
            f"Reg T = ${reg_t}"
        )
        return reg_t, finra, detail, rule_ids, citations

    def _calc_reverse_conversion(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Reverse conversion: FINRA = max(10% of strike x contracts, $250/contract).
        Reg T = 50% of stock market value."""
        call_leg = _find_leg(strategy, "long_call")
        stock_leg = _find_leg(strategy, "underlying_short")
        strike = _strike(call_leg)
        qty = call_leg.position.quantity
        multiplier = _multiplier(call_leg)
        stock_mv = abs(stock_leg.position.market_value)

        rule = self._find_strategy_rule("reverse_conversion")
        rule_ids, citations = _rule_trace(rule)

        context = {
            "option_strike": strike,
            "contract_multiplier": multiplier,
            "contracts": qty,
        }
        finra = evaluate_formula(rule, context) if rule else max_of(
            pct(Decimal("0.10"), strike * to_decimal(multiplier) * qty),
            Decimal("250") * qty,
        )
        reg_t = pct(Decimal("0.50"), stock_mv)

        strike_based = pct(Decimal("0.10"), strike * to_decimal(multiplier) * qty)
        per_contract = Decimal("250") * qty

        detail = (
            f"Reverse conversion\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: FINRA = max(10% x strike x multiplier x contracts, $250 x contracts)\n"
            f"Reg T = 50% x stock market value\n"
            f"Strike: ${strike}, Contracts: {qty}, Multiplier: {multiplier}\n"
            f"Stock market value: ${stock_mv}\n"
            f"10% of strike value = ${strike_based}\n"
            f"$250 per contract = ${per_contract}\n"
            f"FINRA = ${finra}\n"
            f"Reg T = ${reg_t}"
        )
        return reg_t, finra, detail, rule_ids, citations

    # ================================================================
    # Calendar / Diagonal Spreads
    # ================================================================

    def _calc_calendar_spread(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Calendar spread: margin = net debit paid."""
        net_debit = _time_spread_net_debit(strategy)
        rule = self._find_strategy_rule("debit_spread")
        rule_ids, citations = _rule_trace(rule)

        context = {"net_debit": net_debit}
        margin = evaluate_formula(rule, context) if rule else net_debit

        detail = (
            f"Calendar spread\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = net debit paid\n"
            f"Net debit = ${net_debit}\n"
            f"Margin = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    def _calc_diagonal_spread(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Diagonal spread: margin = net debit paid."""
        net_debit = _time_spread_net_debit(strategy)
        rule = self._find_strategy_rule("debit_spread")
        rule_ids, citations = _rule_trace(rule)

        context = {"net_debit": net_debit}
        margin = evaluate_formula(rule, context) if rule else net_debit

        detail = (
            f"Diagonal spread\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = net debit paid\n"
            f"Net debit = ${net_debit}\n"
            f"Margin = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    # ================================================================
    # Short Butterflies
    # ================================================================

    def _calc_short_call_butterfly(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Short call butterfly: sell wings, buy center. Margin = wing width - net credit."""
        return self._calc_short_butterfly(strategy, underlying_price, "Short call butterfly")

    def _calc_short_put_butterfly(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Short put butterfly: sell wings, buy center. Margin = wing width - net credit."""
        return self._calc_short_butterfly(strategy, underlying_price, "Short put butterfly")

    def _calc_short_butterfly(
        self, strategy: RecognizedStrategy, underlying_price: Decimal, name: str
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Common calc for short butterflies: margin = wing width - net credit."""
        # Sort legs by strike to identify low/mid/high
        option_legs = [leg for leg in strategy.legs if isinstance(leg.position.security, Option)]
        sorted_legs = sorted(option_legs, key=lambda l: l.position.security.strike)

        low, mid, high = sorted_legs[0], sorted_legs[1], sorted_legs[2]
        multiplier = _multiplier(low)
        qty = low.position.quantity

        wing_width = (high.position.security.strike - low.position.security.strike) / 2 * to_decimal(multiplier) * qty

        # Net credit = premiums received (short wings) - premiums paid (long center)
        received = ZERO
        paid = ZERO
        for leg in strategy.legs:
            mv = _leg_market_value(leg)
            if leg.position.is_short:
                received += mv
            else:
                paid += mv
        net_credit = max_of(received - paid, ZERO)

        margin = max_of(wing_width - net_credit, ZERO)

        rule = self._find_strategy_rule("credit_spread")
        rule_ids, citations = _rule_trace(rule)

        detail = (
            f"{name}\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = wing width - net credit\n"
            f"Wing width = ${wing_width}\n"
            f"Net credit = ${net_credit}\n"
            f"Margin = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    # ================================================================
    # Long Iron Butterfly & Long Iron Condor
    # ================================================================

    def _calc_long_iron_butterfly(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Long iron butterfly: net debit paid (max loss)."""
        return self._calc_long_iron(strategy, "Long iron butterfly")

    def _calc_long_iron_condor(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Long iron condor: net debit paid (max loss)."""
        return self._calc_long_iron(strategy, "Long iron condor")

    def _calc_long_iron(
        self, strategy: RecognizedStrategy, name: str
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Common calc for long iron strategies: margin = net debit paid."""
        paid = ZERO
        received = ZERO
        for leg in strategy.legs:
            mv = _leg_market_value(leg)
            if leg.position.is_long:
                paid += mv
            else:
                received += mv
        net_debit = max_of(paid - received, ZERO)

        rule = self._find_strategy_rule("debit_spread")
        rule_ids, citations = _rule_trace(rule)

        context = {"net_debit": net_debit}
        margin = evaluate_formula(rule, context) if rule else net_debit

        detail = (
            f"{name}\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = net debit paid (max loss)\n"
            f"Net debit = ${net_debit}\n"
            f"Margin = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    # ================================================================
    # Long Condor Spreads
    # ================================================================

    def _calc_long_call_condor(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Long call condor: net debit paid."""
        return self._calc_long_condor(strategy, "Long call condor")

    def _calc_long_put_condor(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Long put condor: net debit paid."""
        return self._calc_long_condor(strategy, "Long put condor")

    def _calc_long_condor(
        self, strategy: RecognizedStrategy, name: str
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Common calc for long condors: margin = net debit paid."""
        net_debit = _butterfly_net_debit(strategy)  # Same logic: long legs - short legs
        rule = self._find_strategy_rule("debit_spread")
        rule_ids, citations = _rule_trace(rule)

        context = {"net_debit": net_debit}
        margin = evaluate_formula(rule, context) if rule else net_debit

        detail = (
            f"{name}\n"
            f"Rule: {rule_ids[0] if rule_ids else 'N/A'} | {citations[0] if citations else ''}\n"
            f"Formula: Margin = net debit paid (max loss)\n"
            f"Net debit = ${net_debit}\n"
            f"Margin = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    # ================================================================
    # Box Spread
    # ================================================================

    def _calc_box_spread(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Long box spread (European): margin = net cost of the box."""
        paid = ZERO
        received = ZERO
        for leg in strategy.legs:
            mv = _leg_market_value(leg)
            if leg.position.is_long:
                paid += mv
            else:
                received += mv
        net_cost = max_of(paid - received, ZERO)

        rule_ids = ["4210_f_2_H_v_e"]
        citations = ["FINRA 4210(f)(2)(H)(v)(e)", "Reg T 220.12(c)"]

        detail = (
            f"Box spread\n"
            f"Rule: 4210_f_2_H_v_e | FINRA 4210(f)(2)(H)(v)(e)\n"
            f"Formula: Margin = net cost of the box\n"
            f"Net cost = ${net_cost}\n"
            f"Margin = ${net_cost}"
        )
        return net_cost, net_cost, detail, rule_ids, citations

    # ================================================================
    # Ratio Spreads & Backspreads
    # ================================================================

    def _calc_ratio_call_spread(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Ratio call spread: spread margin on matched + naked on excess shorts."""
        return self._calc_ratio_spread(strategy, underlying_price, "Ratio call spread", is_front=True)

    def _calc_ratio_put_spread(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Ratio put spread: spread margin on matched + naked on excess shorts."""
        return self._calc_ratio_spread(strategy, underlying_price, "Ratio put spread", is_front=True)

    def _calc_call_backspread(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Call backspread: spread margin on matched + long cost on excess longs."""
        return self._calc_ratio_spread(strategy, underlying_price, "Call backspread", is_front=False)

    def _calc_put_backspread(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Put backspread: spread margin on matched + long cost on excess longs."""
        return self._calc_ratio_spread(strategy, underlying_price, "Put backspread", is_front=False)

    def _calc_ratio_spread(
        self, strategy: RecognizedStrategy, underlying_price: Decimal,
        name: str, is_front: bool,
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Common calc for ratio spreads and backspreads.

        Front ratio: long N + short M (M > N). Matched portion = vertical spread.
                     Excess M-N short legs get naked margin.
        Backspread:  short N + long M (M > N). Matched portion = vertical spread.
                     Excess M-N long legs are paid in full (no additional margin).
        """
        long_legs = [l for l in strategy.legs if l.position.is_long]
        short_legs = [l for l in strategy.legs if l.position.is_short]

        if not long_legs or not short_legs:
            return ZERO, ZERO, f"{name}: missing legs", [], []

        long_leg = long_legs[0]
        short_leg = short_legs[0]
        long_qty = long_leg.position.quantity
        short_qty = short_leg.position.quantity
        matched = min(long_qty, short_qty)
        multiplier = _multiplier(short_leg)
        mult_d = to_decimal(multiplier)

        # Spread portion margin (credit spread on matched contracts)
        strike_diff = abs(short_leg.position.security.strike - long_leg.position.security.strike)
        spread_max_loss = strike_diff * mult_d * matched
        short_premium_matched = abs(short_leg.position.market_price) * mult_d * matched
        long_premium_matched = abs(long_leg.position.market_price) * mult_d * matched
        net_credit_matched = short_premium_matched - long_premium_matched
        spread_margin = max_of(spread_max_loss - max_of(net_credit_matched, ZERO), ZERO)

        if is_front:
            # Excess short legs get naked margin
            excess = short_qty - matched
            if excess > ZERO:
                naked_req = self._finra.calculate(short_leg.position, underlying_price)
                # Scale naked margin to excess contracts only
                naked_per_contract = naked_req.finra_4210_maintenance / short_qty if short_qty > ZERO else ZERO
                naked_margin = naked_per_contract * excess
            else:
                naked_margin = ZERO
            margin = spread_margin + naked_margin
            excess_detail = f"Excess {excess} short contracts: naked margin = ${naked_margin}"
        else:
            # Excess long legs: paid in full (premium only, no additional margin)
            excess = long_qty - matched
            long_cost = abs(long_leg.position.market_price) * mult_d * excess
            margin = spread_margin + long_cost
            excess_detail = f"Excess {excess} long contracts: cost = ${long_cost}"

        rule_ids = ["4210_f_2_H_i"]
        citations = ["FINRA 4210(f)(2)(H)(i)", "Reg T 220.12(c)"]

        detail = (
            f"{name}\n"
            f"Matched: {matched} contracts (vertical spread)\n"
            f"Spread margin: ${spread_margin}\n"
            f"{excess_detail}\n"
            f"Total margin = ${margin}"
        )
        return margin, margin, detail, rule_ids, citations

    # ================================================================
    # Synthetic Long / Short
    # ================================================================

    def _calc_synthetic_long(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Synthetic long stock: long call + short put. Margined as long stock."""
        return self._calc_synthetic(strategy, underlying_price, is_long=True)

    def _calc_synthetic_short(
        self, strategy: RecognizedStrategy, underlying_price: Decimal
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Synthetic short stock: short call + long put. Margined as short stock."""
        return self._calc_synthetic(strategy, underlying_price, is_long=False)

    def _calc_synthetic(
        self, strategy: RecognizedStrategy, underlying_price: Decimal, is_long: bool,
    ) -> tuple[Decimal, Decimal, str, list[str], list[str]]:
        """Common calc for synthetic positions."""
        if is_long:
            call_leg = _find_leg(strategy, "long_call")
            name = "Synthetic long stock"
            finra_rate = Decimal("0.25")
        else:
            call_leg = _find_leg(strategy, "short_call")
            name = "Synthetic short stock"
            finra_rate = Decimal("0.30")

        strike = _strike(call_leg)
        multiplier = _multiplier(call_leg)
        qty = call_leg.position.quantity

        notional = strike * to_decimal(multiplier) * qty
        finra = pct(finra_rate, notional)
        reg_t = pct(Decimal("0.50"), notional)

        rule_ids = ["4210_f_2_H_i"]
        citations = ["FINRA 4210(f)(2)(H)", "Reg T 220.12(c)"]

        detail = (
            f"{name}\n"
            f"Notional (strike x multiplier x qty): ${notional}\n"
            f"FINRA maintenance ({finra_rate:.0%}): ${finra}\n"
            f"Reg T initial (50%): ${reg_t}\n"
            f"Margin = ${finra}"
        )
        return reg_t, finra, detail, rule_ids, citations


# ================================================================
# Helper functions
# ================================================================

def _rule_trace(rule: RuleConfig | None) -> tuple[list[str], list[str]]:
    """Extract rule_ids and citations from a matched YAML rule.

    Always includes Reg T 220.12(c) since Reg T defers option strategy
    margin to the SRO (FINRA 4210(f)).
    """
    if rule:
        citations = [rule.citation, "Reg T 220.12(c)"] if rule.citation else ["Reg T 220.12(c)"]
        return [rule.id], citations
    return [], ["Reg T 220.12(c)"]


def _find_leg(strategy: RecognizedStrategy, role: str) -> StrategyLeg:
    """Find a leg by its role in the strategy."""
    for leg in strategy.legs:
        if leg.role == role:
            return leg
    raise ValueError(f"Strategy {strategy.strategy_id} missing leg with role '{role}'")


def _strike(leg: StrategyLeg) -> Decimal:
    """Get the strike price from a strategy leg."""
    return leg.position.security.strike


def _multiplier(leg: StrategyLeg) -> int:
    """Get the contract multiplier from a strategy leg."""
    sec = leg.position.security
    if isinstance(sec, Option):
        return sec.contract_multiplier
    return 1


def _leg_market_value(leg: StrategyLeg) -> Decimal:
    """Get the absolute market value of a strategy leg."""
    return abs(leg.position.market_value)


def _net_debit_from_legs(long_leg: StrategyLeg, short_leg: StrategyLeg) -> Decimal:
    """Calculate net debit for a 2-leg debit spread."""
    paid = _leg_market_value(long_leg)
    received = _leg_market_value(short_leg)
    return max_of(paid - received, ZERO)


def _credit_spread_margin(
    short_leg: StrategyLeg, long_leg: StrategyLeg
) -> Decimal:
    """Credit spread margin: strike width * multiplier * qty - net credit."""
    strike_width = abs(short_leg.position.security.strike - long_leg.position.security.strike)
    qty = short_leg.position.quantity
    multiplier = _multiplier(short_leg)
    max_loss = strike_width * to_decimal(multiplier) * qty

    net_credit = _leg_market_value(short_leg) - _leg_market_value(long_leg)
    margin = max_of(max_loss - max_of(net_credit, ZERO), ZERO)
    return margin


def _net_credit_four_leg(
    lp: StrategyLeg, sp: StrategyLeg, sc: StrategyLeg, lc: StrategyLeg
) -> Decimal:
    """Net credit for a 4-leg iron condor/butterfly."""
    received = _leg_market_value(sp) + _leg_market_value(sc)
    paid = _leg_market_value(lp) + _leg_market_value(lc)
    return max_of(received - paid, ZERO)


def _butterfly_net_debit(strategy: RecognizedStrategy) -> Decimal:
    """Net debit for a butterfly spread."""
    paid = ZERO
    received = ZERO
    for leg in strategy.legs:
        mv = _leg_market_value(leg)
        if leg.position.is_long:
            paid += mv
        else:
            received += mv
    return max_of(paid - received, ZERO)


def _total_premium_paid(strategy: RecognizedStrategy) -> Decimal:
    """Total premium paid for a debit strategy (all long legs)."""
    total = ZERO
    for leg in strategy.legs:
        total += _leg_market_value(leg)
    return total


def _time_spread_net_debit(strategy: RecognizedStrategy) -> Decimal:
    """Net debit for a calendar/diagonal spread."""
    paid = ZERO
    received = ZERO
    for leg in strategy.legs:
        mv = _leg_market_value(leg)
        if leg.position.is_long:
            paid += mv
        else:
            received += mv
    return max_of(paid - received, ZERO)


# ================================================================
# Strategy type -> calculator dispatch table
# ================================================================

_StrategyCalcFn = Callable[
    ["StrategyMarginCalculator", RecognizedStrategy, Decimal],
    tuple[Decimal, Decimal, str, list[str], list[str]],
]

_STRATEGY_CALCULATORS: dict[StrategyType, _StrategyCalcFn] = {
    # Naked options
    StrategyType.SHORT_NAKED_CALL: StrategyMarginCalculator._calc_naked_call,
    StrategyType.SHORT_NAKED_PUT: StrategyMarginCalculator._calc_naked_put,
    # Vertical spreads
    StrategyType.BULL_CALL_SPREAD: StrategyMarginCalculator._calc_bull_call_spread,
    StrategyType.BEAR_CALL_SPREAD: StrategyMarginCalculator._calc_bear_call_spread,
    StrategyType.BULL_PUT_SPREAD: StrategyMarginCalculator._calc_bull_put_spread,
    StrategyType.BEAR_PUT_SPREAD: StrategyMarginCalculator._calc_bear_put_spread,
    # Straddles & strangles
    StrategyType.LONG_STRADDLE: StrategyMarginCalculator._calc_long_straddle,
    StrategyType.SHORT_STRADDLE: StrategyMarginCalculator._calc_short_straddle,
    StrategyType.LONG_STRANGLE: StrategyMarginCalculator._calc_long_strangle,
    StrategyType.SHORT_STRANGLE: StrategyMarginCalculator._calc_short_strangle,
    # Iron condor & butterfly (short)
    StrategyType.IRON_CONDOR: StrategyMarginCalculator._calc_iron_condor,
    StrategyType.IRON_BUTTERFLY: StrategyMarginCalculator._calc_iron_butterfly,
    # Iron condor & butterfly (long)
    StrategyType.LONG_IRON_BUTTERFLY: StrategyMarginCalculator._calc_long_iron_butterfly,
    StrategyType.LONG_IRON_CONDOR: StrategyMarginCalculator._calc_long_iron_condor,
    # Butterflies (long)
    StrategyType.LONG_CALL_BUTTERFLY: StrategyMarginCalculator._calc_long_call_butterfly,
    StrategyType.LONG_PUT_BUTTERFLY: StrategyMarginCalculator._calc_long_put_butterfly,
    # Butterflies (short)
    StrategyType.SHORT_CALL_BUTTERFLY: StrategyMarginCalculator._calc_short_call_butterfly,
    StrategyType.SHORT_PUT_BUTTERFLY: StrategyMarginCalculator._calc_short_put_butterfly,
    # Condor spreads (long)
    StrategyType.LONG_CALL_CONDOR: StrategyMarginCalculator._calc_long_call_condor,
    StrategyType.LONG_PUT_CONDOR: StrategyMarginCalculator._calc_long_put_condor,
    # Box spread
    StrategyType.BOX_SPREAD: StrategyMarginCalculator._calc_box_spread,
    # Cross-product
    StrategyType.COVERED_CALL: StrategyMarginCalculator._calc_covered_call,
    StrategyType.COVERED_PUT: StrategyMarginCalculator._calc_covered_put,
    StrategyType.PROTECTIVE_PUT: StrategyMarginCalculator._calc_protective_put,
    StrategyType.PROTECTIVE_CALL: StrategyMarginCalculator._calc_protective_call,
    StrategyType.COLLAR: StrategyMarginCalculator._calc_collar,
    # Conversions
    StrategyType.CONVERSION: StrategyMarginCalculator._calc_conversion,
    StrategyType.REVERSE_CONVERSION: StrategyMarginCalculator._calc_reverse_conversion,
    # Calendar / diagonal
    StrategyType.CALENDAR_SPREAD: StrategyMarginCalculator._calc_calendar_spread,
    StrategyType.DIAGONAL_SPREAD: StrategyMarginCalculator._calc_diagonal_spread,
    # Ratio spreads & backspreads
    StrategyType.RATIO_CALL_SPREAD: StrategyMarginCalculator._calc_ratio_call_spread,
    StrategyType.RATIO_PUT_SPREAD: StrategyMarginCalculator._calc_ratio_put_spread,
    StrategyType.CALL_BACKSPREAD: StrategyMarginCalculator._calc_call_backspread,
    StrategyType.PUT_BACKSPREAD: StrategyMarginCalculator._calc_put_backspread,
    # Synthetic positions
    StrategyType.SYNTHETIC_LONG: StrategyMarginCalculator._calc_synthetic_long,
    StrategyType.SYNTHETIC_SHORT: StrategyMarginCalculator._calc_synthetic_short,
    # Cross-asset
    StrategyType.CONVERTIBLE_ARB: StrategyMarginCalculator._calc_convertible_arb,
}
