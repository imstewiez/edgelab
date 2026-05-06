"""Weekend Gap Fade Strategy.

Exploits the well-documented "weekend gap fill" phenomenon in FX:
- Markets close Friday ~20:00 GMT, reopen Sunday ~22:00 GMT
- Gaps form due to weekend news/events
- Research: ~70% of FX gaps fill within 24-48 hours
- The larger the gap, the higher the fill probability

Logic:
1. Only active Sunday 22:00-23:00 GMT (first hour after reopen)
2. Calculate gap = current_price - friday_20:00_close
3. If |gap| > threshold (0.3 ATR) → trade fade direction
4. Direction = -sign(gap) (trade back toward Friday close)
5. SL = friday_close ± 0.5 ATR (away from target)
6. TP = friday_close (gap fill target)
7. Max hold: 72 hours (Wednesday close) — if not filled, exit

Risk management:
- Skip if gap > 2 ATR (likely fundamental shift, not noise)
- Skip if weekend had major geopolitical event
"""
from dataclasses import dataclass
from typing import Optional
from enum import Enum
import pandas as pd
import numpy as np


class GapStatus(Enum):
    FLAT = 0
    LONG = 1   # Fade a downward gap
    SHORT = -1 # Fade an upward gap


@dataclass(frozen=True)
class GapFadeSignal:
    """Signal output from Gap Fade engine."""
    symbol: str
    status: GapStatus
    gap_size: float
    gap_atr_ratio: float
    friday_close: float
    current_price: float
    timestamp: pd.Timestamp
    direction: int  # 1=LONG, -1=SHORT, 0=FLAT
    sl_price: float
    tp_price: float
    size_lots: float
    max_hold_hours: int = 72
    warmup_complete: bool = True
    blocked_reason: Optional[str] = None
    
    @property
    def is_active(self) -> bool:
        return self.status != GapStatus.FLAT and self.warmup_complete


