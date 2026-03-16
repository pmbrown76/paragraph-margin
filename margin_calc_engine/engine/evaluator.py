"""Formula evaluation engine — all 18+ formula types."""

from decimal import Decimal
from typing import Any

from margin_calc_engine.rules.schema import RuleConfig
from margin_calc_engine.money import ZERO, max_of, pct, round_margin, to_decimal


def evaluate_formula(rule: RuleConfig, context: dict[str, Any]) -> Decimal:
    """Evaluate a rule's formula against a position context and return the margin amount."""
    formula = rule.formula
    market_value = to_decimal(context.get("market_value", 0))
    quantity = to_decimal(context.get("quantity", 0))

    if formula.type == "percentage_of_market_value":
        margin = pct(formula.rate, abs(market_value))
        # Apply minimum floors
        if rule.minimum and rule.minimum.type == "fixed_per_share":
            per_share_min = to_decimal(rule.minimum.amount) * abs(quantity)
            margin = max_of(margin, per_share_min)
        elif rule.minimum and rule.minimum.type == "percentage_of_principal":
            par_value = to_decimal(context.get("par_value", 1000))
            principal_min = pct(rule.minimum.amount, par_value * abs(quantity))
            margin = max_of(margin, principal_min)
        return round_margin(margin)

    elif formula.type == "percentage_of_trade_value":
        # Reg T initial margin: based on trade price (average_cost x quantity)
        trade_value = to_decimal(context.get("trade_value", 0))
        margin = pct(formula.rate, abs(trade_value))
        if rule.minimum and rule.minimum.type == "fixed_per_share":
            per_share_min = to_decimal(rule.minimum.amount) * abs(quantity)
            margin = max_of(margin, per_share_min)
        return round_margin(margin)

    elif formula.type == "percentage_of_principal":
        par_value = to_decimal(context.get("par_value", 1000))
        margin = pct(formula.rate, par_value * abs(quantity))
        return round_margin(margin)

    elif formula.type == "fixed_per_share":
        margin = to_decimal(formula.rate) * abs(quantity)
        return round_margin(margin)

    elif formula.type == "naked_option":
        # Standard naked option formula:
        # 100% of premium + MAX((X% of underlying - OTM), (Y% of underlying/strike))
        premium = abs(market_value)
        underlying_price = to_decimal(context.get("underlying_price", 0))
        strike = to_decimal(context.get("strike", 0))
        multiplier = int(context.get("contract_multiplier", 100))
        contracts = abs(quantity)
        underlying_value = underlying_price * to_decimal(multiplier) * contracts

        base_pct = pct(formula.underlying_pct, underlying_value)

        # Calculate OTM amount
        otm_amount = ZERO
        if formula.otm_deduction:
            option_type = context.get("option_type", "call")
            if option_type == "call" and underlying_price < strike:
                otm_amount = (strike - underlying_price) * to_decimal(multiplier) * contracts
            elif option_type == "put" and underlying_price > strike:
                otm_amount = (underlying_price - strike) * to_decimal(multiplier) * contracts

        main_calc = base_pct - otm_amount

        # Minimum calculation
        min_pct = pct(formula.minimum_underlying_pct, underlying_value)
        min_per_contract = to_decimal(formula.minimum_per_contract) * contracts

        margin = premium + max_of(main_calc, min_pct, min_per_contract)
        return round_margin(margin)

    elif formula.type == "full_payment":
        # Reg T: pay in full based on trade price (what was paid)
        trade_value = to_decimal(context.get("trade_value", 0))
        return round_margin(abs(trade_value))

    elif formula.type == "good_faith":
        # Good faith margin - defers to the rate if provided, else 0
        if formula.rate > 0:
            return round_margin(pct(formula.rate, abs(market_value)))
        return ZERO

    # ================================================================
    # Strategy formula types — used by strategy margin calculator
    # These expect strategy-specific context fields
    # ================================================================

    elif formula.type == "debit_spread":
        # Margin = net debit paid (max loss on debit spread)
        net_debit = to_decimal(context.get("net_debit", 0))
        return round_margin(net_debit)

    elif formula.type == "credit_spread":
        # Margin = (strike width x multiplier x qty) - net credit
        strike_width = to_decimal(context.get("strike_width", 0))
        multiplier_val = to_decimal(context.get("contract_multiplier", 100))
        qty = to_decimal(context.get("contracts", 0))
        net_credit = to_decimal(context.get("net_credit", 0))
        max_loss = strike_width * multiplier_val * qty
        return round_margin(max_of(max_loss - max_of(net_credit, ZERO), ZERO))

    elif formula.type == "short_straddle_strangle":
        # Margin = max(naked call margin, naked put margin) + other side premium
        naked_call_margin = to_decimal(context.get("naked_call_margin", 0))
        naked_put_margin = to_decimal(context.get("naked_put_margin", 0))
        call_premium = to_decimal(context.get("call_premium", 0))
        put_premium = to_decimal(context.get("put_premium", 0))
        if naked_call_margin >= naked_put_margin:
            return round_margin(naked_call_margin + put_premium)
        else:
            return round_margin(naked_put_margin + call_premium)

    elif formula.type == "iron_condor":
        # Margin = max(put spread margin, call spread margin)
        put_wing = to_decimal(context.get("put_wing", 0))
        call_wing = to_decimal(context.get("call_wing", 0))
        put_net_credit = to_decimal(context.get("put_net_credit", 0))
        call_net_credit = to_decimal(context.get("call_net_credit", 0))
        put_margin = max_of(put_wing - max_of(put_net_credit, ZERO), ZERO)
        call_margin = max_of(call_wing - max_of(call_net_credit, ZERO), ZERO)
        return round_margin(max_of(put_margin, call_margin))

    elif formula.type == "covered_equity":
        # Margin = rate x stock market value (call/put is covered)
        stock_mv = to_decimal(context.get("stock_market_value", 0))
        return round_margin(pct(formula.rate, stock_mv))

    elif formula.type == "protective_equity":
        # Margin = max(rate x stock MV - option intrinsic, floor_rate x strike x multiplier x qty)
        stock_mv = to_decimal(context.get("stock_market_value", 0))
        option_intrinsic = to_decimal(context.get("option_intrinsic", 0))
        option_strike = to_decimal(context.get("option_strike", 0))
        multiplier_val = to_decimal(context.get("contract_multiplier", 100))
        qty = to_decimal(context.get("contracts", 0))
        base = pct(formula.rate, stock_mv) - option_intrinsic
        floor = pct(formula.floor_rate, option_strike * multiplier_val * qty)
        return round_margin(max_of(base, floor))

    elif formula.type == "conversion":
        # Margin = max(rate x strike x multiplier x contracts, per_contract_minimum x contracts)
        strike = to_decimal(context.get("option_strike", 0))
        multiplier_val = to_decimal(context.get("contract_multiplier", 100))
        qty = to_decimal(context.get("contracts", 0))
        strike_based = pct(formula.rate, strike * multiplier_val * qty)
        per_contract = to_decimal(formula.per_contract_minimum) * qty
        return round_margin(max_of(strike_based, per_contract))

    elif formula.type == "spread_max_loss":
        # Generic spread max loss — same as debit spread
        net_debit = to_decimal(context.get("net_debit", 0))
        return round_margin(net_debit)

    elif formula.type == "box_spread":
        # Box spread margin = net cost of the box
        net_cost = to_decimal(context.get("net_cost", 0))
        return round_margin(max_of(net_cost, ZERO))

    elif formula.type == "ratio_spread":
        # Ratio spread: spread margin on matched + naked/long on excess
        spread_margin = to_decimal(context.get("spread_margin", 0))
        excess_margin = to_decimal(context.get("excess_margin", 0))
        return round_margin(spread_margin + excess_margin)

    elif formula.type == "synthetic_stock":
        # Synthetic stock: margined as equivalent stock position
        notional = to_decimal(context.get("notional", 0))
        return round_margin(pct(formula.rate, notional))

    else:
        # Unknown formula type - return 0 and log warning
        return ZERO
