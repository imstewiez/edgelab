"""
Market regime detection for dynamic strategy selection.
Uses price action, volatility, and trend strength to classify regimes.
"""
import numpy as np
import pandas as pd


class RegimeDetector:
    """
    Detects market regimes using rolling statistics.
    
    Regimes:
    - TRENDING_UP: price above rising SMA, ADX high
    - TRENDING_DOWN: price below falling SMA, ADX high
    - RANGING: price near SMA, low volatility, ADX low
    - VOLATILE: high ATR percentile, large recent moves
    - UNKNOWN: insufficient data
    """
    
    def __init__(
        self,
        sma_period: int = 50,
        adx_period: int = 14,
        atr_period: int = 20,
        vol_lookback: int = 100,
        trend_threshold: float = 0.3,  # ADX threshold for trend
        vol_percentile: float = 75.0,  # ATR percentile for volatile
    ):
        self.sma_period = sma_period
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.vol_lookback = vol_lookback
        self.trend_threshold = trend_threshold
        self.vol_percentile = vol_percentile
    
    def _compute_atr(self, data: pd.DataFrame, period: int) -> pd.Series:
        high = data["high"]
        low = data["low"]
        close = data["close"]
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean()
    
    def _compute_adx(self, data: pd.DataFrame, period: int) -> pd.Series:
        """Simplified ADX proxy."""
        high = data["high"]
        low = data["low"]
        close = data["close"]
        
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        atr = self._compute_atr(data, period)
        plus_di = 100 * plus_dm.rolling(period).mean() / atr
        minus_di = 100 * minus_dm.rolling(period).mean() / atr
        
        dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
        adx = dx.rolling(period).mean()
        return adx
    
    def detect(self, data: pd.DataFrame) -> pd.Series:
        """
        Return regime classification for each bar.
        Returns Series of strings: TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE, UNKNOWN
        """
        close = data["close"]
        sma = close.rolling(self.sma_period).mean()
        sma_slope = sma.diff(10)
        atr = self._compute_atr(data, self.atr_period)
        atr_pctile = atr.rolling(self.vol_lookback).rank(pct=True) * 100
        adx = self._compute_adx(data, self.adx_period)
        
        regimes = pd.Series("UNKNOWN", index=data.index)
        
        # Volatile regime takes precedence
        volatile = atr_pctile > self.vol_percentile
        regimes[volatile] = "VOLATILE"
        
        # Trending regimes
        trending = adx > self.trend_threshold
        up = (close > sma) & (sma_slope > 0) & trending
        down = (close < sma) & (sma_slope < 0) & trending
        regimes[up & ~volatile] = "TRENDING_UP"
        regimes[down & ~volatile] = "TRENDING_DOWN"
        
        # Ranging regime
        near_sma = (close - sma).abs() / close < 0.02
        low_vol = atr_pctile < 50
        ranging = near_sma & low_vol & ~trending & ~volatile
        regimes[ranging] = "RANGING"
        
        return regimes
    
    def get_regime_summary(self, data: pd.DataFrame) -> pd.DataFrame:
        """Summary statistics per regime."""
        regimes = self.detect(data)
        data = data.copy()
        data["regime"] = regimes
        data["returns"] = data["close"].pct_change()
        
        summary = []
        for regime in regimes.unique():
            subset = data[data["regime"] == regime]
            if len(subset) < 10:
                continue
            summary.append({
                "regime": regime,
                "bars": len(subset),
                "pct_time": round(len(subset) / len(data) * 100, 1),
                "ann_vol": round(subset["returns"].std() * np.sqrt(365*24) * 100, 1),
                "ann_ret": round(subset["returns"].mean() * 365*24 * 100, 1),
            })
        return pd.DataFrame(summary)
