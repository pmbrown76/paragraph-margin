"""Special Memorandum Account (SMA) calculator.

Per Reg T Section 220.5:
- SMA tracks excess buying power in margin accounts
- Credits: dividends, interest, sale proceeds, excess equity above Reg T
- Debits: cash withdrawals, new purchases applied against SMA
- SMA does NOT decrease when market value drops (high-water mark mechanism)
- Buying power = SMA / initial_margin_rate (e.g., SMA / 0.50 = 2x for equities)
- SMA cannot be used to satisfy maintenance margin calls
"""

from decimal import Decimal
from typing import Optional

from margin_calc_engine.models.accounts import SMA, Account
from margin_calc_engine.money import ZERO, max_of, pct, round_margin, to_decimal


REG_T_EQUITY_RATE = Decimal("0.50")


class SMACalculator:
    """Calculates and maintains the Special Memorandum Account balance."""

    def __init__(self, initial_margin_rate: Decimal = REG_T_EQUITY_RATE) -> None:
        self.initial_margin_rate = initial_margin_rate

    def compute_loan_value(self, long_market_value: Decimal) -> Decimal:
        """Loan value = (1 - Reg T rate) * LMV = 50% of LMV for equities."""
        return round_margin(long_market_value * (Decimal("1") - self.initial_margin_rate))

    def compute_reg_t_requirement(self, long_market_value: Decimal) -> Decimal:
        """Reg T equity requirement = rate * LMV."""
        return round_margin(pct(self.initial_margin_rate, long_market_value))

    def compute_excess_equity(
        self,
        long_market_value: Decimal,
        debit_balance: Decimal,
    ) -> Decimal:
        """Excess equity above Reg T = Equity - Reg T Requirement."""
        loan_value = self.compute_loan_value(long_market_value)
        return round_margin(loan_value - debit_balance)

    def update_sma_for_market_change(
        self,
        sma: SMA,
        long_market_value: Decimal,
        debit_balance: Decimal,
    ) -> Decimal:
        """Update SMA after market value change.

        Key Reg T SMA rule: SMA increases when excess equity rises above
        the current SMA, but NEVER decreases due to market drops.
        """
        excess = self.compute_excess_equity(long_market_value, debit_balance)

        # SMA only increases, never decreases due to market decline
        if excess > sma.balance:
            sma.credit(excess - sma.balance)

        return sma.balance

    def credit_deposit(self, sma: SMA, amount: Decimal) -> None:
        """Credit SMA for a cash deposit."""
        sma.credit(amount)

    def credit_sale_proceeds(self, sma: SMA, proceeds: Decimal) -> None:
        """Credit SMA for sale proceeds (the loan value of the sold securities)."""
        loan_value_released = round_margin(proceeds * (Decimal("1") - self.initial_margin_rate))
        sma.credit(loan_value_released)

    def credit_dividend(self, sma: SMA, amount: Decimal) -> None:
        """Credit SMA for dividend/interest received."""
        sma.credit(amount)

    def debit_purchase(self, sma: SMA, purchase_amount: Decimal) -> Decimal:
        """Debit SMA for a new purchase. Returns the margin required (amount not covered by SMA)."""
        reg_t_required = round_margin(pct(self.initial_margin_rate, purchase_amount))
        sma_available = sma.balance

        if sma_available >= reg_t_required:
            sma.debit(reg_t_required)
            return ZERO  # Fully covered by SMA
        else:
            sma.debit(sma_available)
            return round_margin(reg_t_required - sma_available)

    def debit_withdrawal(self, sma: SMA, amount: Decimal) -> bool:
        """Debit SMA for a cash withdrawal. Returns True if permitted."""
        if amount <= sma.balance:
            sma.debit(amount)
            return True
        return False

    def buying_power(self, sma: SMA) -> Decimal:
        """Calculate buying power from current SMA balance."""
        if sma.balance <= ZERO:
            return ZERO
        return round_margin(sma.balance / self.initial_margin_rate)
