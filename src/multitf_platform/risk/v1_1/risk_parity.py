"""Risk Parity portfolio weight calculator.

Instead of fixed inverse-vol weights, computes weights so that each
asset contributes equal risk to the portfolio, accounting for
current correlations.
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional


class RiskParityWeights:
    """Compute risk-parity weights from recent returns.
    
    Each asset contributes equally to total portfolio volatility.
    """
    
    def __init__(self, lookback_bars: int = 50):
        self.lookback = lookback_bars
        self.price_history: Dict[str, pd.Series] = {}
    
    def update_prices(self, symbol: str, bars: pd.DataFrame):
        """Record latest close prices for a symbol."""
        if bars is not None and len(bars) > 0:
            closes = bars["close"]
            if symbol not in self.price_history:
                self.price_history[symbol] = closes
            else:
                self.price_history[symbol] = pd.concat([
                    self.price_history[symbol],
                    closes
                ]).drop_duplicates().tail(self.lookback * 2)
    
    def _get_returns(self, symbol: str) -> pd.Series:
        """Get return series for a symbol."""
        if symbol not in self.price_history:
            return pd.Series(dtype=float)
        prices = self.price_history[symbol].tail(self.lookback)
        if len(prices) < 10:
            return pd.Series(dtype=float)
        return prices.pct_change().dropna()
    
    def calculate_weights(self, symbols: List[str]) -> Dict[str, float]:
        """Calculate risk-parity weights for given symbols.
        
        Uses inverse volatility as fallback if insufficient data.
        Returns weights that sum to 1.0.
        """
        # Collect returns
        returns_dict = {}
        for sym in symbols:
            r = self._get_returns(sym)
            if len(r) >= 10:
                returns_dict[sym] = r
        
        if len(returns_dict) < len(symbols):
            # Fallback: equal weights
            w = 1.0 / len(symbols)
            return {sym: w for sym in symbols}
        
        # Align returns
        df = pd.DataFrame(returns_dict).dropna()
        if len(df) < 10:
            w = 1.0 / len(symbols)
            return {sym: w for sym in symbols}
        
        # Covariance matrix
        cov = df.cov().values
        n = len(symbols)
        
        # Risk parity: solve for weights where marginal risk contribution is equal
        # Use iterative approach (Newton-Raphson style)
        weights = np.ones(n) / n
        
        for _ in range(50):
            # Portfolio variance = w^T * Cov * w
            port_var = weights @ cov @ weights
            if port_var <= 0:
                break
            
            # Marginal risk contribution for each asset
            mrc = (cov @ weights) / np.sqrt(port_var)
            
            # Risk contribution
            rc = weights * mrc
            
            # Target: equal RC
            target_rc = port_var / n
            
            # Update weights
            new_weights = np.zeros(n)
            for i in range(n):
                if mrc[i] > 0:
                    new_weights[i] = target_rc / mrc[i]
                else:
                    new_weights[i] = weights[i]
            
            # Normalize
            total = new_weights.sum()
            if total > 0:
                new_weights /= total
            else:
                new_weights = np.ones(n) / n
            
            # Check convergence
            if np.max(np.abs(new_weights - weights)) < 1e-6:
                break
            weights = new_weights
        
        # Ensure positive and normalize
        weights = np.maximum(weights, 0)
        weights /= weights.sum()
        
        return {sym: float(weights[i]) for i, sym in enumerate(symbols)}
    
    def get_diagnostics(self, symbols: List[str]) -> dict:
        """Get diagnostics for current weights."""
        weights = self.calculate_weights(symbols)
        
        returns_dict = {}
        for sym in symbols:
            r = self._get_returns(sym)
            if len(r) >= 10:
                returns_dict[sym] = r
        
        if len(returns_dict) < len(symbols):
            return {"weights": weights, "method": "fallback"}
        
        df = pd.DataFrame(returns_dict).dropna()
        cov = df.cov().values
        w = np.array([weights[sym] for sym in symbols])
        
        port_vol = np.sqrt(w @ cov @ w) if len(df) >= 10 else 0
        
        # Individual risk contributions
        mrc = (cov @ w) / port_vol if port_vol > 0 else np.zeros(len(symbols))
        rc = {sym: float(w[i] * mrc[i]) for i, sym in enumerate(symbols)}
        
        return {
            "weights": weights,
            "portfolio_volatility": float(port_vol),
            "risk_contributions": rc,
            "method": "risk_parity",
        }
