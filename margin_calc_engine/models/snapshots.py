"""Start-of-Day (SOD) snapshot models for position and account state."""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, computed_field

from margin_calc_engine.models.enums import PositionSide, SecurityType
from margin_calc_engine.models.securities import Security
from margin_calc_engine.money import ZERO, to_decimal

if TYPE_CHECKING:
    from margin_calc_engine.models.positions import Position


class SODPosition(BaseModel):
    """A frozen snapshot of a position at start of day.

    Immutable record — never modified after creation.
    """

    position_id: str
    account_id: str
    security: Security
    side: PositionSide
    quantity: Decimal
    average_cost: Decimal
    market_price: Decimal  # Previous close / SOD price

    @computed_field  # type: ignore[prop-decorator]
    @property
    def market_value(self) -> Decimal:
        """Market value at SOD."""
        base = self.quantity * self.market_price
        if self.security.security_type == SecurityType.OPTION:
            from margin_calc_engine.models.securities import Option

            if isinstance(self.security, Option):
                return base * to_decimal(self.security.contract_multiplier)
        return base

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cost_basis(self) -> Decimal:
        """Cost basis at SOD."""
        base = self.quantity * self.average_cost
        if self.security.security_type == SecurityType.OPTION:
            from margin_calc_engine.models.securities import Option

            if isinstance(self.security, Option):
                return base * to_decimal(self.security.contract_multiplier)
        return base

    @classmethod
    def from_position(cls, position: "Position") -> "SODPosition":
        """Create a SOD snapshot from a live Position."""
        return cls(
            position_id=position.position_id,
            account_id=position.account_id,
            security=position.security,
            side=position.side,
            quantity=position.quantity,
            average_cost=position.average_cost,
            market_price=position.market_price,
        )


class AccountSnapshot(BaseModel):
    """Start-of-day account snapshot.

    Captured once at SOD (or when the demo initializes).
    Provides the baseline for SOD vs. current comparison.
    """

    account_id: str
    snapshot_date: date
    captured_at: datetime
    positions: list[SODPosition] = []
    cash_balance: Decimal = ZERO
    sma_balance: Decimal = ZERO

    @computed_field  # type: ignore[prop-decorator]
    @property
    def long_market_value(self) -> Decimal:
        return sum(
            (p.market_value for p in self.positions if p.side == PositionSide.LONG),
            ZERO,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def short_market_value(self) -> Decimal:
        return sum(
            (p.market_value for p in self.positions if p.side == PositionSide.SHORT),
            ZERO,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def equity(self) -> Decimal:
        """Account equity at SOD = LMV + cash - SMV."""
        return self.long_market_value + self.cash_balance - self.short_market_value
