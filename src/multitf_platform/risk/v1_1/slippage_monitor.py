"""Slippage and Execution Quality Monitor.

Tracks difference between expected fill price and actual execution price.
Raises alerts when slippage exceeds thresholds (broker issue or illiquidity).
"""
from typing import Dict, List, Optional
from collections import deque


class SlippageMonitor:
    """Monitor execution slippage per symbol.
    
    Thresholds:
    - EURUSD: > 2 pips = warning
    - XAUUSD: > $0.50 = warning
    - NAS100: > 5 points = warning
    """
    
    THRESHOLDS = {
        "EURUSD": 0.00020,  # 2 pips
        "XAUUSD": 0.50,     # $0.50
        "NAS100": 5.0,      # 5 points
    }
    DEFAULT_THRESHOLD = 0.00030
    
    def __init__(self, max_history: int = 50):
        self.max_history = max_history
        self.slippages: Dict[str, deque] = {}
    
    def record_slippage(self, symbol: str, expected_price: float,
                        actual_price: float, direction: int) -> dict:
        """Record slippage for a trade.
        
        Args:
            symbol: Asset symbol
            expected_price: Price at signal time
            actual_price: Actual fill price
            direction: 1=LONG, -1=SHORT
        
        Returns:
            Dict with slippage amount, slippage_pct, alert status
        """
        if symbol not in self.slippages:
            self.slippages[symbol] = deque(maxlen=self.max_history)
        
        slippage = actual_price - expected_price
        # For shorts, negative slippage is bad (filled lower than expected)
        if direction == -1:
            slippage = expected_price - actual_price
        
        slippage = abs(slippage)
        slippage_pct = (slippage / expected_price * 100) if expected_price > 0 else 0
        
        threshold = self.THRESHOLDS.get(symbol, self.DEFAULT_THRESHOLD)
        alert = slippage > threshold
        
        entry = {
            "symbol": symbol,
            "expected": expected_price,
            "actual": actual_price,
            "slippage": slippage,
            "slippage_pct": slippage_pct,
            "alert": alert,
        }
        self.slippages[symbol].append(entry)
        
        return entry
    
    def get_average_slippage(self, symbol: str) -> Optional[float]:
        """Get average slippage for a symbol."""
        if symbol not in self.slippages or len(self.slippages[symbol]) == 0:
            return None
        slips = [e["slippage"] for e in self.slippages[symbol]]
        return sum(slips) / len(slips)
    
    def get_alert_count(self, symbol: str) -> int:
        """Count alert-level slippages."""
        if symbol not in self.slippages:
            return 0
        return sum(1 for e in self.slippages[symbol] if e["alert"])
    
    def should_block_trading(self, symbol: str, alert_threshold: int = 3) -> tuple[bool, str]:
        """Block trading if too many recent slippage alerts.
        
        Returns:
            (block: bool, reason: str)
        """
        alerts = self.get_alert_count(symbol)
        total = len(self.slippages.get(symbol, []))
        
        if total < 5:
            return False, "Insufficient data"
        
        alert_rate = alerts / total
        
        if alerts >= alert_threshold and alert_rate > 0.3:
            return True, f"Slippage alert: {alerts}/{total} ({alert_rate:.0%}) exceeded threshold"
        
        return False, f"Slippage OK: {alerts}/{total} alerts"
    
    def get_diagnostics(self) -> dict:
        """Get full slippage diagnostics."""
        result = {}
        for symbol, entries in self.slippages.items():
            if not entries:
                continue
            slips = [e["slippage"] for e in entries]
            alerts = sum(1 for e in entries if e["alert"])
            result[symbol] = {
                "count": len(entries),
                "avg_slippage": sum(slips) / len(slips),
                "max_slippage": max(slips),
                "alerts": alerts,
                "alert_rate": alerts / len(entries),
            }
        return result
