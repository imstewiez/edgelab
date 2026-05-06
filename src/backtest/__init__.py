"""Backtesting framework for FX strategies."""
from .engine import VectorizedBacktester
from .execution import ExecutionSimulator
from .metrics import calculate_metrics
from .strategy import Strategy, SMAStrategy, RSIStrategy

__all__ = [
    "VectorizedBacktester",
    "ExecutionSimulator",
    "calculate_metrics",
    "Strategy",
    "SMAStrategy",
    "RSIStrategy",
]
