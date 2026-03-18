"""Core calculation engine — context building, condition matching, formula evaluation."""

from paragraph_margin.engine.context import build_position_context
from paragraph_margin.engine.matcher import matches_conditions, find_matching_rules
from paragraph_margin.engine.evaluator import evaluate_formula
from paragraph_margin.engine.calculator import evaluate_position_margin, evaluate_position_margin_full
