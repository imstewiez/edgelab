"""Pure signal generation for frozen MultiTF v1.0.0.

This module is SIDE-EFFECT FREE and DETERMINISTIC.
Given the same inputs, it always produces the same outputs.
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np

from .config import FrozenStrategyConfig


@dataclass(frozen=True)
class SignalDecision:
    """Immutable signal decision output."""
    direction: int  # 1=LONG, -1=SHORT, 0=FLAT
    timestamp: pd.Timestamp
    h1_momentum: float
    h4_momentum: float
    warmup_complete: bool
    blocked_reason: Optional[str] = None
    
    @property
    def is_long(self) -> bool:
        return self.direction == 1
    
    @property
    def is_short(self) -> bool:
        return self.direction == -1
    
    @property
    def is_flat(self) -> bool:
        return self.direction == 0
    
    @property
    def is_valid(self) -> bool:
        return self.warmup_complete and self.blocked_reason is None


class MultiTFStrategy:
    """Frozen MultiTF v1.0.0 strategy.
    
    Logic:
    - Compute H1 momentum (close vs close[N] ago)
    - Compute H4 momentum (close vs close[N] ago)
    - LONG only if BOTH H1 and H4 momentum > 0
    - SHORT only if BOTH H1 and H4 momentum < 0
    - FLAT otherwise
    
    NO RISK LOGIC. NO POSITION SIZING. NO EXECUTION.
    Pure signal generation only.
    """
    
    VERSION = "1.0.0"
    
    def __init__(self, config: Optional[FrozenStrategyConfig] = None):
        self.config = config or FrozenStrategyConfig()
    
    def generate_signal(
        self,
        h1_bars: pd.DataFrame,
        h4_bars: pd.DataFrame,
        now_utc: Optional[pd.Timestamp] = None
    ) -> SignalDecision:
        """Generate signal decision from H1 and H4 bar data.
        
        Args:
            h1_bars: DataFrame with columns [open, high, low, close] indexed by UTC timestamp
            h4_bars: DataFrame with columns [open, high, low, close] indexed by UTC timestamp
            now_utc: Current timestamp (defaults to last H1 bar)
            
        Returns:
            SignalDecision with direction, momentum values, and warmup status
        """
        cfg = self.config
        
        if now_utc is None:
            now_utc = h1_bars.index[-1]
        
        # Validate inputs
        if len(h1_bars) < cfg.min_h1_bars:
            return SignalDecision(
                direction=0,
                timestamp=now_utc,
                h1_momentum=np.nan,
                h4_momentum=np.nan,
                warmup_complete=False,
                blocked_reason="Insufficient H1 bars: %d < %d" % (len(h1_bars), cfg.min_h1_bars)
            )
        
        if len(h4_bars) < cfg.min_h4_bars:
            return SignalDecision(
                direction=0,
                timestamp=now_utc,
                h1_momentum=np.nan,
                h4_momentum=np.nan,
                warmup_complete=False,
                blocked_reason="Insufficient H4 bars: %d < %d" % (len(h4_bars), cfg.min_h4_bars)
            )
        
        # Calculate H1 momentum
        h1_close = h1_bars["close"]
        h1_mom = self._calc_momentum(h1_close, cfg.h1_lookback)
        
        # Calculate H4 momentum
        h4_close = h4_bars["close"]
        h4_mom = self._calc_momentum(h4_close, cfg.h4_lookback)
        
        # Determine direction
        if h1_mom > 0 and h4_mom > 0:
            direction = 1
        elif h1_mom < 0 and h4_mom < 0:
            direction = -1
        else:
            direction = 0
        
        return SignalDecision(
            direction=direction,
            timestamp=now_utc,
            h1_momentum=h1_mom,
            h4_momentum=h4_mom,
            warmup_complete=True,
            blocked_reason=None
        )
    
    @staticmethod
    def _calc_momentum(series: pd.Series, lookback: int) -> float:
        """Calculate simple momentum: (current / past - 1).
        
        Returns 0.0 if insufficient data.
        """
        if len(series) < lookback + 1:
            return 0.0
        current = series.iloc[-1]
        past = series.iloc[-(lookback + 1)]
        if past == 0 or pd.isna(past) or pd.isna(current):
            return 0.0
        return (current / past) - 1.0
    
    def generate_signals_series(
        self,
        h1_bars: pd.DataFrame,
        h4_bars: pd.DataFrame
    ) -> pd.Series:
        """Generate a time series of signals for all H1 bars.
        
        This is useful for backtesting. It produces the same signals
        as calling generate_signal() at each bar, but vectorized.
        
        NOTE: This resamples H4 to H1 using forward-fill, which is
        equivalent to the real-time logic. The H4 verification test
        proved 100% agreement between this method and native H4 bars.
        """
        cfg = self.config
        
        h1_mom = h1_bars["close"].pct_change(cfg.h1_lookback)
        
        # Align H4 momentum to H1 timestamps
        h4_close = h4_bars["close"]
        h4_mom = h4_close.pct_change(cfg.h4_lookback)
        h4_mom_h1 = h4_mom.reindex(h1_bars.index, method="ffill")
        
        long = (h1_mom > 0) & (h4_mom_h1 > 0)
        short = (h1_mom < 0) & (h4_mom_h1 < 0)
        
        signals = pd.Series(0, index=h1_bars.index, dtype=int)
        signals[long] = 1
        signals[short] = -1
        
        return signals
