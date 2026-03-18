"""Build evaluation context from a Position for rule condition matching."""

from decimal import Decimal
from typing import Any

from paragraph_margin.models.enums import PositionSide, SecurityType
from paragraph_margin.models.positions import Position
from paragraph_margin.models.securities import ETF, ETP, AgencyDebt, CorporateBond, Equity, MunicipalBond, Option, SecurityFuture, USTreasury
from paragraph_margin.money import ZERO


def build_position_context(position: Position, underlying_price: Decimal = ZERO) -> dict[str, Any]:
    """Build a context dictionary from a position for rule condition matching."""
    sec = position.security
    ctx: dict[str, Any] = {
        "security_type": sec.security_type.value,
        "position_side": position.side.value,
        "marginable": sec.marginable,
        "market_price": position.market_price,
        "market_value": position.market_value,
        "trade_price": position.average_cost,
        "trade_value": position.cost_basis,
        "quantity": position.quantity,
    }

    # Equity-specific
    if isinstance(sec, Equity):
        ctx["concentrated"] = False  # TODO: wire up concentration detection

    # Option-specific
    if isinstance(sec, Option):
        from datetime import date as date_cls
        ctx["option_type"] = sec.option_type.value
        ctx["underlying_type"] = "equity"  # default
        if sec.is_index_option:
            ctx["underlying_type"] = "index"
            ctx["index_type"] = sec.index_type.value if sec.index_type else None
        elif isinstance(sec.underlying, ETF):
            ctx["underlying_type"] = "etf"
            ctx["underlying_leverage_factor"] = abs(sec.underlying.leverage_factor)
        elif isinstance(sec.underlying, ETP):
            ctx["underlying_type"] = "etp"
            ctx["underlying_leverage_factor"] = abs(sec.underlying.leverage_factor)
        ctx["exercise_style"] = sec.exercise_style.value
        ctx["settlement_type"] = sec.settlement_type.value
        ctx["strike"] = sec.strike
        ctx["expiration"] = sec.expiration
        ctx["contract_multiplier"] = sec.contract_multiplier
        ctx["underlying_price"] = underlying_price
        ctx["covered"] = False  # Default; strategy recognizer overrides for covered positions
        ctx["is_leaps"] = sec.is_leaps(date_cls.today())

    # Bond-specific
    if isinstance(sec, CorporateBond):
        ctx["investment_grade"] = sec.is_investment_grade
        ctx["convertible"] = sec.convertible
        ctx["par_value"] = sec.par_value

    if isinstance(sec, MunicipalBond):
        ctx["investment_grade"] = sec.is_investment_grade
        ctx["par_value"] = sec.par_value

    # Treasury-specific
    if isinstance(sec, USTreasury):
        from datetime import date
        today = date.today()
        ctx["maturity_tier"] = sec.maturity_tier(today)
        ctx["zero_coupon"] = sec.is_zero_coupon
        ctx["years_to_maturity"] = sec.years_to_maturity(today)
        ctx["par_value"] = sec.par_value

    # Agency debt-specific
    if isinstance(sec, AgencyDebt):
        from datetime import date
        today = date.today()
        ctx["product_type"] = sec.product_type
        ctx["is_gnma"] = sec.is_gnma
        ctx["years_to_maturity"] = sec.years_to_maturity(today)
        ctx["par_value"] = sec.par_value
        # Use maturity tiers for margin rate determination
        ytm = sec.years_to_maturity(today)
        if ytm < 5:
            ctx["maturity_tier"] = "under_5y"
        elif ytm < 15:
            ctx["maturity_tier"] = "5y_to_15y"
        elif ytm < 25:
            ctx["maturity_tier"] = "15y_to_25y"
        else:
            ctx["maturity_tier"] = "25y_plus"

    # Security futures-specific
    if isinstance(sec, SecurityFuture):
        ctx["underlying_symbol"] = sec.underlying_symbol
        ctx["contract_size"] = sec.contract_size

    # ETF-specific
    if isinstance(sec, (ETF, ETP)):
        ctx["leverage_factor"] = sec.leverage_factor

    return ctx
