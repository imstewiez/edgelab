"""
Portfolio-level risk management.
Handles drawdown limits, correlation checks, volatility targeting, and event filters.
"""
from typing import Dict, Optional
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class RiskLimits:
    max_portfolio_drawdown_pct: float = -15.0
    max_daily_loss_pct: float = -2.0
    max_strategy_correlation: float = 0.70
    target_portfolio_vol: float = 0.10  # 10% annualized
    max_single_strategy_weight: float = 1.0
    min_single_strategy_weight: float = 0.0
    max_leverage: float = 1.0


class RiskManager:
    """
    Monitors portfolio risk and applies overlays.
    """
    
    def __init__(self, limits: RiskLimits = None):
        self.limits = limits or RiskLimits()
        self.peak_equity = 0.0
        self.current_drawdown = 0.0
        self.daily_pnl = 0.0
    
    def check_drawdown(self, equity: float) -> bool:
        """Return False if max drawdown exceeded (HALT trading)."""
        if equity > self.peak_equity:
            self.peak_equity = equity
        dd = (equity - self.peak_equity) / self.peak_equity * 100
        self.current_drawdown = dd
        return dd > self.limits.max_portfolio_drawdown_pct
    
    def check_correlation(self, returns_df: pd.DataFrame) -> Dict[str, bool]:
        """
        Check pairwise correlations between strategies.
        Returns dict of strategy -> bool (True if okay, False if too correlated).
        """
        if returns_df is None or len(returns_df.columns) < 2:
            return {}
        
        corr_matrix = returns_df.corr()
        flags = {col: True for col in returns_df.columns}
        
        for i, col1 in enumerate(corr_matrix.columns):
            for j, col2 in enumerate(corr_matrix.columns):
                if i >= j:
                    continue
                corr = corr_matrix.iloc[i, j]
                if abs(corr) > self.limits.max_strategy_correlation:
                    # Flag both as potentially problematic
                    flags[col1] = False
                    flags[col2] = False
        
        return flags
    
    def apply_vol_target(self, weights: dict, strategy_vols: dict) -> dict:
        """
        Scale total portfolio exposure to target volatility.
        """
        if not weights or not strategy_vols:
            return weights
        
        # Estimate portfolio vol from weighted average
        port_var = sum(
            weights.get(s, 0)**2 * strategy_vols.get(s, 0.20)**2
            for s in weights
        )
        port_vol = np.sqrt(port_var) if port_var > 0 else 0.20
        
        if port_vol == 0:
            return weights
        
        # Scale factor
        scale = min(self.limits.target_portfolio_vol / port_vol, self.limits.max_leverage)
        
        return {k: v * scale for k, v in weights.items()}
    
    def get_status(self) -> dict:
        return {
            "peak_equity": self.peak_equity,
            "current_drawdown_pct": round(self.current_drawdown, 2),
            "drawdown_limit_pct": self.limits.max_portfolio_drawdown_pct,
            "daily_loss_limit_pct": self.limits.max_daily_loss_pct,
        }
