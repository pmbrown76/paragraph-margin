"""Reg T Margin Engine — computes initial margin on today's trades only.

Regulation T (12 CFR Part 220) governs initial margin requirements at the time
of trade execution. This engine:

1. Takes only today's intraday trades as input
2. Aggregates trades into net intraday positions (by symbol + side)
3. Runs strategy recognition on those intraday positions
4. Calculates Reg T initial margin per strategy or per position
5. Uses trade price (not EOD price) as the margin basis

This engine operates independently from the FINRA 4210 engine.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from paragraph_margin.models.accounts import Account
from paragraph_margin.models.enums import PositionSide, TradeSide, TradeStatus
from paragraph_margin.models.margin import MarginRequirement, MarginSummary
from paragraph_margin.models.positions import Position
from paragraph_margin.models.strategies import RecognizedStrategy, StrategyGroup
from paragraph_margin.models.trades import Trade
from paragraph_margin.calculators.strategy_recognizer import StrategyRecognizer
from paragraph_margin.calculators.reg_t import RegTCalculator
from paragraph_margin.engine.context import build_position_context
from paragraph_margin.engine.evaluator import evaluate_formula
from paragraph_margin.engine.matcher import find_matching_rules
from paragraph_margin.rules.registry import MarginRulesRegistry
from paragraph_margin.money import ZERO, max_of, round_margin


class RegTEngine:
    """Reg T initial margin engine — operates on today's trades only."""

    def __init__(self, registry: MarginRulesRegistry) -> None:
        self._registry = registry
        self._calculator = RegTCalculator(registry)
        self._strategy_recognizer = StrategyRecognizer()
        self._house_rules = registry.house_rules

    def calculate_account_margin(
        self,
        account: Account,
        as_of: Optional[date] = None,
        underlying_prices: Optional[dict[str, Decimal]] = None,
    ) -> tuple[MarginSummary, StrategyGroup, list[Position]]:
        """Calculate Reg T initial margin for today's trade activity."""
        trade_date = as_of or date.today()
        prices = underlying_prices or {}

        # Step 1: Extract today's trades and build intraday positions
        intraday_positions = self._build_intraday_positions(account, trade_date)

        if not intraday_positions:
            return (
                MarginSummary(
                    account_id=account.account_id,
                    as_of=datetime.now(),
                    long_market_value=account.long_market_value,
                    short_market_value=account.short_market_value,
                    cash_balance=account.cash_balance,
                    sma_balance=account.sma.balance,
                ),
                StrategyGroup(account_id=account.account_id, strategies=[], unmatched_positions=[]),
                [],
            )

        # Step 2: Run strategy recognition on intraday positions only
        strategy_group = self._strategy_recognizer.recognize(
            intraday_positions, underlying_prices=prices
        )

        # Step 3: Calculate margin
        requirements: list[MarginRequirement] = []
        total_reg_t = ZERO
        total_house = ZERO

        for strategy in strategy_group.strategies:
            u_price = prices.get(strategy.underlying_symbol, ZERO)
            req = self._calculate_strategy_margin(strategy, u_price)
            requirements.append(req)
            total_reg_t += req.reg_t_initial
            total_house += req.house_margin

        for position in strategy_group.unmatched_positions:
            u_price = self._get_underlying_price(position, prices)
            req = self._calculate_position_margin(position, u_price)
            requirements.append(req)
            total_reg_t += req.reg_t_initial
            total_house += req.house_margin

        summary = MarginSummary(
            account_id=account.account_id,
            as_of=datetime.now(),
            long_market_value=account.long_market_value,
            short_market_value=account.short_market_value,
            cash_balance=account.cash_balance,
            reg_t_initial_requirement=round_margin(total_reg_t),
            house_requirement=round_margin(total_house),
            sma_balance=account.sma.balance,
            requirements=requirements,
        )
        return summary, strategy_group, intraday_positions

    def _build_intraday_positions(
        self, account: Account, trade_date: date
    ) -> list[Position]:
        """Aggregate today's trades into net intraday positions."""
        groups: dict[tuple[str, str], dict] = {}

        for trade in account.intraday_trades:
            if trade.status == TradeStatus.DK:
                continue
            if trade.trade_date != trade_date:
                continue
            if trade.side not in (TradeSide.BUY, TradeSide.SELL_SHORT):
                continue

            target_side = (
                PositionSide.LONG if trade.side == TradeSide.BUY else PositionSide.SHORT
            )
            key = (trade.security.symbol, target_side.value)

            if key not in groups:
                groups[key] = {
                    "security": trade.security,
                    "side": target_side,
                    "quantity": ZERO,
                    "total_value": ZERO,
                }
            groups[key]["quantity"] += trade.quantity
            groups[key]["total_value"] += trade.quantity * trade.price

        positions: list[Position] = []
        for (symbol, side_val), info in groups.items():
            qty = info["quantity"]
            if qty <= ZERO:
                continue
            avg_price = info["total_value"] / qty
            pos = Position(
                position_id=f"regt_intraday_{symbol}_{side_val}",
                account_id=account.account_id,
                security=info["security"],
                side=PositionSide(side_val),
                quantity=qty,
                average_cost=avg_price,
                market_price=avg_price,  # Reg T uses trade price
            )
            positions.append(pos)

        return positions

    def _calculate_position_margin(
        self, position: Position, underlying_price: Decimal = ZERO
    ) -> MarginRequirement:
        """Calculate Reg T margin for a single intraday position."""
        reg_t_req = self._calculator.calculate(position, underlying_price)

        # House margin
        context = build_position_context(position, underlying_price)
        house_matching = find_matching_rules(self._house_rules, context, self._registry.disabled_rule_ids)
        house_margin = ZERO
        for rule in house_matching:
            amount = evaluate_formula(rule, context)
            house_margin = max_of(house_margin, amount)

        return MarginRequirement(
            position_id=position.position_id,
            reg_t_initial=reg_t_req.reg_t_initial,
            house_margin=house_margin,
            rule_ids=reg_t_req.rule_ids,
            citations=reg_t_req.citations,
            calculation_detail=reg_t_req.calculation_detail,
        )

    def _calculate_strategy_margin(
        self, strategy: RecognizedStrategy, underlying_price: Decimal = ZERO
    ) -> MarginRequirement:
        """Calculate Reg T margin for a strategy composed of today's trades."""
        from paragraph_margin.calculators.strategy_margin import StrategyMarginCalculator

        strat_calc = StrategyMarginCalculator(self._registry)
        req = strat_calc.calculate(strategy, underlying_price)

        return MarginRequirement(
            position_id=strategy.strategy_id,
            strategy_id=strategy.strategy_id,
            reg_t_initial=req.finra_4210_maintenance,
            house_margin=req.house_margin,
            rule_ids=req.rule_ids,
            citations=req.citations,
            calculation_detail=f"Reg T Strategy | {req.calculation_detail}",
        )

    @staticmethod
    def _get_underlying_price(
        position: Position, prices: dict[str, Decimal]
    ) -> Decimal:
        price = prices.get(position.security.symbol, ZERO)
        if price > ZERO:
            return price
        if hasattr(position.security, "underlying_symbol"):
            return prices.get(position.security.underlying_symbol, ZERO)
        return ZERO
