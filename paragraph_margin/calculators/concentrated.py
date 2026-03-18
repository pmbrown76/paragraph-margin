"""Concentrated account handling — FINRA 4210(f)(6).

Firms must impose additional margin requirements on accounts where a
single position (or combined positions in the same issuer) represents
a significant portion of the account's net equity.

Concentration thresholds:
- Single position > 10% of account equity -> concentrated
- Same issuer > 15% of account equity -> concentrated
- Low-cap + concentrated -> 75% maintenance (vs 25% standard)
- Illiquid + concentrated -> 100% (non-marginable)
"""

from decimal import Decimal
from typing import Optional

from paragraph_margin.models.accounts import Account
from paragraph_margin.models.enums import PositionSide, SecurityType
from paragraph_margin.models.positions import Position
from paragraph_margin.money import ZERO, round_margin


# Default concentration thresholds
SINGLE_POSITION_THRESHOLD = Decimal("0.10")  # 10% of equity
SAME_ISSUER_THRESHOLD = Decimal("0.15")  # 15% of equity

# Margin rates for concentrated positions
CONCENTRATED_LONG_RATE = Decimal("0.40")  # 40% maintenance
CONCENTRATED_SHORT_RATE = Decimal("0.50")  # 50% maintenance
CONCENTRATED_LOW_CAP_RATE = Decimal("0.75")  # 75% for low-cap
CONCENTRATED_ILLIQUID_RATE = Decimal("1.00")  # 100% (non-marginable)

# Standard rates for comparison
STANDARD_LONG_RATE = Decimal("0.25")
STANDARD_SHORT_RATE = Decimal("0.30")


class ConcentrationResult:
    """Result of concentration analysis for a position."""

    def __init__(
        self,
        position: Position,
        is_concentrated: bool,
        concentration_pct: Decimal,
        margin_rate: Decimal,
        standard_rate: Decimal,
        surcharge: Decimal,
        citation: str = "FINRA 4210(f)(6)",
        rule_ids: list[str] | None = None,
    ) -> None:
        self.position = position
        self.is_concentrated = is_concentrated
        self.concentration_pct = concentration_pct
        self.margin_rate = margin_rate
        self.standard_rate = standard_rate
        self.surcharge = surcharge
        self.citation = citation
        self.rule_ids = rule_ids or []

    @property
    def additional_margin(self) -> Decimal:
        """Additional margin above standard rate."""
        return self.surcharge


