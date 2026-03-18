"""Day trading rules — FINRA 4210(f)(8)(B) Pattern Day Trader provisions.

A pattern day trader (PDT) is any customer who executes 4+ day trades within
5 business days, provided the number of day trades represents more than 6%
of the customer's total trades in that period.

Key rules:
- PDT accounts must maintain minimum equity of $25,000
- Day-trading buying power = 4x maintenance margin excess (not Reg T)
- Day-trade calls must be met within 5 business days
- Unmet day-trade calls restrict account to 2x buying power (90-day freeze)
- Cross-guarantees between accounts are not permitted for PDT purposes
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from paragraph_margin.models.accounts import Account
from paragraph_margin.models.enums import TradeSide
from paragraph_margin.models.trades import Trade
from paragraph_margin.money import ZERO, round_margin


# Default constants — used as fallbacks if YAML rules are not loaded.
# When a MarginRulesRegistry is provided, values are read from YAML rules instead.
PDT_MINIMUM_EQUITY = Decimal("25000")
DT_BUYING_POWER_MULTIPLIER = Decimal("4")
RESTRICTED_BUYING_POWER_MULTIPLIER = Decimal("2")
PDT_TRADE_THRESHOLD = 4
PDT_WINDOW_DAYS = 5
PDT_PERCENTAGE_THRESHOLD = Decimal("0.06")

# Rule IDs for traceability
_RULE_PDT_MIN_EQUITY = "4210_pdt_minimum_equity"
_RULE_DT_MARGIN_RATE = "4210_dt_margin_rate"
_RULE_DT_BP_4X = "4210_dt_buying_power_4x"
_RULE_DT_BP_RESTRICTED = "4210_dt_buying_power_restricted"


class DayTrade:
    """Represents a single day trade (round-trip same day)."""

    def __init__(
        self,
        symbol: str,
        buy_trade: Trade,
        sell_trade: Trade,
        quantity: Decimal,
    ) -> None:
        self.symbol = symbol
        self.buy_trade = buy_trade
        self.sell_trade = sell_trade
        self.quantity = quantity
        self.trade_date = buy_trade.trade_date

    @property
    def profit_loss(self) -> Decimal:
        """Gross P&L on the day trade."""
        return (self.sell_trade.price - self.buy_trade.price) * self.quantity

    @property
    def market_value(self) -> Decimal:
        """Market value of the day trade (cost side)."""
        return self.buy_trade.price * self.quantity


class DayTradeDetector:
    """Detects day trades from a list of trades.

    A day trade is the purchase and sale (or short sale and buy-to-cover)
    of the same security on the same day in a margin account.
    """

    def detect_day_trades(self, trades: list[Trade]) -> list[DayTrade]:
        """Identify day trades from a list of trades.

        Groups trades by (security symbol, trade date) and pairs
        buys with sells to identify round-trip day trades.
        """
        day_trades: list[DayTrade] = []

        # Group by (symbol, trade_date)
        grouped: dict[tuple[str, date], list[Trade]] = {}
        for trade in trades:
            key = (trade.security.symbol, trade.trade_date)
            grouped.setdefault(key, []).append(trade)

        for (symbol, trade_date), group_trades in grouped.items():
            buys = [
                t for t in group_trades
                if t.side in (TradeSide.BUY, TradeSide.BUY_TO_COVER)
            ]
            sells = [
                t for t in group_trades
                if t.side in (TradeSide.SELL, TradeSide.SELL_SHORT)
            ]

            if not buys or not sells:
                continue

            # Match buys and sells FIFO
            buy_idx = 0
            sell_idx = 0
            buy_remaining = buys[0].quantity if buys else ZERO
            sell_remaining = sells[0].quantity if sells else ZERO

            while buy_idx < len(buys) and sell_idx < len(sells):
                matched_qty = min(buy_remaining, sell_remaining)
                if matched_qty > ZERO:
                    day_trades.append(DayTrade(
                        symbol=symbol,
                        buy_trade=buys[buy_idx],
                        sell_trade=sells[sell_idx],
                        quantity=matched_qty,
                    ))

                buy_remaining -= matched_qty
                sell_remaining -= matched_qty

                if buy_remaining <= ZERO:
                    buy_idx += 1
                    if buy_idx < len(buys):
                        buy_remaining = buys[buy_idx].quantity

                if sell_remaining <= ZERO:
                    sell_idx += 1
                    if sell_idx < len(sells):
                        sell_remaining = sells[sell_idx].quantity

        return day_trades

    def count_day_trades_in_window(
        self,
        trades: list[Trade],
        as_of: Optional[date] = None,
        window_days: int = PDT_WINDOW_DAYS,
    ) -> int:
        """Count the number of day trades in the rolling window."""
        if as_of is None:
            as_of = date.today()

        # Look back window_days calendar days (approximate for business days)
        start_date = as_of - timedelta(days=window_days * 2)  # generous lookback
        recent_trades = [
            t for t in trades
            if start_date <= t.trade_date <= as_of
        ]

        day_trades = self.detect_day_trades(recent_trades)

        # Count unique day-trade dates within the window
        # Group by date, each date with a day trade counts as 1 day-trade instance
        dt_dates: set[date] = set()
        for dt in day_trades:
            dt_dates.add(dt.trade_date)

        # Filter to only business-day window
        # For simplicity, count the most recent window_days worth of day-trade dates
        sorted_dates = sorted(dt_dates, reverse=True)
        return len([d for d in sorted_dates if d >= as_of - timedelta(days=window_days * 2)])

    def is_pattern_day_trader(
        self,
        trades: list[Trade],
        as_of: Optional[date] = None,
    ) -> bool:
        """Determine if trade history qualifies as Pattern Day Trader.

        FINRA 4210(f)(8)(B)(ii): A pattern day trader is any customer who
        executes 4 or more day trades within 5 business days, provided the
        number of day trades is more than 6% of total trades.
        """
        if as_of is None:
            as_of = date.today()

        start_date = as_of - timedelta(days=PDT_WINDOW_DAYS * 2)
        recent_trades = [
            t for t in trades
            if start_date <= t.trade_date <= as_of
        ]

        if not recent_trades:
            return False

        day_trades = self.detect_day_trades(recent_trades)
        day_trade_count = len(day_trades)

        if day_trade_count < PDT_TRADE_THRESHOLD:
            return False

        # Check 6% threshold
        total_trades = len(recent_trades)
        if total_trades == 0:
            return False

        pct = Decimal(str(day_trade_count)) / Decimal(str(total_trades))
        return pct > PDT_PERCENTAGE_THRESHOLD


class DayTradingBuyingPower:
    """Calculates day-trading buying power per FINRA 4210(f)(8)(B).

    Day-trading buying power = 4x the maintenance margin excess
    in the account as of the close of business of the prior day.

    If a day-trade margin call is outstanding and unmet, buying power
    is restricted to 2x maintenance excess for 90 calendar days.

    When a MarginRulesRegistry is provided, parameters are read from YAML rules
    for full traceability. Otherwise, module-level constants are used as fallbacks.
    """

    def __init__(self, registry=None) -> None:
        self._registry = registry
        # Read parameters from YAML rules if available
        self._pdt_min_equity = PDT_MINIMUM_EQUITY
        self._bp_multiplier = DT_BUYING_POWER_MULTIPLIER
        self._restricted_multiplier = RESTRICTED_BUYING_POWER_MULTIPLIER
        self._dt_margin_rate = Decimal("0.25")
        self._rule_ids: dict[str, str] = {}

        if registry:
            r = registry.get_rule(_RULE_PDT_MIN_EQUITY)
            if r:
                self._pdt_min_equity = Decimal(str(r.formula.amount))
                self._rule_ids["pdt_min_equity"] = r.id

            r = registry.get_rule(_RULE_DT_MARGIN_RATE)
            if r:
                self._dt_margin_rate = Decimal(str(r.formula.rate))
                self._rule_ids["dt_margin_rate"] = r.id

            r = registry.get_rule(_RULE_DT_BP_4X)
            if r and r.formula.multiplier > 0:
                self._bp_multiplier = Decimal(str(r.formula.multiplier))
                self._rule_ids["dt_bp_4x"] = r.id

            r = registry.get_rule(_RULE_DT_BP_RESTRICTED)
            if r and r.formula.multiplier > 0:
                self._restricted_multiplier = Decimal(str(r.formula.multiplier))
                self._rule_ids["dt_bp_restricted"] = r.id

    def calculate_buying_power(
        self,
        account: Account,
        maintenance_requirement: Decimal,
        is_restricted: bool = False,
    ) -> Decimal:
        """Calculate day-trading buying power.

        Args:
            account: The account to calculate for.
            maintenance_requirement: Total maintenance margin requirement.
            is_restricted: True if account has an unmet day-trade call (90-day freeze).

        Returns:
            Day-trading buying power (4x or 2x maintenance excess).
        """
        if not account.pattern_day_trader:
            return ZERO

        equity = account.equity

        # PDT minimum equity check — per YAML rule 4210_pdt_minimum_equity
        if equity < self._pdt_min_equity:
            return ZERO

        # Maintenance excess
        maintenance_excess = equity - maintenance_requirement
        if maintenance_excess <= ZERO:
            return ZERO

        multiplier = (
            self._restricted_multiplier
            if is_restricted
            else self._bp_multiplier
        )

        return round_margin(maintenance_excess * multiplier)

    def calculate_day_trade_margin(
        self,
        day_trades: list[DayTrade],
    ) -> Decimal:
        """Calculate the margin requirement for day trades.

        Per FINRA 4210(f)(8)(B)(iv): The day-trading margin requirement
        is 25% of the cost of all day trades made during the day.
        """
        if not day_trades:
            return ZERO

        total_cost = sum((dt.market_value for dt in day_trades), ZERO)
        return round_margin(total_cost * self._dt_margin_rate)

    def check_day_trade_call(
        self,
        account: Account,
        day_trades: list[DayTrade],
        buying_power_used: Decimal,
        maintenance_requirement: Decimal,
    ) -> Optional[Decimal]:
        """Check if a day-trade margin call is needed.

        A day-trade call is issued when the day's trading activity
        exceeds the account's day-trading buying power.

        Returns the call amount, or None if no call needed.
        """
        bp = self.calculate_buying_power(account, maintenance_requirement)

        if buying_power_used <= bp:
            return None

        # Day-trade call = amount by which activity exceeded buying power
        excess = buying_power_used - bp
        return round_margin(excess)
