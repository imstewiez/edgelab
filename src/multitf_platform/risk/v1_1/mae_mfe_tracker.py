"""MAE (Maximum Adverse Excursion) / MFE (Maximum Favorable Excursion) Tracker.

Tracks how far each trade went against you (MAE) and for you (MFE) before closing.
Used to optimize SL/TP distances based on actual price behavior.

- If MAE > 1.5x SL on average → SL is too tight
- If MFE > 2x TP on average → TP is too conservative
"""
from typing import Dict, List, Optional
from collections import defaultdict


class MAEMFETracker:
    """Track MAE and MFE per symbol for SL/TP optimization."""
    
    def __init__(self):
        self.trades: Dict[str, List[dict]] = defaultdict(list)
    
    def record_trade(self, symbol: str, direction: int, entry_price: float,
                     exit_price: float, sl: float, tp: float,
                     mae_price: Optional[float] = None,
                     mfe_price: Optional[float] = None):
        """Record a completed trade with MAE/MFE data.
        
        Args:
            symbol: Asset symbol
            direction: 1=LONG, -1=SHORT
            entry_price: Entry price
            exit_price: Exit price
            sl: Stop loss price
            tp: Take profit price
            mae_price: Worst price reached during trade (optional)
            mfe_price: Best price reached during trade (optional)
        """
        risk_distance = abs(entry_price - sl)
        profit_distance = abs(exit_price - entry_price)
        
        # Estimate MAE/MFE if not provided
        if mae_price is None:
            # Conservative estimate: if trade was a loss, MAE ≈ SL distance
            mae_price = sl if direction == 1 else sl
        if mfe_price is None:
            # Conservative estimate: if trade was a win, MFE ≈ TP distance
            mfe_price = tp if direction == 1 else tp
        
        mae = abs(entry_price - mae_price)
        mfe = abs(entry_price - mfe_price)
        
        mae_multiple = mae / risk_distance if risk_distance > 0 else 0
        mfe_multiple = mfe / risk_distance if risk_distance > 0 else 0
        profit_multiple = profit_distance / risk_distance if risk_distance > 0 else 0
        
        self.trades[symbol].append({
            "direction": direction,
            "entry": entry_price,
            "exit": exit_price,
            "sl": sl,
            "tp": tp,
            "mae": mae,
            "mfe": mfe,
            "mae_multiple": mae_multiple,
            "mfe_multiple": mfe_multiple,
            "profit_multiple": profit_multiple,
            "pnl": profit_distance if direction == 1 else -profit_distance,
        })
        
        # Keep last 100 trades per symbol
        self.trades[symbol] = self.trades[symbol][-100:]
    
    def get_recommendations(self, symbol: str) -> dict:
        """Get SL/TP recommendations based on MAE/MFE history.
        
        Returns dict with recommended_sl_mult, recommended_tp_mult, and reasoning.
        """
        trades = self.trades.get(symbol, [])
        if len(trades) < 10:
            return {
                "sl_mult": 1.0,
                "tp_mult": 2.0,
                "reason": "Insufficient MAE/MFE data",
                "sufficient_data": False,
            }
        
        avg_mae = sum(t["mae_multiple"] for t in trades) / len(trades)
        avg_mfe = sum(t["mfe_multiple"] for t in trades) / len(trades)
        
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        
        avg_mae_wins = sum(t["mae_multiple"] for t in wins) / len(wins) if wins else 0
        avg_mae_losses = sum(t["mae_multiple"] for t in losses) / len(losses) if losses else 0
        
        # Recommendations
        sl_mult = 1.0
        tp_mult = 2.0
        reasons = []
        
        if avg_mae > 1.3:
            sl_mult = round(avg_mae * 1.1, 1)
            reasons.append(f"MAE avg {avg_mae:.1f}x risk → widen SL to {sl_mult:.1f}x")
        
        if avg_mfe > 2.5:
            tp_mult = round(avg_mfe * 0.8, 1)
            reasons.append(f"MFE avg {avg_mfe:.1f}x risk → extend TP to {tp_mult:.1f}x")
        elif avg_mfe < 1.5:
            tp_mult = 1.5
            reasons.append(f"MFE avg {avg_mfe:.1f}x risk → reduce TP to 1.5x")
        
        if avg_mae_losses < 0.8 and len(losses) > 5:
            reasons.append("Losses hit SL too fast — consider wider SL")
        
        return {
            "sl_mult": sl_mult,
            "tp_mult": tp_mult,
            "reason": " | ".join(reasons) if reasons else "Current SL/TP optimal",
            "sufficient_data": True,
            "avg_mae": round(avg_mae, 2),
            "avg_mfe": round(avg_mfe, 2),
            "avg_mae_wins": round(avg_mae_wins, 2),
            "avg_mae_losses": round(avg_mae_losses, 2),
            "trade_count": len(trades),
        }
    
    def get_diagnostics(self, symbol: str) -> dict:
        """Get full MAE/MFE diagnostics for a symbol."""
        trades = self.trades.get(symbol, [])
        if not trades:
            return {"trade_count": 0}
        
        return {
            "trade_count": len(trades),
            "avg_mae": sum(t["mae"] for t in trades) / len(trades),
            "avg_mfe": sum(t["mfe"] for t in trades) / len(trades),
            "avg_mae_multiple": sum(t["mae_multiple"] for t in trades) / len(trades),
            "avg_mfe_multiple": sum(t["mfe_multiple"] for t in trades) / len(trades),
            "max_mae": max(t["mae"] for t in trades),
            "max_mfe": max(t["mfe"] for t in trades),
        }
