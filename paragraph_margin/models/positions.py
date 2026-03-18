"""Position and lot models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, computed_field

from paragraph_margin.models.enums import PositionSide, SecurityType
from paragraph_margin.models.securities import Security
from paragraph_margin.money import ZERO, to_decimal


class Lot(BaseModel):
    """Individual tax lot within a position."""

    lot_id: str
    quantity: Decimal
    cost_basis_per_unit: Decimal
    acquired_date: date

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_cost_basis(self) -> Decimal:
        return self.quantity * self.cost_basis_per_unit


class Position(BaseModel):
    """A position in a security held in an account."""

    position_id: str
    account_id: str
    security: Security
    side: PositionSide
    quantity: Decimal
    average_cost: Decimal
    market_price: Decimal = ZERO
    lots: list[Lot] = []
    opened_date: date = date.today()  # noqa: DTZ011
    last_updated: Optional[datetime] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def market_value(self) -> Decimal:
        """Current market value of the position.

        Fixed income: qty * (market_price / 100) * par_value (prices are % of par)
        Options: qty * market_price * contract_multiplier
        Other: qty * market_price
        """
        if self.security.is_fixed_income:
            par = getattr(self.security, 'par_value', Decimal("1000"))
            return self.quantity * (self.market_price / Decimal("100")) * par
        base = self.quantity * self.market_price
        if self.security.security_type == SecurityType.OPTION:
            from paragraph_margin.models.securities import Option
            if isinstance(self.security, Option):
                return base * to_decimal(self.security.contract_multiplier)
        return base

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cost_basis(self) -> Decimal:
        """Total cost basis of the position.

        Fixed income: qty * (average_cost / 100) * par_value
        Options: qty * average_cost * contract_multiplier
        Other: qty * average_cost
        """
        if self.security.is_fixed_income:
            par = getattr(self.security, 'par_value', Decimal("1000"))
            return self.quantity * (self.average_cost / Decimal("100")) * par
        base = self.quantity * self.average_cost
        if self.security.security_type == SecurityType.OPTION:
            from paragraph_margin.models.securities import Option
            if isinstance(self.security, Option):
                return base * to_decimal(self.security.contract_multiplier)
        return base

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized P&L."""
        if self.side == PositionSide.LONG:
            return self.market_value - self.cost_basis
        else:  # SHORT
            return self.cost_basis - self.market_value

    @property
    def is_long(self) -> bool:
        return self.side == PositionSide.LONG

    @property
    def is_short(self) -> bool:
        return self.side == PositionSide.SHORT

    @property
    def underlying_market_value(self) -> Decimal:
        """For options, the market value of the underlying shares controlled.
        For non-options, same as market_value."""
        if self.security.security_type == SecurityType.OPTION:
            from paragraph_margin.models.securities import Option
            if isinstance(self.security, Option):
                # This would need the underlying price passed in;
                # for now return 0 as a placeholder - the engine will calculate this
                return ZERO
        return self.market_value
