"""GARCH(1,1) volatility forecasting for position sizing.

Uses conditional volatility forecasting instead of historical realized vol.
GARCH captures volatility clustering — when vol is high, it tends to stay high.

Formula: sigma^2_t = omega + alpha * r^2_{t-1} + beta * sigma^2_{t-1}
"""
import numpy as np
import pandas as pd
from typing import Optional


class GARCHForecaster:
    """Simple GARCH(1,1) volatility forecaster.
    
    Estimates omega, alpha, beta via MLE-like approach on recent returns.
    Forecasts next-period volatility for dynamic position sizing.
    """
    
    def __init__(self, lookback: int = 100):
        self.lookback = lookback
        self.omega = None
        self.alpha = None
        self.beta = None
        self.last_vol = None
        self._fitted = False
    
    def _fit(self, returns: np.ndarray) -> bool:
        """Fit GARCH(1,1) parameters via method of moments."""
        if len(returns) < 30:
            return False
        
        # Use squared returns as proxy for variance
        sq_returns = returns ** 2
        
        # Long-run variance (unconditional)
        var_uncond = np.var(returns)
        
        # Simple estimation: EWMA-style with grid search for best alpha,beta
        best_score = float('inf')
        best_params = (0.01, 0.1, 0.85)
        
        for alpha in np.arange(0.02, 0.25, 0.03):
            for beta in np.arange(0.50, 0.97, 0.05):
                if alpha + beta >= 0.999:
                    continue
                omega = var_uncond * (1 - alpha - beta)
                if omega <= 0:
                    continue
                
                # Simulate GARCH variances
                var_t = var_uncond
                log_lik = 0
                for r in returns:
                    var_t = omega + alpha * (r ** 2) + beta * var_t
                    if var_t <= 0:
                        log_lik = float('inf')
                        break
                    log_lik += np.log(var_t) + (r ** 2) / var_t
                
                if log_lik < best_score:
                    best_score = log_lik
                    best_params = (omega, alpha, beta)
        
        self.omega, self.alpha, self.beta = best_params
        self._fitted = True
        
        # Compute last volatility
        var_t = var_uncond
        for r in returns:
            var_t = self.omega + self.alpha * (r ** 2) + self.beta * var_t
        self.last_vol = np.sqrt(var_t)
        return True
    
    def forecast_volatility(self, bars: pd.DataFrame) -> Optional[float]:
        """Forecast next-period annualized volatility %.
        
        Returns None if insufficient data.
        """
        if len(bars) < self.lookback:
            return None
        
        returns = bars["close"].pct_change().dropna().values
        if len(returns) < 30:
            return None
        
        recent = returns[-self.lookback:]
        if not self._fit(recent):
            # Fallback: EWMA
            ewma_var = pd.Series(recent**2).ewm(span=20).mean().iloc[-1]
            return np.sqrt(ewma_var) * np.sqrt(252 * 24) * 100
        
        # One-step ahead forecast
        last_return = returns[-1]
        forecast_var = self.omega + self.alpha * (last_return ** 2) + self.beta * (self.last_vol ** 2)
        forecast_vol = np.sqrt(max(forecast_var, 1e-12))
        
        # Annualize
        annualized = forecast_vol * np.sqrt(252 * 24) * 100
        return annualized
    
    def get_position_scale(self, bars: pd.DataFrame, target_vol: float = 15.0) -> float:
        """Get position scale factor based on GARCH forecast.
        
        Args:
            target_vol: Target annualized volatility % (default 15%)
        
        Returns:
            Scale factor (0.1 to 2.0)
        """
        forecast = self.forecast_volatility(bars)
        if forecast is None or forecast <= 0:
            return 1.0
        
        scale = target_vol / forecast
        return max(0.1, min(2.0, scale))
    
    def get_diagnostics(self) -> dict:
        return {
            "omega": self.omega,
            "alpha": self.alpha,
            "beta": self.beta,
            "persistence": (self.alpha + self.beta) if self.alpha else None,
            "last_vol": self.last_vol,
            "fitted": self._fitted,
        }
