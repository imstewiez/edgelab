"""Paper broker for demo/paper trading simulation.

Simulates MT5-style execution for XAUUSD CFDs with realistic
spread, commission, slippage, and margin calculations.
"""
from .models import Position, FillEvent, TradeRecord, BrokerState
from .broker import PaperBroker

__all__ = ["PaperBroker", "Position", "FillEvent", "TradeRecord", "BrokerState"]
