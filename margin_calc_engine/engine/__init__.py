"""Core calculation engine — context building, condition matching, formula evaluation."""

from margin_calc_engine.engine.context import build_position_context
from margin_calc_engine.engine.matcher import matches_conditions, find_matching_rules
from margin_calc_engine.engine.evaluator import evaluate_formula
from margin_calc_engine.engine.calculator import evaluate_position_margin, evaluate_position_margin_full
