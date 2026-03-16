"""Decimal-based money handling to avoid floating-point errors in margin calculations."""

from decimal import Decimal, ROUND_HALF_UP

# Standard precision for margin calculations
MARGIN_PRECISION = Decimal("0.01")


def to_decimal(value: float | int | str | Decimal) -> Decimal:
    """Convert a value to Decimal for precise financial calculations."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_margin(amount: Decimal) -> Decimal:
    """Round a margin amount to 2 decimal places (standard USD precision)."""
    return amount.quantize(MARGIN_PRECISION, rounding=ROUND_HALF_UP)


def pct(rate: Decimal | float, value: Decimal) -> Decimal:
    """Calculate a percentage of a value. rate is expressed as a decimal (0.25 = 25%)."""
    return to_decimal(rate) * value


def max_of(*values: Decimal) -> Decimal:
    """Return the maximum of the given Decimal values."""
    return max(values)


def min_of(*values: Decimal) -> Decimal:
    """Return the minimum of the given Decimal values."""
    return min(values)


ZERO = Decimal("0")
ONE_HUNDRED_PCT = Decimal("1.0")
