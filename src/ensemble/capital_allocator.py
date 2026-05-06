"""
Capital allocation across strategies using inverse-volatility weighting
with Sharpe-based filtering.
"""
import numpy as np
import pandas as pd


class CapitalAllocator:
    """
    Allocates capital across strategies based on:
    1. Recent Sharpe ratio (higher = more weight)
    2. Inverse volatility (lower vol = more weight)
    3. Regime suitability
    """
    
    def __init__(
        self,
        sharpe_weight: float = 0.6,
        inv_vol_weight: float = 0.4,
        min_weight: float = 0.0,
        max_weight: float = 1.0,
    ):
        self.sharpe_weight = sharpe_weight
        self.inv_vol_weight = inv_vol_weight
        self.min_weight = min_weight
        self.max_weight = max_weight
    
    def allocate(self, strategies, returns_df: pd.DataFrame = None) -> dict:
        """
        Allocate weights to active strategies.
        
        Args:
            strategies: List of StrategyRecord
            returns_df: DataFrame of strategy returns (columns = strategy names)
        
        Returns:
            Dict[str, float] of strategy name -> weight
        """
        if not strategies:
            return {}
        
        weights = {}
        scores = {}
        
        for rec in strategies:
            # Sharpe score (normalize to 0-1 range, clip negatives)
            sharpe_score = max(0, rec.avg_sharpe / 2.0)  # Sharpe 2.0 = max score
            
            # Inverse vol score
            vol = self._estimate_volatility(rec)
            inv_vol_score = 0.1 / max(vol, 0.01)  # Lower vol = higher score
            inv_vol_score = min(inv_vol_score, 1.0)  # Cap at 1.0
            
            # Combined score
            score = (self.sharpe_weight * sharpe_score + 
                    self.inv_vol_weight * inv_vol_score)
            scores[rec.name] = score
        
        # Normalize to sum to 1.0
        total_score = sum(scores.values())
        if total_score == 0:
            # Equal weight if all scores are zero
            equal_w = 1.0 / len(strategies)
            return {rec.name: equal_w for rec in strategies}
        
        for rec in strategies:
            w = scores[rec.name] / total_score
            w = max(self.min_weight, min(self.max_weight, w))
            weights[rec.name] = w
        
        # Renormalize after capping
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        
        return weights
    
    def _estimate_volatility(self, rec) -> float:
        """Estimate strategy volatility from return history."""
        if not rec.return_history:
            return 0.20  # Default 20% vol assumption
        rets = np.array(rec.return_history)
        if len(rets) < 2:
            return 0.20
        return max(float(np.std(rets)), 0.001)