class ConcentratedAccountCalculator:
    """Detects concentrated positions and calculates surcharges.

    Per FINRA 4210(f)(6), firms must have procedures for reviewing
    accounts with concentrated positions and applying additional
    margin when appropriate.

    When a MarginRulesRegistry is provided, parameters are read from YAML rules
    for full traceability. Otherwise, module-level constants are used as fallbacks.
    """

    def __init__(
        self,
        single_threshold: Decimal = SINGLE_POSITION_THRESHOLD,
        issuer_threshold: Decimal = SAME_ISSUER_THRESHOLD,
        registry=None,
    ) -> None:
        self.single_threshold = single_threshold
        self.issuer_threshold = issuer_threshold
        self._rule_ids: dict[str, str] = {}

        if registry:
            r = registry.get_rule("4210_concentrated_threshold_single")
            if r:
                self.single_threshold = Decimal(str(r.formula.rate))
                self._rule_ids["threshold_single"] = r.id

            r = registry.get_rule("4210_concentrated_threshold_issuer")
            if r:
                self.issuer_threshold = Decimal(str(r.formula.rate))
                self._rule_ids["threshold_issuer"] = r.id

            r = registry.get_rule("4210_concentrated_equity_long")
            if r:
                self._rule_ids["long_rate"] = r.id

            r = registry.get_rule("4210_concentrated_equity_short")
            if r:
                self._rule_ids["short_rate"] = r.id

    def analyze_account(
        self,
        account: Account,
    ) -> list[ConcentrationResult]:
        """Analyze all positions in an account for concentration.

        Returns a list of ConcentrationResult for each position
        that exceeds concentration thresholds.
        """
        equity = account.equity
        if equity <= ZERO:
            return []

        results: list[ConcentrationResult] = []

        # Group positions by issuer (symbol for equities, underlying for options)
        issuer_groups: dict[str, list[Position]] = {}
        for pos in account.positions:
            issuer = self._get_issuer(pos)
            issuer_groups.setdefault(issuer, []).append(pos)

        # Check each position individually
        for pos in account.positions:
            if pos.security.security_type not in (
                SecurityType.EQUITY, SecurityType.ETF, SecurityType.ETP
            ):
                continue

            mv = abs(pos.market_value)
            concentration_pct = mv / equity if equity > ZERO else ZERO

            # Single position concentration check
            is_concentrated = concentration_pct > self.single_threshold

            # Also check issuer-level concentration
            if not is_concentrated:
                issuer = self._get_issuer(pos)
                issuer_mv = sum(
                    abs(p.market_value) for p in issuer_groups.get(issuer, [])
                )
                issuer_pct = issuer_mv / equity if equity > ZERO else ZERO
                is_concentrated = issuer_pct > self.issuer_threshold
                if is_concentrated:
                    concentration_pct = issuer_pct

            if not is_concentrated:
                continue

            # Determine margin rate based on position characteristics
            margin_rate, standard_rate = self._get_rates(pos, concentration_pct)
            surcharge = self._calculate_surcharge(pos, margin_rate, standard_rate)

            # Collect applicable rule IDs for traceability
            result_rule_ids = list(self._rule_ids.values())

            results.append(ConcentrationResult(
                position=pos,
                is_concentrated=True,
                concentration_pct=round_margin(concentration_pct * 100),
                margin_rate=margin_rate,
                standard_rate=standard_rate,
                surcharge=surcharge,
                rule_ids=result_rule_ids,
            ))

        return results

    def calculate_surcharge(
        self,
        position: Position,
        account_equity: Decimal,
    ) -> Decimal:
        """Calculate the concentration surcharge for a single position.

        Returns the additional margin above standard rates.
        """
        if account_equity <= ZERO:
            return ZERO

        mv = abs(position.market_value)
        concentration_pct = mv / account_equity

        if concentration_pct <= self.single_threshold:
            return ZERO

        margin_rate, standard_rate = self._get_rates(position, concentration_pct)
        return self._calculate_surcharge(position, margin_rate, standard_rate)

    def is_position_concentrated(
        self,
        position: Position,
        account_equity: Decimal,
    ) -> bool:
        """Check if a position exceeds the single-position concentration threshold."""
        if account_equity <= ZERO:
            return False
        return abs(position.market_value) / account_equity > self.single_threshold

    def _get_rates(
        self,
        position: Position,
        concentration_pct: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Determine the applicable margin rate for a concentrated position.

        Returns (concentrated_rate, standard_rate).
        """
        is_long = position.side == PositionSide.LONG
        standard_rate = STANDARD_LONG_RATE if is_long else STANDARD_SHORT_RATE

        # Check for special characteristics
        is_low_cap = getattr(position.security, "low_cap", False)
        is_illiquid = getattr(position.security, "illiquid", False)

        if is_illiquid:
            return CONCENTRATED_ILLIQUID_RATE, standard_rate
        elif is_low_cap and is_long:
            return CONCENTRATED_LOW_CAP_RATE, standard_rate
        elif is_long:
            return CONCENTRATED_LONG_RATE, standard_rate
        else:
            return CONCENTRATED_SHORT_RATE, standard_rate

    @staticmethod
    def _calculate_surcharge(
        position: Position,
        margin_rate: Decimal,
        standard_rate: Decimal,
    ) -> Decimal:
        """Calculate the dollar surcharge above standard maintenance."""
        mv = abs(position.market_value)
        concentrated_margin = round_margin(mv * margin_rate)
        standard_margin = round_margin(mv * standard_rate)
        return max(ZERO, concentrated_margin - standard_margin)

    @staticmethod
    def _get_issuer(position: Position) -> str:
        """Get the issuer symbol for grouping."""
        if hasattr(position.security, "underlying_symbol"):
            return getattr(position.security, "underlying_symbol")
        return position.security.symbol
