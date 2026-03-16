"""Strategy definitions and leg models for multi-leg strategy recognition."""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from margin_calc_engine.models.enums import OptionType, PositionSide, StrategyType
from margin_calc_engine.models.margin import MarginRequirement
from margin_calc_engine.models.positions import Position
from margin_calc_engine.money import ZERO


class StrategyLeg(BaseModel):
    """A single leg of a recognized strategy."""

    position: Position
    role: str = ""  # e.g., "long_call", "short_put", "underlying"
    ratio: int = 1  # Number of contracts/shares in this leg relative to the strategy unit


class RecognizedStrategy(BaseModel):
    """A multi-leg strategy identified by the strategy recognizer."""

    strategy_id: str
    strategy_type: StrategyType
    legs: list[StrategyLeg]
    underlying_symbol: str
    description: str = ""
    max_loss: Optional[Decimal] = None
    max_gain: Optional[Decimal] = None
    breakeven_points: list[Decimal] = []
    margin_requirement: Optional[MarginRequirement] = None

    @property
    def num_legs(self) -> int:
        return len(self.legs)

    @property
    def is_defined_risk(self) -> bool:
        """Whether the strategy has a known maximum loss."""
        return self.max_loss is not None

    @property
    def net_premium(self) -> Decimal:
        """Net premium paid (positive = debit, negative = credit)."""
        total = ZERO
        for leg in self.legs:
            pos = leg.position
            if pos.is_long:
                total += pos.market_value * leg.ratio
            else:
                total -= pos.market_value * leg.ratio
        return total

    @property
    def is_credit_strategy(self) -> bool:
        return self.net_premium < ZERO

    @property
    def is_debit_strategy(self) -> bool:
        return self.net_premium > ZERO


class StrategyGroup(BaseModel):
    """A group of recognized strategies for an account, representing the optimal
    pairing of positions to minimize total margin."""

    account_id: str
    strategies: list[RecognizedStrategy] = []
    unmatched_positions: list[Position] = []
    total_margin: Optional[MarginRequirement] = None
