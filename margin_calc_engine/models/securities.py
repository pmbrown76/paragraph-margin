"""Security type hierarchy for all supported asset classes."""

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from margin_calc_engine.models.enums import (
    BondRating,
    ExerciseStyle,
    INVESTMENT_GRADE_RATINGS,
    IndexType,
    OptionType,
    SecurityType,
    SettlementType,
    TreasuryType,
)


class Security(BaseModel):
    """Base security model."""

    security_id: str
    symbol: str
    security_type: SecurityType
    description: str = ""
    marginable: bool = True


class Equity(Security):
    """Equity security (common/preferred stock)."""

    security_type: SecurityType = SecurityType.EQUITY
    exchange: str = ""
    shares_outstanding: Optional[int] = None
    market_cap: Optional[Decimal] = None


class Option(Security):
    """Listed option contract."""

    security_type: SecurityType = SecurityType.OPTION
    underlying: Security
    underlying_symbol: str
    option_type: OptionType
    strike: Decimal
    expiration: date
    exercise_style: ExerciseStyle = ExerciseStyle.AMERICAN
    settlement_type: SettlementType = SettlementType.PHYSICAL
    contract_multiplier: int = 100
    index_type: Optional[IndexType] = None

    @property
    def is_broad_based_index(self) -> bool:
        return self.index_type == IndexType.BROAD_BASED

    @property
    def is_narrow_based_index(self) -> bool:
        return self.index_type == IndexType.NARROW_BASED

    @property
    def is_index_option(self) -> bool:
        return self.index_type is not None

    @property
    def is_cash_settled(self) -> bool:
        return self.settlement_type == SettlementType.CASH

    @property
    def is_european(self) -> bool:
        return self.exercise_style == ExerciseStyle.EUROPEAN

    def is_expired(self, as_of: date) -> bool:
        return as_of > self.expiration

    def days_to_expiration(self, as_of: date) -> int:
        return max(0, (self.expiration - as_of).days)

    def months_to_expiration(self, as_of: date) -> float:
        return self.days_to_expiration(as_of) / 30.44

    def is_leaps(self, as_of: date) -> bool:
        """LEAPS are options with > 9 months to expiration."""
        return self.months_to_expiration(as_of) > 9


class CorporateBond(Security):
    """Corporate debt security."""

    security_type: SecurityType = SecurityType.CORPORATE_BOND
    issuer: str = ""
    coupon_rate: Decimal = Decimal("0")
    maturity_date: date
    par_value: Decimal = Decimal("1000")
    rating: BondRating = BondRating.NR
    convertible: bool = False
    conversion_ratio: Optional[Decimal] = None
    conversion_underlying: Optional[str] = None

    @property
    def is_investment_grade(self) -> bool:
        return self.rating in INVESTMENT_GRADE_RATINGS

    def years_to_maturity(self, as_of: date) -> float:
        return max(0, (self.maturity_date - as_of).days / 365.25)


class MunicipalBond(Security):
    """Municipal bond security."""

    security_type: SecurityType = SecurityType.MUNICIPAL_BOND
    issuer: str = ""
    state: str = ""
    coupon_rate: Decimal = Decimal("0")
    maturity_date: date
    par_value: Decimal = Decimal("1000")
    rating: BondRating = BondRating.NR
    taxable: bool = False
    general_obligation: bool = True  # GO vs revenue bond

    @property
    def is_investment_grade(self) -> bool:
        return self.rating in INVESTMENT_GRADE_RATINGS

    def years_to_maturity(self, as_of: date) -> float:
        return max(0, (self.maturity_date - as_of).days / 365.25)


class USTreasury(Security):
    """US Treasury security."""

    security_type: SecurityType = SecurityType.US_TREASURY
    treasury_type: TreasuryType
    coupon_rate: Decimal = Decimal("0")
    maturity_date: date
    par_value: Decimal = Decimal("1000")
    marginable: bool = True  # Treasuries are always marginable (exempt securities)

    def years_to_maturity(self, as_of: date) -> float:
        return max(0, (self.maturity_date - as_of).days / 365.25)

    def maturity_tier(self, as_of: date) -> str:
        """Return the FINRA 4210 maturity tier for margin calculation."""
        ytm = self.years_to_maturity(as_of)
        if ytm < 1:
            return "under_1y"
        elif ytm < 3:
            return "1y_to_3y"
        elif ytm < 5:
            return "3y_to_5y"
        elif ytm < 10:
            return "5y_to_10y"
        elif ytm < 20:
            return "10y_to_20y"
        else:
            return "20y_plus"

    @property
    def is_zero_coupon(self) -> bool:
        return self.coupon_rate == Decimal("0")


class AgencyDebt(Security):
    """Agency debt and mortgage-related securities (GNMA, FNMA, FHLMC)."""

    security_type: SecurityType = SecurityType.AGENCY_DEBT
    issuer: str = ""  # GNMA, FNMA, FHLMC
    product_type: str = ""  # pass_through, cmo, tba, debenture
    coupon_rate: Decimal = Decimal("0")
    maturity_date: date
    par_value: Decimal = Decimal("1000")
    is_gnma: bool = False  # GNMA has full faith & credit guarantee
    average_life_years: Optional[float] = None  # For CMOs/MBS

    def years_to_maturity(self, as_of: date) -> float:
        """Return average life if available, otherwise years to maturity."""
        if self.average_life_years is not None:
            return self.average_life_years
        return max(0, (self.maturity_date - as_of).days / 365.25)


class SecurityFuture(Security):
    """Single stock future or narrow-based security index future."""

    security_type: SecurityType = SecurityType.SECURITY_FUTURE
    underlying_symbol: str = ""
    contract_size: int = 100  # typically 100 shares
    expiration: date
    settlement_type: SettlementType = SettlementType.PHYSICAL


class ETF(Security):
    """Exchange-Traded Fund."""

    security_type: SecurityType = SecurityType.ETF
    underlying_index: str = ""
    leverage_factor: int = 1  # 1, 2, 3 for leveraged; -1, -2, -3 for inverse
    expense_ratio: Optional[Decimal] = None

    @property
    def is_leveraged(self) -> bool:
        return abs(self.leverage_factor) > 1

    @property
    def is_inverse(self) -> bool:
        return self.leverage_factor < 0

    @property
    def abs_leverage(self) -> int:
        return abs(self.leverage_factor)


class ETP(Security):
    """Exchange-Traded Product (ETN, commodity ETP, etc.)."""

    security_type: SecurityType = SecurityType.ETP
    product_type: str = ""  # ETN, commodity, currency, etc.
    leverage_factor: int = 1
    underlying_index: str = ""

    @property
    def is_leveraged(self) -> bool:
        return abs(self.leverage_factor) > 1

    @property
    def is_inverse(self) -> bool:
        return self.leverage_factor < 0

    @property
    def abs_leverage(self) -> int:
        return abs(self.leverage_factor)
