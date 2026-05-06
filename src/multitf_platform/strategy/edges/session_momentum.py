"""Session Open Momentum Scalper.

Exploits the well-documented "session open effect" in FX markets:
- London open (08:00 GMT): highest FX volume of the day
- NY open (13:00 GMT): second volume surge, often continues London move

Research shows that the first hour after session open has:
- Elevated volatility (2-3x normal)
- Persistent directional moves (momentum effect)
- 60-70% follow-through rate when range expands

Logic:
1. Identify if current H1 bar is within session open window
2. Check if current bar's range > 1.5x average range (breakout confirmation)
3. Direction = sign(close - open) of breakout bar
4. SL = opposite extreme of breakout bar (tight, ~0.5R)
5. TP = 1R (quick scalp, don't get greedy)
6. Max hold time: 4 hours (time-decay exit)

Only trades during London (08:00-09:00) and NY (13:00-14:00) opens.
Avoids Asian session (low volume, chop).
"""
from dataclasses import dataclass
from typing import Optional
from enum import Enum
import pandas as pd
import numpy as np


class SessionType(Enum):
    NONE = 0
    LONDON = 1
    NEW_YORK = 2


class MomentumStatus(Enum):
    FLAT = 0
    LONG = 1
    SHORT = -1


@dataclass(frozen=True)
class SessionMomentumSignal:
    """Signal output from Session Momentum engine."""
    symbol: str
    status: MomentumStatus
    session: SessionType
    bar_range: float
    avg_range: float
    range_ratio: float
    open_price: float
    close_price: float
    timestamp: pd.Timestamp
    direction: int  # 1=LONG, -1=SHORT, 0=FLAT
    sl_price: float
    tp_price: float
    size_lots: float
    max_hold_hours: int = 4
    warmup_complete: bool = True
    blocked_reason: Optional[str] = None
    
    @property
    def is_active(self) -> bool:
        return self.status != MomentumStatus.FLAT and self.warmup_complete


