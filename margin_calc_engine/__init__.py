"""margin-calc-engine — YAML-driven margin calculation engine for US BD regulations.

Public API re-exports for convenient access.
"""

# Money utilities
from margin_calc_engine.money import (
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
from margin_calc_engine.models.enums import (
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
from margin_calc_engine.models.securities import (
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
from margin_calc_engine.models.positions import Position, Lot
from margin_calc_engine.models.margin import MarginRequirement, MarginSummary, MarginCall
from margin_calc_engine.models.strategies import (
    StrategyLeg,
    RecognizedStrategy,
    StrategyGroup,
)
from margin_calc_engine.models.accounts import Account, SMA
from margin_calc_engine.models.trades import Trade, Broker
from margin_calc_engine.models.snapshots import SODPosition, AccountSnapshot
from margin_calc_engine.models.portfolios import PortfolioSummary

# Rule DSL
from margin_calc_engine.rules.schema import (
    RuleConfig,
    FormulaConfig,
    MinimumConfig,
    CrossReference,
    RuleSet,
    RuleSetMetadata,
)
from margin_calc_engine.rules.loader import load_rule_file, load_rules_directory
from margin_calc_engine.rules.registry import MarginRulesRegistry

# Engine
from margin_calc_engine.engine.context import build_position_context
from margin_calc_engine.engine.matcher import matches_conditions, find_matching_rules
from margin_calc_engine.engine.evaluator import evaluate_formula
from margin_calc_engine.engine.calculator import (
    evaluate_position_margin,
    evaluate_position_margin_full,
)

# Calculators
from margin_calc_engine.calculators.reg_t import RegTCalculator
from margin_calc_engine.calculators.finra_4210 import FINRA4210Calculator
from margin_calc_engine.calculators.strategy_margin import StrategyMarginCalculator
from margin_calc_engine.calculators.strategy_recognizer import StrategyRecognizer
from margin_calc_engine.calculators.portfolio_margin import PortfolioMarginCalculator
from margin_calc_engine.calculators.concentrated import ConcentratedAccountCalculator
from margin_calc_engine.calculators.day_trading import DayTradeDetector
from margin_calc_engine.calculators.sma import SMACalculator

# Engines
from margin_calc_engine.aggregator import MarginAggregator
from margin_calc_engine.reg_t_engine import RegTEngine
from margin_calc_engine.finra_4210_engine import FINRA4210Engine
