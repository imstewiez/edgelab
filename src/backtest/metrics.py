"""
Performance metrics for backtest results.
"""
from typing import Dict, Optional

import numpy as np
import pandas as pd


def calculate_metrics(
    equity_curve: pd.Series,
    trades: Optional[pd.DataFrame] = None,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252 * 24  # Default: hourly data
) -> Dict:
    """
    Calculate comprehensive performance metrics from an equity curve.
    
    Args:
        equity_curve: Series of portfolio values indexed by time
        trades: Optional DataFrame with individual trade details
        risk_free_rate: Annual risk-free rate (default 0)
        periods_per_year: Number of periods in a year for annualization
    
    Returns:
        Dict of metric names to values
    """
    returns = equity_curve.pct_change().dropna()
    if len(returns) < 2:
        return {"error": "Insufficient data"}
    
    # Basic return metrics
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0] - 1
    log_returns = np.log(equity_curve / equity_curve.shift(1)).dropna()
    
    # Annualized metrics
    ann_return = log_returns.mean() * periods_per_year
    ann_vol = log_returns.std() * np.sqrt(periods_per_year)
    
    # Sharpe ratio
    sharpe = (ann_return - risk_free_rate) / ann_vol if ann_vol > 0 else np.nan
    
    # Sortino ratio (downside deviation)
    downside = log_returns[log_returns < 0].std() * np.sqrt(periods_per_year)
    sortino = (ann_return - risk_free_rate) / downside if downside > 0 else np.nan
    
    # Maximum drawdown
    cummax = equity_curve.cummax()
    drawdown = (equity_curve - cummax) / cummax
    max_dd = drawdown.min()
    max_dd_duration = _max_drawdown_duration(drawdown)
    
    # Calmar ratio
    calmar = ann_return / abs(max_dd) if max_dd != 0 else np.nan
    
    # Skewness and kurtosis
    skew = log_returns.skew()
    kurt = log_returns.kurtosis()
    
    # Value at Risk (95%)
    var_95 = np.percentile(log_returns, 5)
    cvar_95 = log_returns[log_returns <= var_95].mean()
    
    metrics = {
        "total_return_pct": round(total_return * 100, 2),
        "ann_return_pct": round(ann_return * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "calmar_ratio": round(calmar, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "max_dd_duration_bars": int(max_dd_duration),
        "skewness": round(skew, 3),
        "kurtosis": round(kurt, 3),
        "var_95_daily": round(var_95 * 100, 4),
        "cvar_95_daily": round(cvar_95 * 100, 4),
        "num_bars": len(returns),
    }
    
    # Trade-level metrics
    if trades is not None and len(trades) > 0:
        trade_returns = trades["return"]
        metrics["num_trades"] = len(trades)
        metrics["win_rate_pct"] = round((trade_returns > 0).mean() * 100, 2)
        metrics["avg_trade_return_pct"] = round(trade_returns.mean() * 100, 4)
        metrics["profit_factor"] = round(
            abs(trade_returns[trade_returns > 0].sum() / trade_returns[trade_returns < 0].sum()), 2
        ) if trade_returns[trade_returns < 0].sum() != 0 else np.inf
        metrics["avg_win_pct"] = round(trade_returns[trade_returns > 0].mean() * 100, 4) if (trade_returns > 0).any() else 0
        metrics["avg_loss_pct"] = round(trade_returns[trade_returns < 0].mean() * 100, 4) if (trade_returns < 0).any() else 0
        metrics["best_trade_pct"] = round(trade_returns.max() * 100, 4)
        metrics["worst_trade_pct"] = round(trade_returns.min() * 100, 4)
        metrics["expectancy_pct"] = round(
            (metrics["win_rate_pct"]/100 * metrics["avg_win_pct"] + 
             (1-metrics["win_rate_pct"]/100) * metrics["avg_loss_pct"]), 4
        )
    
    return metrics


def _max_drawdown_duration(drawdown: pd.Series) -> int:
    """Calculate maximum consecutive bars in drawdown."""
    in_dd = drawdown < 0
    if not in_dd.any():
        return 0
    
    # Find consecutive True values
    groups = (in_dd != in_dd.shift()).cumsum()
    durations = in_dd.groupby(groups).sum()
    return int(durations.max())


def print_metrics(metrics: Dict):
    """Pretty-print metrics."""
    print("=" * 60)
    print("BACKTEST PERFORMANCE METRICS")
    print("=" * 60)
    for key, val in metrics.items():
        if key == "num_bars" or key == "num_trades" or key == "max_dd_duration_bars":
            print(f"{key:30s}: {val:,}")
        else:
            print(f"{key:30s}: {val}")
    print("=" * 60)
