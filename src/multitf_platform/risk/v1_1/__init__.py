"""Risk Wrapper v1.1 - Hard controls around frozen MultiTF v1.0.0.

This module wraps signal decisions in risk gates.
It does NOT modify signal logic. It only allows, blocks, or modifies
position sizing based on market conditions and portfolio state.
"""
from .wrapper import RiskWrapper, WrappedDecision, RiskState, Action

__all__ = ["RiskWrapper", "WrappedDecision", "RiskState", "Action"]
