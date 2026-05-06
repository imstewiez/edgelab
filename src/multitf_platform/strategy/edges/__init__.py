"""Unconventional trading edges — outside the box alpha generators.

Modules:
- stat_arb: Cointegration-based pairs trading (market-neutral)
- session_momentum: London/NY open breakout scalper
- gap_fade: Weekend gap mean-reversion
"""
from .stat_arb import StatArbEngine, StatArbSignal, PAIRS_CONFIG
from .session_momentum import SessionMomentumEngine, SessionMomentumSignal
from .gap_fade import GapFadeEngine, GapFadeSignal

__all__ = [
    "StatArbEngine", "StatArbSignal", "PAIRS_CONFIG",
    "SessionMomentumEngine", "SessionMomentumSignal",
    "GapFadeEngine", "GapFadeSignal",
]
