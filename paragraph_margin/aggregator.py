"""Margin aggregator — orchestrates two independent margin engines.

The aggregator coordinates:
1. Reg T Engine — initial margin on today's trades only (trade price basis)
2. FINRA 4210 Engine — maintenance margin on all positions (market price basis)

Each engine runs its own independent strategy recognition. A position may appear
in a 4210 strategy but have no Reg T strategy (if the other legs were from prior days).

The aggregator also maintains backward compatibility with the legacy combined API.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from paragraph_margin.models.accounts import Account
from paragraph_margin.models.enums import AccountType, PositionSide
from paragraph_margin.models.margin import MarginRequirement, MarginSummary
from paragraph_margin.models.positions import Position
from paragraph_margin.models.strategies import RecognizedStrategy, StrategyGroup
from paragraph_margin.calculators.finra_4210 import FINRA4210Calculator
from paragraph_margin.calculators.portfolio_margin import PortfolioMarginCalculator
from paragraph_margin.calculators.strategy_margin import StrategyMarginCalculator
from paragraph_margin.calculators.strategy_recognizer import StrategyRecognizer
from paragraph_margin.finra_4210_engine import FINRA4210Engine
from paragraph_margin.calculators.reg_t import RegTCalculator
from paragraph_margin.calculators.sma import SMACalculator
from paragraph_margin.reg_t_engine import RegTEngine
from paragraph_margin.engine.context import build_position_context
from paragraph_margin.engine.evaluator import evaluate_formula
from paragraph_margin.engine.matcher import find_matching_rules
from paragraph_margin.rules.registry import MarginRulesRegistry
from paragraph_margin.rules.schema import RuleConfig
from paragraph_margin.money import ZERO, max_of, round_margin


class MarginAggregator:
    """Orchestrates two independent margin calculation engines.

    - reg_t_engine: Reg T initial margin on today's intraday trades
    - finra_4210_engine: FINRA 4210 maintenance on the full position book

    Each engine has its own strategy recognizer and operates independently.
    The aggregator combines results for the API layer.
    """

    def __init__(self, registry: MarginRulesRegistry) -> None:
        self.registry = registry

        # Independent engines
        self.reg_t_engine = RegTEngine(registry)
        self.finra_4210_engine = FINRA4210Engine(registry)

        # Legacy calculators (still used by some callers)
        self.reg_t = RegTCalculator(registry)
        self.finra_4210 = FINRA4210Calculator(registry)
        self.strategy_recognizer = self.finra_4210_engine.strategy_recognizer
        self.strategy_calculator = self.finra_4210_engine.strategy_calculator
        self.portfolio_margin_calc = PortfolioMarginCalculator()
        self.sma_calc = SMACalculator()
        self._house_rules = registry.house_rules

    def calculate_dual_margin(
        self,
        account: Account,
        underlying_prices: Optional[dict[str, Decimal]] = None,
        as_of: Optional[date] = None,
    ) -> dict:
        """Run both independent margin engines and return combined results."""
        prices = underlying_prices or {}

        # Engine 1: Reg T — today's trades only
        reg_t_summary, reg_t_strategies, intraday_positions = (
            self.reg_t_engine.calculate_account_margin(account, as_of, prices)
        )

        # Engine 2: FINRA 4210 — all positions
        finra_summary, finra_strategies = (
            self.finra_4210_engine.calculate_account_margin(account, prices)
        )

        return {
            "reg_t": {
                "summary": reg_t_summary,
                "strategy_group": reg_t_strategies,
                "intraday_positions": intraday_positions,
            },
            "finra_4210": {
                "summary": finra_summary,
                "strategy_group": finra_strategies,
            },
        }

    # ================================================================
    # Legacy API — backward compatible combined calculation
    # ================================================================

    def calculate_position_margin(
        self,
        position: Position,
        underlying_price: Decimal = ZERO,
    ) -> MarginRequirement:
        """Calculate full margin requirement for a single position (legacy)."""
        # Reg T initial
        reg_t_req = self.reg_t.calculate(position, underlying_price)

        # FINRA 4210 maintenance
        finra_req = self.finra_4210.calculate(position, underlying_price)

        # House margin
        context = build_position_context(position, underlying_price)
        house_matching = find_matching_rules(self._house_rules, context, self.registry.disabled_rule_ids)
        house_margin = ZERO
        for rule in house_matching:
            amount = evaluate_formula(rule, context)
            house_margin = max_of(house_margin, amount)

        # Combine
        all_rule_ids = reg_t_req.rule_ids + finra_req.rule_ids
        all_citations = list(set(reg_t_req.citations + finra_req.citations))

        detail_parts = []
        if reg_t_req.reg_t_initial > ZERO:
            detail_parts.append(f"Reg T Initial: ${reg_t_req.reg_t_initial}")
        if finra_req.finra_4210_maintenance > ZERO:
            detail_parts.append(f"FINRA 4210 Maint: ${finra_req.finra_4210_maintenance}")
        if house_margin > ZERO:
            detail_parts.append(f"House: ${house_margin}")

        return MarginRequirement(
            position_id=position.position_id,
            reg_t_initial=reg_t_req.reg_t_initial,
            finra_4210_maintenance=finra_req.finra_4210_maintenance,
            house_margin=house_margin,
            rule_ids=all_rule_ids,
            citations=all_citations,
            calculation_detail=" | ".join(detail_parts),
        )

    def calculate_strategy_margin(
        self,
        strategy: RecognizedStrategy,
        underlying_price: Decimal = ZERO,
    ) -> MarginRequirement:
        """Calculate full margin requirement for a recognized strategy (legacy)."""
        return self.strategy_calculator.calculate(strategy, underlying_price)

    def calculate_account_margin(
        self,
        account: Account,
        underlying_prices: Optional[dict[str, Decimal]] = None,
    ) -> tuple[MarginSummary, StrategyGroup]:
        """Calculate full margin summary for an account (legacy combined mode)."""
        prices = underlying_prices or {}
        requirements: list[MarginRequirement] = []

        total_reg_t = ZERO
        total_maintenance = ZERO
        total_house = ZERO
        total_pm: Optional[Decimal] = None

        # Portfolio margin calculation (for PM accounts)
        if account.is_portfolio_margin:
            pm_total, pm_groups = self.portfolio_margin_calc.calculate_account_pm(
                account, prices
            )
            total_pm = pm_total

        # Step 1: Recognize strategies from all positions
        strategy_group = self.strategy_recognizer.recognize(
            account.positions, underlying_prices=prices
        )

        # Step 2: Calculate margin for each recognized strategy
        for strategy in strategy_group.strategies:
            u_price = prices.get(strategy.underlying_symbol, ZERO)
            req = self.strategy_calculator.calculate(strategy, u_price)
            requirements.append(req)
            total_reg_t += req.reg_t_initial
            total_maintenance += req.finra_4210_maintenance
            total_house += req.house_margin

        # Step 3: Calculate per-position margin for unmatched positions
        for position in strategy_group.unmatched_positions:
            u_price = self._get_underlying_price(position, prices)
            req = self.calculate_position_margin(position, u_price)
            requirements.append(req)
            total_reg_t += req.reg_t_initial
            total_maintenance += req.finra_4210_maintenance
            total_house += req.house_margin

        summary = MarginSummary(
            account_id=account.account_id,
            as_of=datetime.now(),
            long_market_value=account.long_market_value,
            short_market_value=account.short_market_value,
            cash_balance=account.cash_balance,
            reg_t_initial_requirement=round_margin(total_reg_t),
            maintenance_requirement=round_margin(total_maintenance),
            house_requirement=round_margin(total_house),
            portfolio_margin_requirement=total_pm,
            sma_balance=account.sma.balance,
            requirements=requirements,
        )
        return summary, strategy_group

    @staticmethod
    def _get_underlying_price(
        position: Position, prices: dict[str, Decimal]
    ) -> Decimal:
        """Get the underlying price for a position from the prices dict."""
        price = prices.get(position.security.symbol, ZERO)
        if price > ZERO:
            return price
        if hasattr(position.security, "underlying_symbol"):
            return prices.get(position.security.underlying_symbol, ZERO)
        return ZERO
