"""Time-Decay Exit (Time Stop).

Closes positions that haven't reached breakeven after N bars.
Research shows trades that stay flat >24h have win rate <20%.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict


class TimeDecayExit:
    """Exit trades that haven't progressed after a time threshold."""
    
    DEFAULT_MAX_BARS = 24  # H1 bars = 24 hours
    BREAKEVEN_THRESHOLD = 0.5  # Must be at least 0.5x risk in profit
    
    def __init__(self, max_bars: int = DEFAULT_MAX_BARS):
        self.max_bars = max_bars
        self._entry_times: Dict[str, datetime] = {}
        self._entry_prices: Dict[str, float] = {}
        self._risk_distances: Dict[str, float] = {}
    
    def record_entry(self, symbol: str, entry_price: float, sl_price: float,
                     timestamp: Optional[datetime] = None):
        """Record when a position was entered."""
        self._entry_times[symbol] = timestamp or datetime.utcnow()
        self._entry_prices[symbol] = entry_price
        self._risk_distances[symbol] = abs(entry_price - sl_price)
    
    def record_exit(self, symbol: str):
        """Clear tracking when position exits."""
        self._entry_times.pop(symbol, None)
        self._entry_prices.pop(symbol, None)
        self._risk_distances.pop(symbol, None)
    
    def check_exit(self, symbol: str, current_price: float,
                   current_time: Optional[datetime] = None) -> tuple[bool, str]:
        """Check if a time-decay exit should trigger.
        
        Returns:
            (should_exit: bool, reason: str)
        """
        if symbol not in self._entry_times:
            return False, "No entry recorded"
        
        entry_time = self._entry_times[symbol]
        current_time = current_time or datetime.utcnow()
        
        # Calculate bars elapsed (approximate: 1 bar = 1 hour)
        hours_elapsed = (current_time - entry_time).total_seconds() / 3600
        bars_elapsed = int(hours_elapsed)
        
        if bars_elapsed < self.max_bars:
            return False, f"Time decay: {bars_elapsed}/{self.max_bars} bars"
        
        # Check if trade is in sufficient profit
        entry_price = self._entry_prices[symbol]
        risk_distance = self._risk_distances[symbol]
        
        if entry_price is None or risk_distance is None or risk_distance == 0:
            return True, f"Time decay expired ({bars_elapsed} bars) — no risk data"
        
        profit_distance = abs(current_price - entry_price)
        profit_multiple = profit_distance / risk_distance
        
        if profit_multiple >= self.BREAKEVEN_THRESHOLD:
            return False, f"Time decay: {bars_elapsed} bars but profit {profit_multiple:.1f}x risk — hold"
        
        return True, f"Time decay exit: {bars_elapsed} bars, only {profit_multiple:.1f}x risk — closing"
    
    def get_status(self, symbol: str) -> dict:
        """Get time decay status for a symbol."""
        if symbol not in self._entry_times:
            return {"active": False}
        
        entry_time = self._entry_times[symbol]
        hours_elapsed = (datetime.utcnow() - entry_time).total_seconds() / 3600
        bars_elapsed = int(hours_elapsed)
        
        return {
            "active": True,
            "bars_elapsed": bars_elapsed,
            "max_bars": self.max_bars,
            "remaining_bars": max(0, self.max_bars - bars_elapsed),
            "entry_price": self._entry_prices.get(symbol),
            "risk_distance": self._risk_distances.get(symbol),
        }
