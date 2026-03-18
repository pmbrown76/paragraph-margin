"""Portfolio margin calculator — OCC TIMS-based methodology per FINRA 4210(g).

Portfolio margining uses the OCC's Theoretical Intermarket Margining System (TIMS)
to calculate margin based on the potential loss of a portfolio under various stress
scenarios, rather than per-position percentage requirements.

Key concepts:
- Positions are grouped by "product group" (underlying + related instruments)
- Each group is stressed with price moves of ±15% (equities) in 10 equidistant steps
- The theoretical loss at each scenario point is computed
- Margin = worst-case theoretical loss across all scenarios
- Cross-product offsets reduce margin when positions hedge each other

References:
- FINRA Rule 4210(g): Portfolio Margin Requirements
- OCC TIMS methodology document
- SEC Rule 15c3-1a: Portfolio margin pilot programs
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from paragraph_margin.models.accounts import Account
from paragraph_margin.models.enums import OptionType, PositionSide, SecurityType
from paragraph_margin.models.margin import MarginRequirement
from paragraph_margin.models.positions import Position
from paragraph_margin.models.securities import ETF, ETP, Equity, Option
from paragraph_margin.money import ZERO, max_of, round_margin


# TIMS stress parameters by asset class
_EQUITY_STRESS_PCT = Decimal("0.15")      # ±15% for equities
_BROAD_INDEX_STRESS_PCT = Decimal("0.08") # ±8% for broad-based indices
_ETF_STRESS_PCT = Decimal("0.15")         # ±15% for ETFs (scaled by leverage)
_CONCENTRATION_CHARGE = Decimal("0.30")   # 30% surcharge for concentrated positions
_MINIMUM_PM_PCT = Decimal("0.0375")       # 3.75% minimum for broad-based
_NUM_SCENARIOS = 10                        # Number of equidistant points per direction


@dataclass
class ScenarioResult:
    """Result of evaluating a single stress scenario."""
    shock_pct: Decimal
    theoretical_pnl: Decimal
    theoretical_value: Decimal


@dataclass
class ProductGroupResult:
    """Margin result for a product group (positions sharing an underlying)."""
    underlying_symbol: str
    positions: list[Position]
    scenarios: list[ScenarioResult]
    worst_case_loss: Decimal
    margin_requirement: Decimal
    stress_range: Decimal


class PortfolioMarginCalculator:
    """TIMS-based portfolio margin calculator per FINRA 4210(g).

    Eligible accounts: AccountType.PORTFOLIO_MARGIN
    Minimum equity: $500,000 (typically; not enforced here — that's an account-level check)

    Algorithm:
    1. Group positions by underlying
    2. For each group, determine stress range (±15% for equities, ±8% for broad index)
    3. Generate 10 equidistant scenario points from -range to +range
    4. Calculate theoretical portfolio P&L at each point
    5. Group margin = worst-case (maximum) loss
    6. Total PM = sum of all group margins
    """

    def calculate_account_pm(
        self,
        account: Account,
        underlying_prices: Optional[dict[str, Decimal]] = None,
    ) -> tuple[Decimal, list[ProductGroupResult]]:
        """Calculate portfolio margin for all positions.

        Returns (total_pm_requirement, group_results).
        """
        prices = underlying_prices or {}
        groups = self._group_by_underlying(account.positions)
        results: list[ProductGroupResult] = []
        total_pm = ZERO

        for underlying_sym, positions in groups.items():
            u_price = self._resolve_underlying_price(underlying_sym, positions, prices)
            if u_price <= ZERO:
                continue

            stress = self._get_stress_range(underlying_sym, positions)
            scenarios = self._run_scenarios(positions, u_price, stress)

            worst_loss = max((-s.theoretical_pnl for s in scenarios), default=ZERO)
            worst_loss = max_of(worst_loss, ZERO)  # Can't be negative

            # Apply minimum requirement (3.75% of notional for broad-based)
            min_req = self._minimum_requirement(positions, u_price)
            group_margin = max_of(worst_loss, min_req)

            results.append(ProductGroupResult(
                underlying_symbol=underlying_sym,
                positions=positions,
                scenarios=scenarios,
                worst_case_loss=worst_loss,
                margin_requirement=round_margin(group_margin),
                stress_range=stress,
            ))
            total_pm += group_margin

        return round_margin(total_pm), results

    def calculate_position_pm(
        self,
        position: Position,
        underlying_price: Decimal = ZERO,
    ) -> MarginRequirement:
        """Calculate portfolio margin for a single position."""
        u_price = underlying_price if underlying_price > ZERO else position.market_price
        stress = self._get_stress_range_for_position(position)
        scenarios = self._run_scenarios([position], u_price, stress)

        worst_loss = max((-s.theoretical_pnl for s in scenarios), default=ZERO)
        worst_loss = max_of(worst_loss, ZERO)

        return MarginRequirement(
            position_id=position.position_id,
            portfolio_margin=round_margin(worst_loss),
            citations=["FINRA 4210(g)"],
            calculation_detail=f"PM TIMS: ±{stress*100:.0f}% stress, worst loss ${worst_loss:,.2f}",
        )

    # --- Internal ---

    def _group_by_underlying(self, positions: list[Position]) -> dict[str, list[Position]]:
        """Group positions by their effective underlying symbol."""
        groups: dict[str, list[Position]] = {}
        for pos in positions:
            sym = self._get_underlying_symbol(pos)
            groups.setdefault(sym, []).append(pos)
        return groups

    @staticmethod
    def _get_underlying_symbol(position: Position) -> str:
        """Get the underlying symbol for grouping."""
        sec = position.security
        if isinstance(sec, Option):
            return sec.underlying_symbol
        return sec.symbol

    def _resolve_underlying_price(
        self,
        symbol: str,
        positions: list[Position],
        prices: dict[str, Decimal],
    ) -> Decimal:
        """Find the underlying price from prices dict or position data."""
        if symbol in prices:
            return prices[symbol]
        # Look for a non-option position with a market price
        for pos in positions:
            if not isinstance(pos.security, Option):
                return pos.market_price
        # For option-only groups, use the first option's underlying price estimate
        for pos in positions:
            if pos.market_price > ZERO:
                return pos.market_price
        return ZERO

    def _get_stress_range(self, symbol: str, positions: list[Position]) -> Decimal:
        """Determine stress range for a product group."""
        # Check if any position is on a broad-based index
        for pos in positions:
            sec = pos.security
            if isinstance(sec, Option) and sec.is_index_option and sec.is_broad_based_index:
                return _BROAD_INDEX_STRESS_PCT
            if isinstance(sec, ETF) and sec.is_leveraged:
                return _ETF_STRESS_PCT * Decimal(str(abs(sec.leverage_factor)))

        return _EQUITY_STRESS_PCT

    def _get_stress_range_for_position(self, position: Position) -> Decimal:
        """Stress range for a single position."""
        sec = position.security
        if isinstance(sec, Option):
            if sec.is_index_option and sec.is_broad_based_index:
                return _BROAD_INDEX_STRESS_PCT
            if isinstance(sec.underlying, ETF) and sec.underlying.is_leveraged:
                return _ETF_STRESS_PCT * Decimal(str(abs(sec.underlying.leverage_factor)))
        if isinstance(sec, ETF) and sec.is_leveraged:
            return _ETF_STRESS_PCT * Decimal(str(abs(sec.leverage_factor)))
        return _EQUITY_STRESS_PCT

    def _run_scenarios(
        self,
        positions: list[Position],
        underlying_price: Decimal,
        stress_range: Decimal,
    ) -> list[ScenarioResult]:
        """Evaluate the portfolio at each stress scenario point."""
        results = []
        # Generate equidistant points: -stress to +stress
        step = stress_range / _NUM_SCENARIOS
        for i in range(-_NUM_SCENARIOS, _NUM_SCENARIOS + 1):
            shock = step * i
            shocked_price = underlying_price * (Decimal("1") + shock)
            if shocked_price < ZERO:
                shocked_price = ZERO

            pnl = self._portfolio_pnl(positions, underlying_price, shocked_price)
            results.append(ScenarioResult(
                shock_pct=shock,
                theoretical_pnl=pnl,
                theoretical_value=shocked_price,
            ))

        return results

    def _portfolio_pnl(
        self,
        positions: list[Position],
        current_price: Decimal,
        scenario_price: Decimal,
    ) -> Decimal:
        """Calculate total P&L of positions at a given scenario price."""
        total_pnl = ZERO
        for pos in positions:
            total_pnl += self._position_pnl(pos, current_price, scenario_price)
        return total_pnl

    def _position_pnl(
        self,
        position: Position,
        current_price: Decimal,
        scenario_price: Decimal,
    ) -> Decimal:
        """Calculate P&L for a single position at a scenario price."""
        sec = position.security
        qty = position.quantity
        sign = Decimal("1") if position.is_long else Decimal("-1")

        if isinstance(sec, Option):
            return self._option_pnl(position, current_price, scenario_price) * sign

        # Equity / ETF: P&L = qty * (scenario - current) * sign
        return qty * (scenario_price - current_price) * sign

    def _option_pnl(
        self,
        position: Position,
        current_price: Decimal,
        scenario_price: Decimal,
    ) -> Decimal:
        """Calculate option P&L at a scenario price using intrinsic value.

        At expiry or for stress testing, option value = max(intrinsic, 0).
        For simplicity, we use intrinsic value minus current premium as P&L.
        """
        sec = position.security
        if not isinstance(sec, Option):
            return ZERO

        qty = position.quantity
        multiplier = Decimal(str(sec.contract_multiplier))
        current_premium = position.market_price * multiplier * qty

        # Intrinsic value at scenario price
        if sec.option_type == OptionType.CALL:
            scenario_intrinsic = max_of(scenario_price - sec.strike, ZERO)
        else:
            scenario_intrinsic = max_of(sec.strike - scenario_price, ZERO)

        scenario_value = scenario_intrinsic * multiplier * qty

        # P&L = change in value
        return scenario_value - current_premium

    def _minimum_requirement(
        self,
        positions: list[Position],
        underlying_price: Decimal,
    ) -> Decimal:
        """Calculate minimum PM requirement (3.75% of notional for broad-based)."""
        total_notional = ZERO
        for pos in positions:
            sec = pos.security
            if isinstance(sec, Option):
                notional = underlying_price * Decimal(str(sec.contract_multiplier)) * pos.quantity
            else:
                notional = pos.quantity * underlying_price
            total_notional += notional

        return total_notional * _MINIMUM_PM_PCT
