"""Trade and execution models for Done With / Done Away flows."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from paragraph_margin.models.enums import ExecutionType, TradeSide, TradeStatus
from paragraph_margin.models.securities import Security
from paragraph_margin.money import ZERO


class Broker(BaseModel):
    """Broker-dealer entity."""

    broker_id: str
    name: str
    mpid: str  # Market Participant Identifier
    is_prime_broker: bool = False


class Trade(BaseModel):
    """A trade execution."""

    trade_id: str
    account_id: str
    security: Security
    side: TradeSide
    quantity: Decimal
    price: Decimal
    trade_date: date
    settlement_date: Optional[date] = None
    execution_type: ExecutionType = ExecutionType.DONE_WITH
    executing_broker: Optional[Broker] = None
    clearing_broker: Optional[Broker] = None
    status: TradeStatus = TradeStatus.PENDING
    accrued_interest: Decimal = ZERO  # Per-bond accrued interest
    commission: Decimal = ZERO
    fees: Decimal = ZERO
    dk_reason: Optional[str] = None  # Reason if DK'd
    confirmed_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None
    entry_date: Optional[datetime] = None  # When the order was entered

    @property
    def is_done_away(self) -> bool:
        return self.execution_type == ExecutionType.DONE_AWAY

    @property
    def is_done_with(self) -> bool:
        return self.execution_type == ExecutionType.DONE_WITH

    @property
    def is_buy(self) -> bool:
        return self.side in (TradeSide.BUY, TradeSide.BUY_TO_COVER)

    @property
    def is_sell(self) -> bool:
        return self.side in (TradeSide.SELL, TradeSide.SELL_SHORT)

    @property
    def gross_amount(self) -> Decimal:
        """Gross trade amount.

        For fixed income: qty * (price / 100) * par_value + accrued_interest * qty
        For other securities: qty * price
        """
        if self.security.is_fixed_income:
            par = getattr(self.security, 'par_value', Decimal("1000"))
            principal = self.quantity * (self.price / Decimal("100")) * par
            return principal + self.accrued_interest * self.quantity
        return self.quantity * self.price

    @property
    def net_amount(self) -> Decimal:
        """Net trade amount including commissions and fees."""
        if self.is_buy:
            return self.gross_amount + self.commission + self.fees
        else:
            return self.gross_amount - self.commission - self.fees
