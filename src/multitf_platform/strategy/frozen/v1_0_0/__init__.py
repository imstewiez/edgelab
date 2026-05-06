"""Frozen MultiTF Strategy v1.0.0 - Immutable alpha package.

This package is FROZEN. No signal logic changes are permitted.
Future versions must be created as v1.0.1, v1.1.0, etc.
"""
from .signals import MultiTFStrategy, SignalDecision
from .config import FrozenStrategyConfig
from .version import VERSION

__all__ = ["MultiTFStrategy", "SignalDecision", "FrozenStrategyConfig", "VERSION"]
