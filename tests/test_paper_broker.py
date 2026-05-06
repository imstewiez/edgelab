"""Tests for paper broker execution simulation."""
import pytest
import pandas as pd
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from multitf_platform.config.models import BrokerConfig
from multitf_platform.brokers.paper import PaperBroker
from multitf_platform.brokers.paper.models import TradeSide, TradeAction
from multitf_platform.risk.v1_1.wrapper import Action, WrappedDecision
from multitf_platform.strategy.frozen.v1_0_0 import SignalDecision


def make_decision(action: Action, direction: int, scale: float = 1.0,
                  reasons: list = None) -> WrappedDecision:
    """Helper to create WrappedDecision for tests."""
    sig = SignalDecision(
        direction=direction,
        timestamp=pd.Timestamp("2024-01-01 10:00"),
        h1_momentum=0.0, h4_momentum=0.0,
        warmup_complete=True, blocked_reason=None,
    )
    return WrappedDecision(
        action=action,
        original_signal=sig,
        position_scale=scale,
        reason="test",
        sub_reasons=reasons or [],
    )


class TestPaperBroker:
    """Tests for paper broker fill simulation and margin tracking."""
    
    def test_initial_state(self):
        cfg = BrokerConfig(initial_equity=300.0, leverage=1000)
        broker = PaperBroker(cfg)
        state = broker.get_state()
        
        assert state.balance == 300.0
        assert state.equity == 300.0
        assert state.margin_used == 0.0
        assert state.free_margin == 300.0
    
    def test_open_long_position(self):
        cfg = BrokerConfig(initial_equity=300.0, leverage=1000, commission_per_lot=7.0)
        broker = PaperBroker(cfg)
        
        bar = pd.Series({
            "open": 2000.0, "high": 2001.0, "low": 1999.0,
            "close": 2000.0, "spread": 25,
        }, name=pd.Timestamp("2024-01-01 10:00"))
        
        decision = make_decision(Action.ALLOW, 1, 1.0)
        state = broker.process_bar(decision, bar, 0)
        
        assert state.open_position is not None
        assert state.open_position.direction == 1
        assert state.open_position.size_lots > 0
        assert len(broker.fills) == 1
        assert broker.fills[0].action == TradeAction.OPEN
        assert broker.fills[0].side == TradeSide.BUY
        # Long fill at ask = close + spread/2 (spread=25 points = $0.25)
        assert broker.fills[0].fill_price >= 2000.0
    
    def test_open_short_position(self):
        cfg = BrokerConfig(initial_equity=300.0, leverage=1000)
        broker = PaperBroker(cfg)
        
        bar = pd.Series({
            "open": 2000.0, "high": 2001.0, "low": 1999.0,
            "close": 2000.0, "spread": 25,
        }, name=pd.Timestamp("2024-01-01 10:00"))
        
        decision = make_decision(Action.ALLOW, -1, 1.0)
        state = broker.process_bar(decision, bar, 0)
        
        assert state.open_position is not None
        assert state.open_position.direction == -1
        assert broker.fills[0].side == TradeSide.SELL
        # Short fill at bid = close - spread/2
        assert broker.fills[0].fill_price <= 2000.0
    
    def test_flatten_closes_position(self):
        cfg = BrokerConfig(initial_equity=300.0, leverage=1000)
        broker = PaperBroker(cfg)
        
        bar1 = pd.Series({
            "open": 2000.0, "high": 2001.0, "low": 1999.0,
            "close": 2000.0, "spread": 25,
        }, name=pd.Timestamp("2024-01-01 10:00"))
        
        bar2 = pd.Series({
            "open": 2000.0, "high": 2001.0, "low": 1999.0,
            "close": 2005.0, "spread": 25,
        }, name=pd.Timestamp("2024-01-01 11:00"))
        
        broker.process_bar(make_decision(Action.ALLOW, 1, 1.0), bar1, 0)
        broker.flatten(bar2, reason="test_flatten")
        
        assert broker.position is None
        assert len(broker.trades) == 1
        assert broker.trades[0].exit_reason == "test_flatten"
        # Long at ~2000, closed at ~2005 should be profitable
        assert broker.trades[0].gross_pnl > 0
    
    def test_flip_direction(self):
        cfg = BrokerConfig(initial_equity=300.0, leverage=1000)
        broker = PaperBroker(cfg)
        
        bar1 = pd.Series({
            "open": 2000.0, "high": 2001.0, "low": 1999.0,
            "close": 2000.0, "spread": 25,
        }, name=pd.Timestamp("2024-01-01 10:00"))
        
        bar2 = pd.Series({
            "open": 2000.0, "high": 2001.0, "low": 1999.0,
            "close": 2000.0, "spread": 25,
        }, name=pd.Timestamp("2024-01-01 11:00"))
        
        broker.process_bar(make_decision(Action.ALLOW, 1, 1.0), bar1, 0)
        broker.process_bar(make_decision(Action.ALLOW, -1, 1.0), bar2, 1)
        
        assert broker.position is not None
        assert broker.position.direction == -1
        assert len(broker.trades) == 1  # First trade closed
        assert len(broker.fills) == 3   # Open, Close, Open
    
    def test_margin_calculation(self):
        cfg = BrokerConfig(initial_equity=300.0, leverage=1000)
        broker = PaperBroker(cfg)
        
        bar = pd.Series({
            "open": 2000.0, "high": 2001.0, "low": 1999.0,
            "close": 2000.0, "spread": 25,
        }, name=pd.Timestamp("2024-01-01 10:00"))
        
        broker.process_bar(make_decision(Action.ALLOW, 1, 1.0), bar, 0)
        
        state = broker.get_state()
        # Margin for 0.01 lots @ $2000 with 1:1000 leverage
        # Notional = 0.01 * 100 * 2000 = $20
        # Margin = 20 / 1000 = $2.00
        assert state.margin_used > 0
        assert state.margin_used < 5.0
        assert state.free_margin == pytest.approx(state.equity - state.margin_used, rel=1e-6)
    
    def test_kill_switch_flattens(self):
        cfg = BrokerConfig(initial_equity=300.0, leverage=1000)
        broker = PaperBroker(cfg)
        
        bar1 = pd.Series({
            "open": 2000.0, "high": 2001.0, "low": 1999.0,
            "close": 2000.0, "spread": 25,
        }, name=pd.Timestamp("2024-01-01 10:00"))
        
        bar2 = pd.Series({
            "open": 2000.0, "high": 2001.0, "low": 1999.0,
            "close": 2000.0, "spread": 25,
        }, name=pd.Timestamp("2024-01-01 11:00"))
        
        broker.process_bar(make_decision(Action.ALLOW, 1, 1.0), bar1, 0)
        broker.process_bar(make_decision(Action.KILL_SWITCH, 0, 0.0), bar2, 1)
        
        assert broker.position is None
        assert len(broker.trades) == 1
        assert broker.trades[0].exit_reason == "kill_switch"
    
    def test_trade_stats(self):
        cfg = BrokerConfig(initial_equity=300.0, leverage=1000)
        broker = PaperBroker(cfg)
        
        bar1 = pd.Series({
            "open": 2000.0, "high": 2001.0, "low": 1999.0,
            "close": 2000.0, "spread": 25,
        }, name=pd.Timestamp("2024-01-01 10:00"))
        
        bar2 = pd.Series({
            "open": 2005.0, "high": 2006.0, "low": 2004.0,
            "close": 2005.0, "spread": 25,
        }, name=pd.Timestamp("2024-01-01 11:00"))
        
        broker.process_bar(make_decision(Action.ALLOW, 1, 1.0), bar1, 0)
        broker.flatten(bar2, reason="test")
        
        stats = broker.get_trade_stats()
        assert stats["total_trades"] == 1
        assert stats["winning_trades"] == 1
        assert stats["win_rate"] == 1.0
        assert stats["avg_pnl"] > 0
    
    def test_minimum_lot_size_respected(self):
        cfg = BrokerConfig(initial_equity=300.0, leverage=1000, min_lot_size=0.01)
        broker = PaperBroker(cfg)
        
        bar = pd.Series({
            "open": 2000.0, "high": 2001.0, "low": 1999.0,
            "close": 2000.0, "spread": 25,
        }, name=pd.Timestamp("2024-01-01 10:00"))
        
        # Very small scale
        broker.process_bar(make_decision(Action.ALLOW, 1, 0.001), bar, 0)
        
        # Should still open with minimum lot size
        assert broker.position is not None
        assert broker.position.size_lots >= 0.01
