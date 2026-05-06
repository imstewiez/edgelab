"""Trade Expectancy Filter — only trade when EV is positive.

Expectancy = (WinRate × AvgWin) − (LossRate × AvgLoss)

Research shows EV is the only reliable long-term predictor of profitability.
A negative EV strategy loses money regardless of win rate or R/R.
"""
from typing import Optional, List


class ExpectancyFilter:
    """Filter trades based on historical expectancy.
    
    Uses recent trade history to compute per-symbol expectancy.
    Blocks trades when EV falls below threshold.
    """
    
    DEFAULT_THRESHOLD = 0.5  # Minimum $0.50 expected profit per trade
    MIN_TRADES = 10  # Need at least 10 trades for statistical significance
    
    def __init__(self, threshold: float = DEFAULT_THRESHOLD):
        self.threshold = threshold
        self._trade_history: List[dict] = []
    
    def add_trade(self, symbol: str, pnl: float):
        """Record a completed trade P&L."""
        self._trade_history.append({"symbol": symbol, "pnl": pnl})
        # Keep last 200 trades
        self._trade_history = self._trade_history[-200:]
    
    def calculate_expectancy(self, symbol: Optional[str] = None) -> dict:
        """Calculate expectancy for a symbol (or all trades if None).
        
        Returns dict with expectancy, win_rate, avg_win, avg_loss, trade_count.
        """
        trades = self._trade_history
        if symbol:
            trades = [t for t in trades if t["symbol"] == symbol]
        
        if len(trades) < self.MIN_TRADES:
            return {
                "expectancy": None,
                "win_rate": None,
                "avg_win": None,
                "avg_loss": None,
                "trade_count": len(trades),
                "sufficient_data": False,
            }
        
        pnls = [t["pnl"] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        win_rate = len(wins) / len(pnls)
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0
        
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        
        return {
            "expectancy": expectancy,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "trade_count": len(trades),
            "sufficient_data": True,
        }
    
    def check_trade(self, symbol: Optional[str] = None) -> tuple[bool, float, str]:
        """Check if a new trade should be allowed based on expectancy.
        
        Returns:
            (allow: bool, expectancy: float, reason: str)
        """
        stats = self.calculate_expectancy(symbol)
        
        if not stats["sufficient_data"]:
            return True, 0.0, f"Insufficient history ({stats['trade_count']} trades) — allowing by default"
        
        ev = stats["expectancy"]
        
        if ev >= self.threshold:
            return True, ev, f"EV=${ev:.2f} >= threshold ${self.threshold:.2f}"
        elif ev > 0:
            return True, ev, f"EV=${ev:.2f} positive but below threshold"
        else:
            return False, ev, f"EV=${ev:.2f} NEGATIVE — trade blocked"
    
    def get_all_expectancies(self, symbols: List[str]) -> dict:
        """Get expectancy for all symbols."""
        return {sym: self.calculate_expectancy(sym) for sym in symbols}
