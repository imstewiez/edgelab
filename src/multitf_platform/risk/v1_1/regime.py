"""Market regime detection module.

Classifies market into regimes and adjusts strategy behavior:
- TRENDING: ADX > 25, momentum works well
- RANGING: ADX < 20, mean reversion works better
- VOLATILE: ATR > 90th percentile, reduce size or block
- QUIET: ATR < 10th percentile, block (no edge)
"""
import numpy as np
import pandas as pd
from enum import Enum
from typing import Optional


class MarketRegime(Enum):
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    QUIET = "quiet"
    UNKNOWN = "unknown"


class RegimeDetector:
    """Detect market regime from H1 bar data."""
    
    ADX_TREND_THRESHOLD = 25.0
    ADX_RANGE_THRESHOLD = 20.0
    ATR_VOLATILE_PCT = 90.0
    ATR_QUIET_PCT = 10.0
    
    def __init__(self):
        self.atr_history = pd.Series(dtype=float)
        self.current_regime = MarketRegime.UNKNOWN
    
    def _calculate_adx(self, bars: pd.DataFrame, period: int = 14) -> float:
        """Calculate ADX (Average Directional Index)."""
        if len(bars) < period * 2:
            return 0.0
        
        high = bars["high"]
        low = bars["low"]
        close = bars["close"]
        
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        
        # +DM and -DM
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        plus_dm[plus_dm <= minus_dm] = 0
        minus_dm[minus_dm <= plus_dm] = 0
        
        plus_di = 100 * plus_dm.rolling(period).mean().iloc[-1] / atr if atr > 0 else 0
        minus_di = 100 * minus_dm.rolling(period).mean().iloc[-1] / atr if atr > 0 else 0
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
        
        # Simplified ADX (not smoothed over period, just last value)
        return dx
    
    def _calculate_atr(self, bars: pd.DataFrame, period: int = 14) -> float:
        """Calculate current ATR."""
        if len(bars) < period + 1:
            return 0.0
        
        high = bars["high"]
        low = bars["low"]
        close = bars["close"]
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        return tr.rolling(period).mean().iloc[-1]
    
    def detect(self, bars: pd.DataFrame) -> MarketRegime:
        """Detect market regime from recent H1 bars.
        
        Args:
            bars: DataFrame with high, low, close columns
            
        Returns:
            MarketRegime enum
        """
        if len(bars) < 50:
            return MarketRegime.UNKNOWN
        
        atr = self._calculate_atr(bars)
        adx = self._calculate_adx(bars)
        
        # Track ATR history for percentile
        self.atr_history = pd.concat([self.atr_history, pd.Series([atr])]).tail(500)
        
        # Check volatility percentiles
        if len(self.atr_history) >= 100:
            p90 = np.percentile(self.atr_history, self.ATR_VOLATILE_PCT)
            p10 = np.percentile(self.atr_history, self.ATR_QUIET_PCT)
            
            if atr >= p90:
                self.current_regime = MarketRegime.VOLATILE
                return self.current_regime
            if atr <= p10:
                self.current_regime = MarketRegime.QUIET
                return self.current_regime
        
        # Trend vs Range based on ADX
        if adx >= self.ADX_TREND_THRESHOLD:
            self.current_regime = MarketRegime.TRENDING
        elif adx <= self.ADX_RANGE_THRESHOLD:
            self.current_regime = MarketRegime.RANGING
        else:
            # Neutral zone - classify based on recent ATR vs median
            if len(self.atr_history) >= 100:
                median_atr = np.median(self.atr_history)
                self.current_regime = MarketRegime.VOLATILE if atr > median_atr else MarketRegime.RANGING
            else:
                self.current_regime = MarketRegime.RANGING
        
        return self.current_regime
    
    def get_position_adjustments(self) -> dict:
        """Get recommended adjustments for current regime.
        
        Returns:
            Dict with scale, sl_multiplier, tp_multiplier, block_new
        """
        adjustments = {
            MarketRegime.TRENDING: {"scale": 1.0, "sl_mult": 1.5, "tp_mult": 2.0, "block_new": False},
            MarketRegime.RANGING: {"scale": 0.5, "sl_mult": 1.0, "tp_mult": 1.0, "block_new": False},
            MarketRegime.VOLATILE: {"scale": 0.25, "sl_mult": 2.0, "tp_mult": 1.5, "block_new": True},
            MarketRegime.QUIET: {"scale": 0.0, "sl_mult": 1.0, "tp_mult": 1.0, "block_new": True},
            MarketRegime.UNKNOWN: {"scale": 0.5, "sl_mult": 1.0, "tp_mult": 1.0, "block_new": False},
        }
        return adjustments.get(self.current_regime, adjustments[MarketRegime.UNKNOWN])
