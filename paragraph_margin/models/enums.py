"""Shared enumerations for the margin calculation system."""

from enum import Enum, StrEnum


class SecurityType(StrEnum):
    EQUITY = "equity"
    OPTION = "option"
    CORPORATE_BOND = "corporate_bond"
    MUNICIPAL_BOND = "municipal_bond"
    US_TREASURY = "us_treasury"
    ETF = "etf"
    ETP = "etp"
    AGENCY_DEBT = "agency_debt"
    SECURITY_FUTURE = "security_future"


class OptionType(StrEnum):
    CALL = "call"
    PUT = "put"


class ExerciseStyle(StrEnum):
    AMERICAN = "american"
    EUROPEAN = "european"


class SettlementType(StrEnum):
    PHYSICAL = "physical"
    CASH = "cash"


class PositionSide(StrEnum):
    LONG = "long"
    SHORT = "short"


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"
    SELL_SHORT = "sell_short"
    BUY_TO_COVER = "buy_to_cover"


class ExecutionType(StrEnum):
    DONE_WITH = "done_with"
    DONE_AWAY = "done_away"


class TradeStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DK = "dk"  # Don't Know
    SETTLED = "settled"
    FAILED = "failed"


class AccountType(StrEnum):
    MARGIN = "margin"
    CASH = "cash"
    PORTFOLIO_MARGIN = "portfolio_margin"


class MarginCallType(StrEnum):
    REG_T_INITIAL = "reg_t_initial"
    MAINTENANCE = "maintenance"
    HOUSE = "house"
    DAY_TRADE = "day_trade"


class MarginCallStatus(StrEnum):
    OUTSTANDING = "outstanding"
    MET = "met"
    LIQUIDATED = "liquidated"
    EXTENDED = "extended"


class BondRating(StrEnum):
    AAA = "AAA"
    AA_PLUS = "AA+"
    AA = "AA"
    AA_MINUS = "AA-"
    A_PLUS = "A+"
    A = "A"
    A_MINUS = "A-"
    BBB_PLUS = "BBB+"
    BBB = "BBB"
    BBB_MINUS = "BBB-"
    BB_PLUS = "BB+"
    BB = "BB"
    BB_MINUS = "BB-"
    B_PLUS = "B+"
    B = "B"
    B_MINUS = "B-"
    CCC_PLUS = "CCC+"
    CCC = "CCC"
    CCC_MINUS = "CCC-"
    CC = "CC"
    C = "C"
    D = "D"
    NR = "NR"  # Not rated


INVESTMENT_GRADE_RATINGS = {
    BondRating.AAA, BondRating.AA_PLUS, BondRating.AA, BondRating.AA_MINUS,
    BondRating.A_PLUS, BondRating.A, BondRating.A_MINUS,
    BondRating.BBB_PLUS, BondRating.BBB, BondRating.BBB_MINUS,
}


class TreasuryType(StrEnum):
    BILL = "bill"   # <= 1 year at issuance
    NOTE = "note"   # 2-10 years
    BOND = "bond"   # 20-30 years


class IndexType(StrEnum):
    BROAD_BASED = "broad_based"
    NARROW_BASED = "narrow_based"


class StrategyType(StrEnum):
    # Single-leg
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    SHORT_NAKED_CALL = "short_naked_call"
    SHORT_NAKED_PUT = "short_naked_put"
    CASH_SECURED_PUT = "cash_secured_put"

    # Two-leg vertical spreads
    BULL_CALL_SPREAD = "bull_call_spread"
    BEAR_CALL_SPREAD = "bear_call_spread"
    BULL_PUT_SPREAD = "bull_put_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"

    # Two-leg volatility
    LONG_STRADDLE = "long_straddle"
    SHORT_STRADDLE = "short_straddle"
    LONG_STRANGLE = "long_strangle"
    SHORT_STRANGLE = "short_strangle"

    # Two-leg time spreads
    CALENDAR_SPREAD = "calendar_spread"
    DIAGONAL_SPREAD = "diagonal_spread"

    # Multi-leg
    LONG_CALL_BUTTERFLY = "long_call_butterfly"
    LONG_PUT_BUTTERFLY = "long_put_butterfly"
    SHORT_CALL_BUTTERFLY = "short_call_butterfly"
    SHORT_PUT_BUTTERFLY = "short_put_butterfly"
    IRON_BUTTERFLY = "iron_butterfly"
    LONG_IRON_BUTTERFLY = "long_iron_butterfly"
    IRON_CONDOR = "iron_condor"
    LONG_IRON_CONDOR = "long_iron_condor"
    LONG_CALL_CONDOR = "long_call_condor"
    LONG_PUT_CONDOR = "long_put_condor"
    BOX_SPREAD = "box_spread"
    CHRISTMAS_TREE = "christmas_tree"
    RATIO_CALL_SPREAD = "ratio_call_spread"
    RATIO_PUT_SPREAD = "ratio_put_spread"
    CALL_BACKSPREAD = "call_backspread"
    PUT_BACKSPREAD = "put_backspread"
    JELLY_ROLL = "jelly_roll"

    # Cross-product (stock + options)
    COVERED_CALL = "covered_call"
    COVERED_PUT = "covered_put"
    PROTECTIVE_PUT = "protective_put"
    PROTECTIVE_CALL = "protective_call"
    COLLAR = "collar"
    CONVERSION = "conversion"
    REVERSE_CONVERSION = "reverse_conversion"
    SYNTHETIC_LONG = "synthetic_long"
    SYNTHETIC_SHORT = "synthetic_short"

    # Unrecognized
    UNRECOGNIZED = "unrecognized"


class AssetClass(StrEnum):
    EQUITY = "equity"
    FIXED_INCOME = "fixed_income"
    DERIVATIVE = "derivative"
    FUND = "fund"


# Mapping from SecurityType to AssetClass
_SECURITY_TYPE_TO_ASSET_CLASS: dict[str, str] = {
    "equity": "equity",
    "option": "derivative",
    "corporate_bond": "fixed_income",
    "municipal_bond": "fixed_income",
    "us_treasury": "fixed_income",
    "agency_debt": "fixed_income",
    "etf": "fund",
    "etp": "fund",
    "security_future": "derivative",
}


class FormulaType(StrEnum):
    """Types of margin calculation formulas supported by the rule engine."""
    PERCENTAGE_OF_MARKET_VALUE = "percentage_of_market_value"
    PERCENTAGE_OF_PRINCIPAL = "percentage_of_principal"
    NAKED_OPTION = "naked_option"
    NET_DEBIT = "net_debit"
    MAX_LOSS = "max_loss"
    GREATER_SIDE_PLUS_OTHER_PREMIUM = "greater_side_plus_other_premium"
    GREATER_WING_MINUS_CREDIT = "greater_wing_minus_credit"
    FIXED_PERCENTAGE_OF_EXERCISE_PRICE = "fixed_percentage_of_exercise_price"
    GOOD_FAITH = "good_faith"
    FULL_PAYMENT = "full_payment"
    PROTECTIVE_PUT = "protective_put"
    COLLAR = "collar"
