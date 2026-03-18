"""Portfolio aggregation model."""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from paragraph_margin.models.enums import SecurityType
from paragraph_margin.models.positions import Position
from paragraph_margin.money import ZERO


class PortfolioSummary(BaseModel):
    """Aggregated portfolio statistics."""

    account_id: str
    total_long_market_value: Decimal = ZERO
    total_short_market_value: Decimal = ZERO
    total_options_market_value: Decimal = ZERO
    total_bond_market_value: Decimal = ZERO
    total_treasury_market_value: Decimal = ZERO
    total_etf_market_value: Decimal = ZERO
    position_count: int = 0
    unique_underlyings: int = 0

    @classmethod
    def from_positions(cls, account_id: str, positions: list[Position]) -> "PortfolioSummary":
        summary = cls(account_id=account_id, position_count=len(positions))
        underlyings = set()

        for pos in positions:
            mv = pos.market_value
            if pos.is_long:
                summary.total_long_market_value += mv
            else:
                summary.total_short_market_value += mv

            st = pos.security.security_type
            if st == SecurityType.OPTION:
                summary.total_options_market_value += mv
                if hasattr(pos.security, "underlying_symbol"):
                    underlyings.add(getattr(pos.security, "underlying_symbol"))
            elif st in (SecurityType.CORPORATE_BOND, SecurityType.MUNICIPAL_BOND):
                summary.total_bond_market_value += mv
            elif st == SecurityType.US_TREASURY:
                summary.total_treasury_market_value += mv
            elif st in (SecurityType.ETF, SecurityType.ETP):
                summary.total_etf_market_value += mv
            else:
                underlyings.add(pos.security.symbol)

        summary.unique_underlyings = len(underlyings)
        return summary
