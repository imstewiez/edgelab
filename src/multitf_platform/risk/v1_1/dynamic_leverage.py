"""Dynamic Leverage based on Drawdown.

Reduces leverage automatically as equity falls from peak.
This is the opposite of what amateur traders do (increase size when losing).

Tiers:
- Equity > 90% of peak  → leverage cap 1:1000
- Equity 75-90%         → leverage cap 1:500
- Equity 60-75%         → leverage cap 1:200
- Equity < 60%          → leverage cap 1:50
"""
from typing import Optional


class DynamicLeverage:
    """Adjust max leverage based on current drawdown from peak equity."""
    
    TIERS = [
        (0.90, 1000, "Normal"),
        (0.75, 500, "Caution"),
        (0.60, 200, "Restricted"),
        (0.00, 50, "Conservation"),
    ]
    
    def __init__(self):
        self.peak_equity = 0.0
    
    def update_peak(self, equity: float):
        """Update peak equity if current is higher."""
        if equity > self.peak_equity:
            self.peak_equity = equity
    
    def get_max_leverage(self, equity: float) -> tuple[int, str, float]:
        """Get maximum allowed leverage for current equity.
        
        Returns:
            (max_leverage: int, tier_name: str, drawdown_pct: float)
        """
        self.update_peak(equity)
        
        if self.peak_equity <= 0:
            return 1000, "Normal", 0.0
        
        drawdown_pct = (self.peak_equity - equity) / self.peak_equity * 100
        equity_ratio = equity / self.peak_equity
        
        for threshold, leverage, name in self.TIERS:
            if equity_ratio >= threshold:
                return leverage, name, drawdown_pct
        
        return 50, "Conservation", drawdown_pct
    
    def get_position_size_cap(self, equity: float, proposed_lots: float,
                              broker_leverage: int = 1000) -> tuple[float, str]:
        """Cap position size based on dynamic leverage.
        
        Returns:
            (capped_lots: float, reason: str)
        """
        max_lev, tier, dd = self.get_max_leverage(equity)
        effective_lev = min(max_lev, broker_leverage)
        
        if effective_lev >= broker_leverage:
            return proposed_lots, f"Leverage OK: {tier} (DD {dd:.1f}%)"
        
        scale = effective_lev / broker_leverage
        capped = proposed_lots * scale
        
        return capped, f"Leverage reduced to 1:{effective_lev} ({tier}, DD {dd:.1f}%)"
    
    def get_diagnostics(self, equity: float) -> dict:
        lev, tier, dd = self.get_max_leverage(equity)
        return {
            "peak_equity": self.peak_equity,
            "current_equity": equity,
            "drawdown_pct": dd,
            "tier": tier,
            "max_leverage": lev,
        }
