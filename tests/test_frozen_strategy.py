"""Tests for frozen MultiTF v1.0.0 strategy."""
import pytest
import pandas as pd
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from multitf_platform.strategy.frozen.v1_0_0 import (
    MultiTFStrategy, FrozenStrategyConfig, SignalDecision, VERSION
)


class TestFrozenStrategy:
    """Tests for the immutable frozen strategy package."""
    
    def test_version_is_frozen(self):
        assert VERSION == "1.0.0"
    
    def test_deterministic_output(self):
        """Same inputs must produce same outputs."""
        cfg = FrozenStrategyConfig(min_h1_bars=100, min_h4_bars=50)
        strat = MultiTFStrategy(cfg)
        
        # Create synthetic data with stable end
        idx = pd.date_range("2024-01-01", periods=300, freq="h")
        base = np.linspace(2000, 2100, 300)
        noise = np.random.RandomState(42).randn(300) * 0.5
        prices = base + noise
        h1 = pd.DataFrame({
            "open": prices,
            "high": prices + 1,
            "low": prices - 1,
            "close": prices,
        }, index=idx)
        
        h4 = h1.resample("4h").last()
        
        sig1 = strat.generate_signal(h1, h4)
        sig2 = strat.generate_signal(h1, h4)
        
        assert sig1.direction == sig2.direction
        assert sig1.h1_momentum == pytest.approx(sig2.h1_momentum, rel=1e-10)
        assert sig1.h4_momentum == pytest.approx(sig2.h4_momentum, rel=1e-10)
    
    def test_insufficient_data_blocked(self):
        """Strategy must block when insufficient bars."""
        cfg = FrozenStrategyConfig(min_h1_bars=500)
        strat = MultiTFStrategy(cfg)
        
        idx = pd.date_range("2024-01-01", periods=100, freq="h")
        h1 = pd.DataFrame({"open":[2000]*100, "high":[2001]*100, "low":[1999]*100, "close":[2000]*100}, index=idx)
        h4 = h1.resample("4h").last()
        
        sig = strat.generate_signal(h1, h4)
        
        assert sig.direction == 0
        assert not sig.warmup_complete
        assert sig.blocked_reason is not None
    
    def test_bullish_signal(self):
        """Both timeframes up -> LONG."""
        cfg = FrozenStrategyConfig(h1_lookback=10, h4_lookback=10, min_h1_bars=100, min_h4_bars=50)
        strat = MultiTFStrategy(cfg)
        
        # Rising prices - need enough bars for both H1 and H4 lookbacks
        idx = pd.date_range("2024-01-01", periods=500, freq="h")
        prices = np.linspace(2000, 2100, 500)
        h1 = pd.DataFrame({
            "open": prices, "high": prices+1, "low": prices-1, "close": prices
        }, index=idx)
        h4 = h1.resample("4h").last()
        
        sig = strat.generate_signal(h1, h4)
        
        assert sig.direction == 1
        assert sig.is_long
        assert sig.warmup_complete
    
    def test_bearish_signal(self):
        """Both timeframes down -> SHORT."""
        cfg = FrozenStrategyConfig(h1_lookback=10, h4_lookback=10, min_h1_bars=100, min_h4_bars=50)
        strat = MultiTFStrategy(cfg)
        
        idx = pd.date_range("2024-01-01", periods=500, freq="h")
        prices = np.linspace(2100, 2000, 500)
        h1 = pd.DataFrame({
            "open": prices, "high": prices+1, "low": prices-1, "close": prices
        }, index=idx)
        h4 = h1.resample("4h").last()
        
        sig = strat.generate_signal(h1, h4)
        
        assert sig.direction == -1
        assert sig.is_short
        assert sig.warmup_complete
    
    def test_mixed_signal_flat(self):
        """Timeframes disagree -> FLAT."""
        cfg = FrozenStrategyConfig(h1_lookback=10, h4_lookback=10, min_h1_bars=100, min_h4_bars=50)
        strat = MultiTFStrategy(cfg)
        
        idx = pd.date_range("2024-01-01", periods=500, freq="h")
        # H1 up
        h1_prices = np.linspace(2000, 2100, 500)
        h1 = pd.DataFrame({
            "open": h1_prices, "high": h1_prices+1, "low": h1_prices-1, "close": h1_prices
        }, index=idx)
        
        # H4 down (overlapping period, create enough 4h bars)
        h4_idx = pd.date_range("2024-01-01", periods=125, freq="4h")
        h4_prices = np.linspace(2200, 2000, 125)
        h4 = pd.DataFrame({
            "open": h4_prices, "high": h4_prices+1, "low": h4_prices-1, "close": h4_prices
        }, index=h4_idx)
        
        sig = strat.generate_signal(h1, h4)
        
        assert sig.direction == 0
        assert sig.is_flat