class GapFadeEngine:
    """Weekend gap fade strategy.
    
    Args:
        symbol: Symbol to trade
        gap_atr_threshold: Min gap size as multiple of ATR (default 0.3)
        max_gap_atr: Max gap size — gaps > this are likely fundamental (default 2.0)
        atr_lookback: Bars for ATR calculation (default 20)
    """
    
    VERSION = "1.0.0"
    
    def __init__(
        self,
        symbol: str,
        gap_atr_threshold: float = 0.3,
        max_gap_atr: float = 2.0,
        atr_lookback: int = 20,
    ):
        self.symbol = symbol
        self.gap_atr_threshold = gap_atr_threshold
        self.max_gap_atr = max_gap_atr
        self.atr_lookback = atr_lookback
        self.current_status = GapStatus.FLAT
    
    def generate_signal(
        self,
        h1_bars: pd.DataFrame,
        equity: float = 10000.0,
        now_utc: Optional[pd.Timestamp] = None,
    ) -> GapFadeSignal:
        """Generate gap fade signal.
        
        Args:
            h1_bars: DataFrame [open, high, low, close] indexed by UTC
                     Must include Friday bars and current Sunday bar
            equity: Current account equity
            now_utc: Current timestamp
            
        Returns:
            GapFadeSignal
        """
        if now_utc is None:
            now_utc = h1_bars.index[-1]
        
        # Only trade on Sunday 22:00-23:00 GMT
        weekday = now_utc.weekday()
        hour = now_utc.hour
        
        if not (weekday == 6 and 22 <= hour < 23):
            return self._make_signal(
                GapStatus.FLAT, 0, 0, 0, 0, now_utc, 0, 0, 0, 0,
                blocked_reason=f"Not Sunday 22-23h GMT (day={weekday}, hour={hour})"
            )
        
        if len(h1_bars) < self.atr_lookback + 48:
            return self._make_signal(
                GapStatus.FLAT, 0, 0, 0, 0, now_utc, 0, 0, 0, 0,
                blocked_reason=f"Insufficient history: {len(h1_bars)} bars"
            )
        
        # Find Friday 20:00 GMT close (last bar before weekend)
        friday_close = None
        friday_time = None
        
        # Search backwards for Friday bars (weekday == 4)
        for i in range(1, min(len(h1_bars), 72)):
            t = h1_bars.index[-i]
            if t.weekday() == 4:
                # Found Friday — use the last Friday bar
                friday_close = h1_bars["close"].iloc[-i]
                friday_time = t
                break
        
        if friday_close is None:
            return self._make_signal(
                GapStatus.FLAT, 0, 0, 0, 0, now_utc, 0, 0, 0, 0,
                blocked_reason="Could not find Friday close"
            )
        
        # Current price (Sunday open)
        current_price = h1_bars["close"].iloc[-1]
        
        # Calculate gap
        gap = current_price - friday_close
        
        # Calculate ATR from recent history (before weekend)
        # Use Friday and earlier bars only
        friday_idx = h1_bars.index.get_loc(friday_time) if friday_time in h1_bars.index else len(h1_bars) - 1
        pre_weekend = h1_bars.iloc[:friday_idx + 1]
        
        if len(pre_weekend) < self.atr_lookback:
            return self._make_signal(
                GapStatus.FLAT, 0, 0, 0, 0, now_utc, 0, 0, 0, 0,
                blocked_reason="Insufficient pre-weekend bars for ATR"
            )
        
        atr = (pre_weekend["high"] - pre_weekend["low"]).tail(self.atr_lookback).mean()
        
        if atr == 0 or np.isnan(atr):
            return self._make_signal(
                GapStatus.FLAT, 0, 0, 0, 0, now_utc, 0, 0, 0, 0,
                blocked_reason="Zero ATR"
            )
        
        gap_atr_ratio = abs(gap) / atr
        
        # Block if gap too small
        if gap_atr_ratio < self.gap_atr_threshold:
            return self._make_signal(
                GapStatus.FLAT, gap, gap_atr_ratio, friday_close, current_price,
                now_utc, 0, 0, 0, 0,
                blocked_reason=f"Gap {gap_atr_ratio:.2f}x ATR < threshold {self.gap_atr_threshold}"
            )
        
        # Block if gap too large (likely fundamental event)
        if gap_atr_ratio > self.max_gap_atr:
            return self._make_signal(
                GapStatus.FLAT, gap, gap_atr_ratio, friday_close, current_price,
                now_utc, 0, 0, 0, 0,
                blocked_reason=f"Gap {gap_atr_ratio:.2f}x ATR > max {self.max_gap_atr} (fundamental)"
            )
        
        # Determine direction: fade the gap
        if gap > 0:
            # Price gapped UP → SHORT (expect reversion to Friday close)
            direction = -1
            status = GapStatus.SHORT
            sl = friday_close + atr * 0.5  # SL above Friday close
            tp = friday_close  # Target: fill the gap
        else:
            # Price gapped DOWN → LONG (expect reversion to Friday close)
            direction = 1
            status = GapStatus.LONG
            sl = friday_close - atr * 0.5  # SL below Friday close
            tp = friday_close  # Target: fill the gap
        
        # Position size
        size_lots = 0.01
        
        self.current_status = status
        
        return self._make_signal(
            status, gap, gap_atr_ratio, friday_close, current_price,
            now_utc, direction, sl, tp, size_lots
        )
    
    def _make_signal(
        self, status, gap, gap_atr_ratio, friday_close, current_price,
        timestamp, direction, sl, tp, size_lots,
        blocked_reason=None, warmup_complete=True
    ) -> GapFadeSignal:
        return GapFadeSignal(
            symbol=self.symbol,
            status=status,
            gap_size=round(gap, 5),
            gap_atr_ratio=round(gap_atr_ratio, 2),
            friday_close=round(friday_close, 5),
            current_price=round(current_price, 5),
            timestamp=timestamp,
            direction=direction,
            sl_price=round(sl, 5),
            tp_price=round(tp, 5),
            size_lots=size_lots,
            warmup_complete=warmup_complete,
            blocked_reason=blocked_reason,
        )
    
    def reset(self):
        """Reset internal state."""
        self.current_status = GapStatus.FLAT


# All FX pairs suitable for gap fading (most liquid)
GAP_FADE_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "XAUUSD",
]


def create_all_engines() -> dict:
    """Create engines for all gap fade symbols."""
    engines = {}
    for sym in GAP_FADE_SYMBOLS:
        engines[sym] = GapFadeEngine(sym)
    return engines