class SessionMomentumEngine:
    """Session open momentum scalper.
    
    Args:
        symbol: Symbol to trade (should be liquid: EURUSD, GBPUSD, XAUUSD)
        range_lookback: Bars for average range calculation (default 20)
        range_mult: Breakout threshold as multiple of avg range (default 1.5)
        session_windows: Dict of {SessionType: (start_hour, end_hour)} in GMT
    """
    
    VERSION = "1.0.0"
    
    def __init__(
        self,
        symbol: str,
        range_lookback: int = 20,
        range_mult: float = 1.5,
        session_windows: dict = None,
    ):
        self.symbol = symbol
        self.range_lookback = range_lookback
        self.range_mult = range_mult
        self.session_windows = session_windows or {
            SessionType.LONDON: (8, 9),    # 08:00-09:00 GMT
            SessionType.NEW_YORK: (13, 14), # 13:00-14:00 GMT
        }
        self.current_status = MomentumStatus.FLAT
    
    def generate_signal(
        self,
        h1_bars: pd.DataFrame,
        equity: float = 10000.0,
        now_utc: Optional[pd.Timestamp] = None,
    ) -> SessionMomentumSignal:
        """Generate session momentum signal.
        
        Args:
            h1_bars: DataFrame [open, high, low, close] indexed by UTC
            equity: Current account equity
            now_utc: Current timestamp (default: last bar)
            
        Returns:
            SessionMomentumSignal
        """
        if now_utc is None:
            now_utc = h1_bars.index[-1]
        
        if len(h1_bars) < self.range_lookback + 5:
            return self._make_signal(
                MomentumStatus.FLAT, SessionType.NONE, 0, 0, 0,
                0, 0, now_utc, 0, 0, 0, 0,
                blocked_reason=f"Insufficient bars: {len(h1_bars)}"
            )
        
        # Determine if we're in a session open window
        hour = now_utc.hour
        session = SessionType.NONE
        for st, (start, end) in self.session_windows.items():
            if start <= hour < end:
                session = st
                break
        
        if session == SessionType.NONE:
            return self._make_signal(
                MomentumStatus.FLAT, SessionType.NONE, 0, 0, 0,
                0, 0, now_utc, 0, 0, 0, 0,
                blocked_reason=f"Outside session window (hour={hour})"
            )
        
        # Current bar metrics
        current = h1_bars.iloc[-1]
        bar_range = current["high"] - current["low"]
        bar_open = current["open"]
        bar_close = current["close"]
        bar_low = current["low"]
        bar_high = current["high"]
        
        # Average range over lookback
        ranges = h1_bars["high"] - h1_bars["low"]
        avg_range = ranges.tail(self.range_lookback).mean()
        
        if avg_range == 0 or np.isnan(avg_range):
            return self._make_signal(
                MomentumStatus.FLAT, session, bar_range, 0, 0,
                bar_open, bar_close, now_utc, 0, 0, 0, 0,
                blocked_reason="Zero average range"
            )
        
        range_ratio = bar_range / avg_range
        
        # Block if range is too small (no breakout)
        if range_ratio < self.range_mult:
            return self._make_signal(
                MomentumStatus.FLAT, session, bar_range, avg_range, range_ratio,
                bar_open, bar_close, now_utc, 0, 0, 0, 0,
                blocked_reason=f"Range ratio {range_ratio:.2f} < {self.range_mult}"
            )
        
        # Determine direction: close near high = bullish, close near low = bearish
        # Use the full bar's directional bias
        if bar_close > bar_open:
            direction = 1  # LONG
            status = MomentumStatus.LONG
            # SL = bar low (tight)
            sl = bar_low
            risk = bar_close - sl
            tp = bar_close + risk  # 1R
        elif bar_close < bar_open:
            direction = -1  # SHORT
            status = MomentumStatus.SHORT
            # SL = bar high (tight)
            sl = bar_high
            risk = sl - bar_close
            tp = bar_close - risk  # 1R
        else:
            return self._make_signal(
                MomentumStatus.FLAT, session, bar_range, avg_range, range_ratio,
                bar_open, bar_close, now_utc, 0, 0, 0, 0,
                blocked_reason="Neutral bar (open == close)"
            )
        
        # Block if risk is too small (likely just spread noise)
        point = self._estimate_point_value(bar_close)
        if risk < point * 5:
            return self._make_signal(
                MomentumStatus.FLAT, session, bar_range, avg_range, range_ratio,
                bar_open, bar_close, now_utc, 0, 0, 0, 0,
                blocked_reason=f"Risk too small: {risk:.5f}"
            )
        
        # Position size: fixed 0.01 lots for scalping (fast in/out)
        size_lots = 0.01
        
        # Update state
        self.current_status = status
        
        return self._make_signal(
            status, session, bar_range, avg_range, range_ratio,
            bar_open, bar_close, now_utc, direction, sl, tp, size_lots
        )
    
    def _estimate_point_value(self, price: float) -> float:
        """Estimate point size based on price magnitude."""
        if price > 1000:
            return 0.01  # Indices, gold
        elif price > 10:
            return 0.01  # JPY pairs
        else:
            return 0.0001  # Standard FX
    
    def _make_signal(
        self, status, session, bar_range, avg_range, range_ratio,
        open_price, close_price, timestamp, direction, sl, tp, size_lots,
        blocked_reason=None, warmup_complete=True
    ) -> SessionMomentumSignal:
        return SessionMomentumSignal(
            symbol=self.symbol,
            status=status,
            session=session,
            bar_range=round(bar_range, 5),
            avg_range=round(avg_range, 5),
            range_ratio=round(range_ratio, 2),
            open_price=round(open_price, 5),
            close_price=round(close_price, 5),
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
        self.current_status = MomentumStatus.FLAT


# Symbols suitable for session momentum (most liquid)
SESSION_SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]


def create_all_engines() -> dict:
    """Create engines for all session momentum symbols."""
    engines = {}
    for sym in SESSION_SYMBOLS:
        engines[sym] = SessionMomentumEngine(sym)
    return engines
