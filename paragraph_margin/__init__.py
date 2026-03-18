"""paragraph-margin — YAML-driven margin calculation engine for US BD regulations.

Public API re-exports for convenient access.
"""

# Money utilities
from paragraph_margin.money import (
    ZERO,
    ONE_HUNDRED_PCT,
    MARGIN_PRECISION,
    to_decimal,
    round_margin,
    pct,
    max_of,
    min_of,
)

# Domain models
from paragraph_margin.models.enums import (
    AssetClass,
    SecurityType,
    OptionType,
    ExerciseStyle,
    SettlementType,
    PositionSide,
    TradeSide,
    ExecutionType,
    TradeStatus,
    AccountType,
    MarginCallType,
    MarginCallStatus,
    BondRating,
    INVESTMENT_GRADE_RATINGS,
    TreasuryType,
    IndexType,
    StrategyType,
    FormulaType,
)
from paragraph_margin.models.securities import (
    Security,
    Equity,
    Option,
    CorporateBond,
    MunicipalBond,
    USTreasury,
    AgencyDebt,
    SecurityFuture,
    ETF,
    ETP,
)
from paragraph_margin.models.positions import Position, Lot
from paragraph_margin.models.margin import MarginRequirement, MarginSummary, MarginCall
from paragraph_margin.models.strategies import (
    StrategyLeg,
    RecognizedStrategy,
    StrategyGroup,
)
from paragraph_margin.models.accounts import Account, SMA
from paragraph_margin.models.trades import Trade, Broker
from paragraph_margin.models.snapshots import SODPosition, AccountSnapshot
from paragraph_margin.models.portfolios import PortfolioSummary

# Rule DSL
from paragraph_margin.rules.schema import (
    RuleConfig,
    FormulaConfig,
    MinimumConfig,
    CrossReference,
    RuleSet,
    RuleSetMetadata,
)
from paragraph_margin.rules.loader import load_rule_file, load_rules_directory
from paragraph_margin.rules.registry import MarginRulesRegistry

# Engine
from paragraph_margin.engine.context import build_position_context
from paragraph_margin.engine.matcher import matches_conditions, find_matching_rules
from paragraph_margin.engine.evaluator import evaluate_formula
from paragraph_margin.engine.calculator import (
    evaluate_position_margin,
    evaluate_position_margin_full,
)

# Calculators
from paragraph_margin.calculators.reg_t import RegTCalculator
from paragraph_margin.calculators.finra_4210 import FINRA4210Calculator
from paragraph_margin.calculators.strategy_margin import StrategyMarginCalculator
from paragraph_margin.calculators.strategy_recognizer import StrategyRecognizer
from paragraph_margin.calculators.portfolio_margin import PortfolioMarginCalculator
from paragraph_margin.calculators.concentrated import (
    ConcentratedAccountCalculator,
    ConcentrationResult,
    CONCENTRATED_LONG_RATE,
    CONCENTRATED_SHORT_RATE,
    CONCENTRATED_LOW_CAP_RATE,
    CONCENTRATED_ILLIQUID_RATE,
)
from paragraph_margin.calculators.day_trading import (
    DayTrade,
    DayTradeDetector,
    DayTradingBuyingPower,
    PDT_MINIMUM_EQUITY,
    DT_BUYING_POWER_MULTIPLIER,
    RESTRICTED_BUYING_POWER_MULTIPLIER,
    PDT_TRADE_THRESHOLD,
    PDT_WINDOW_DAYS,
    PDT_PERCENTAGE_THRESHOLD,
)
from paragraph_margin.calculators.sma import SMACalculator

# Engines
from paragraph_margin.aggregator import MarginAggregator
from paragraph_margin.reg_t_engine import RegTEngine
from paragraph_margin.finra_4210_engine import FINRA4210Engine
