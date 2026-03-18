"""Margin requirement and margin call models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from paragraph_margin.models.enums import MarginCallStatus, MarginCallType
from paragraph_margin.money import ZERO


class MarginRequirement(BaseModel):
    """Margin requirement for a single position or strategy."""

    position_id: Optional[str] = None
    strategy_id: Optional[str] = None
    reg_t_initial: Decimal = ZERO
    finra_4210_maintenance: Decimal = ZERO
    house_margin: Decimal = ZERO
    portfolio_margin: Optional[Decimal] = None
    rule_ids: list[str] = []
    citations: list[str] = []
    calculation_detail: str = ""

    @property
    def effective_initial(self) -> Decimal:
        """The binding initial margin = max(Reg T, house initial)."""
        return max(self.reg_t_initial, self.house_margin)

    @property
    def effective_maintenance(self) -> Decimal:
        """The binding maintenance margin."""
        if self.portfolio_margin is not None:
            return max(self.portfolio_margin, self.house_margin)
        return max(self.finra_4210_maintenance, self.house_margin)


class MarginSummary(BaseModel):
    """Aggregated margin summary for an account."""

    account_id: str
    as_of: datetime
    long_market_value: Decimal = ZERO
    short_market_value: Decimal = ZERO
    cash_balance: Decimal = ZERO
    reg_t_initial_requirement: Decimal = ZERO
    maintenance_requirement: Decimal = ZERO
    house_requirement: Decimal = ZERO
    portfolio_margin_requirement: Optional[Decimal] = None
    sma_balance: Decimal = ZERO
    requirements: list[MarginRequirement] = []

    @property
    def equity(self) -> Decimal:
        """Account equity = LMV - debit balance (for long) or credit balance - SMV (for short)."""
        return self.long_market_value + self.cash_balance - self.short_market_value

    @property
    def buying_power(self) -> Decimal:
        """Reg T buying power = SMA / 0.50 = 2x SMA for equities."""
        if self.sma_balance > ZERO:
            return self.sma_balance * 2
        return ZERO

    @property
    def margin_excess_deficit(self) -> Decimal:
        """Positive = excess margin, negative = margin deficiency."""
        return self.equity - self.maintenance_requirement

    @property
    def has_margin_call(self) -> bool:
        return self.equity < self.maintenance_requirement


class MarginCall(BaseModel):
    """A margin call issued to an account."""

    call_id: str
    account_id: str
    call_type: MarginCallType
    amount: Decimal
    issued_at: datetime
    due_date: date
    status: MarginCallStatus = MarginCallStatus.OUTSTANDING
    resolved_at: Optional[datetime] = None
    resolution_detail: str = ""
