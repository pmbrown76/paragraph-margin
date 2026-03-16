"""Account and SMA (Special Memorandum Account) models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from margin_calc_engine.models.enums import AccountType, MarginCallStatus, PositionSide
from margin_calc_engine.models.margin import MarginCall, MarginSummary
from margin_calc_engine.models.positions import Position
from margin_calc_engine.models.snapshots import AccountSnapshot
from margin_calc_engine.models.trades import Broker, Trade
from margin_calc_engine.money import ZERO


class SMA(BaseModel):
    """Special Memorandum Account — tracks excess buying power under Reg T.

    Per Reg T Section 220.5:
    - SMA increases dollar-for-dollar with appreciation above Reg T requirement
    - SMA does NOT decrease when market value drops (high-water mark)
    - SMA can be used to purchase additional securities (buying power = SMA / initial rate)
    - SMA cannot be used to satisfy maintenance margin calls
    """

    balance: Decimal = ZERO
    last_updated: Optional[datetime] = None

    def credit(self, amount: Decimal) -> None:
        """Credit the SMA (deposits, dividends, sale proceeds, excess equity)."""
        self.balance += amount
        self.last_updated = datetime.now()

    def debit(self, amount: Decimal) -> None:
        """Debit the SMA (withdrawals, used for new purchases)."""
        self.balance = max(ZERO, self.balance - amount)
        self.last_updated = datetime.now()


class Account(BaseModel):
    """A client account at the broker-dealer."""

    account_id: str
    client_id: str
    client_name: str = ""
    account_type: AccountType = AccountType.MARGIN
    prime_brokerage: bool = False
    prime_broker: Optional[Broker] = None
    pattern_day_trader: bool = False
    day_trade_count_5d: int = 0  # Day trades in last 5 business days
    minimum_equity: Decimal = Decimal("2000")  # $2,000 standard; $25,000 for PDT
    sma: SMA = SMA()
    positions: list[Position] = []
    open_trades: list[Trade] = []
    intraday_trades: list[Trade] = []  # Confirmed trades applied today
    margin_calls: list[MarginCall] = []
    cash_balance: Decimal = ZERO
    sod_snapshot: Optional[AccountSnapshot] = None  # Start-of-day baseline
    created_at: Optional[datetime] = None

    @property
    def is_margin_account(self) -> bool:
        return self.account_type in (AccountType.MARGIN, AccountType.PORTFOLIO_MARGIN)

    @property
    def is_portfolio_margin(self) -> bool:
        return self.account_type == AccountType.PORTFOLIO_MARGIN

    @property
    def is_cash_account(self) -> bool:
        return self.account_type == AccountType.CASH

    @property
    def long_market_value(self) -> Decimal:
        return sum(
            (p.market_value for p in self.positions if p.side == PositionSide.LONG),
            ZERO,
        )

    @property
    def short_market_value(self) -> Decimal:
        return sum(
            (p.market_value for p in self.positions if p.side == PositionSide.SHORT),
            ZERO,
        )

    @property
    def short_credit_balance(self) -> Decimal:
        """Frozen short sale proceeds = sum of short positions (avg_cost x qty)."""
        return sum(
            (p.average_cost * p.quantity for p in self.positions if p.side == PositionSide.SHORT),
            ZERO,
        )

    @property
    def debit_balance(self) -> Decimal:
        """Amount borrowed from broker for long purchases (positive = in debt)."""
        net = self.cash_balance - self.short_credit_balance
        return (-net) if net < ZERO else ZERO

    @property
    def free_credit_balance(self) -> Decimal:
        """Free cash after netting frozen short proceeds."""
        net = self.cash_balance - self.short_credit_balance
        return net if net > ZERO else ZERO

    @property
    def equity(self) -> Decimal:
        """Account equity = long market value + cash - short market value."""
        return self.long_market_value + self.cash_balance - self.short_market_value

    @property
    def outstanding_margin_calls(self) -> list[MarginCall]:
        return [mc for mc in self.margin_calls if mc.status == MarginCallStatus.OUTSTANDING]

    def get_positions_by_underlying(self, symbol: str) -> list[Position]:
        """Get all positions (stock + options) for a given underlying symbol."""
        result = []
        for p in self.positions:
            if p.security.symbol == symbol:
                result.append(p)
            elif hasattr(p.security, "underlying_symbol"):
                if getattr(p.security, "underlying_symbol") == symbol:
                    result.append(p)
        return result
