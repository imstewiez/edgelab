"""Portfolio backtest: XAUUSD + EURUSD + NAS100 with inv-vol weights.

Uses the proven vectorized backtester (same as Phase 6 research)
with per-asset cost calibration.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.metrics import calculate_metrics
from multitf_platform.strategy.frozen.v1_0_0.signals import MultiTFStrategy
from multitf_platform.strategy.frozen.v1_0_0.config import FrozenStrategyConfig


ASSETS = {
    "XAUUSD": {"spread_pips": 0.2, "commission": 7.0, "lot_size": 100.0, "trade_lots": 1.0, "pip_value": 1.0},
    "EURUSD": {"spread_pips": 0.2, "commission": 7.0, "lot_size": 100_000.0, "trade_lots": 0.01, "pip_value": 1.0},
    "NAS100": {"spread_pips": 2.0, "commission": 7.0, "lot_size": 1.0, "trade_lots": 0.01, "pip_value": 1.0},
}


def load_data(symbol):
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    h1 = pd.read_parquet(base / f"{symbol}_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    h4 = pd.read_parquet(base / f"{symbol}_H4.parquet")
    if "time" in h4.columns:
        h4.set_index("time", inplace=True)
    return h1, h4


def run_asset(symbol, h1, h4):
    """Run vectorized backtest for single asset with calibrated costs."""
    cfg = FrozenStrategyConfig()
    strat = MultiTFStrategy(cfg)
    signals = strat.generate_signals_series(h1, h4)
    
    asset_cfg = ASSETS[symbol]
    exec_cfg = ExecutionConfig(
        spread_pips=asset_cfg["spread_pips"],
        commission_per_lot=asset_cfg["commission"],
        lot_size=asset_cfg["lot_size"],
        trade_lots=asset_cfg["trade_lots"],
        slippage_pips=0.5,
        pip_value=asset_cfg["pip_value"],
    )
    
    class MockStrat:
        def __init__(self, sig): self.sig = sig
        def generate_signals(self, data): return self.sig.reindex(data.index).fillna(0)
    
    bt = VectorizedBacktester(h1, MockStrat(signals), execution_config=exec_cfg)
    bt.run()
    
    periods = 252 * 24
    m = calculate_metrics(bt.equity_curve, trades=bt.trades, periods_per_year=periods)
    
    return {
        "symbol": symbol,
        "equity_curve": bt.equity_curve,
        "trades": bt.trades,
        "sharpe": m.get("sharpe_ratio", 0),
        "ann_return": m.get("ann_return_pct", 0),
        "max_dd": m.get("max_drawdown_pct", 0),
        "num_trades": m.get("num_trades", 0),
        "win_rate": m.get("win_rate_pct", 0),
    }


def calculate_inv_vol_weights(returns_dict):
    """Calculate inverse-volatility weights from return series."""
    vols = {}
    for symbol, data in returns_dict.items():
        r = data["equity_curve"].pct_change().dropna()
        vols[symbol] = r.std()
    
    inv_vols = {s: 1.0/v if v > 0 else 0 for s, v in vols.items()}
    total = sum(inv_vols.values())
    return {s: v/total for s, v in inv_vols.items()}


def build_portfolio_equity(results, weights):
    """Build portfolio equity curve from weighted asset equity curves."""
    # Normalize each equity curve to start at 1.0
    normalized = {}
    for symbol, data in results.items():
        ec = data["equity_curve"]
        if len(ec) > 0 and ec.iloc[0] > 0:
            normalized[symbol] = ec / ec.iloc[0]
        else:
            normalized[symbol] = pd.Series(1.0, index=ec.index)
    
    # Align to common index
    common_idx = None
    for ec in normalized.values():
        if common_idx is None:
            common_idx = ec.index
        else:
            common_idx = common_idx.union(ec.index)
    
    # Combine weighted returns
    portfolio = pd.Series(0.0, index=common_idx)
    for symbol, w in weights.items():
        if symbol in normalized:
            ec = normalized[symbol].reindex(common_idx, method="ffill").fillna(1.0)
            portfolio += ec * w
    
    # Scale to $10,000 initial equity
    portfolio *= 10000.0
    return portfolio


def main():
    print("=" * 70)
    print("Portfolio Backtest: XAUUSD + EURUSD + NAS100")
    print("=" * 70)
    
    results = {}
    for symbol in ASSETS:
        print(f"\n--- {symbol} ---")
        h1, h4 = load_data(symbol)
        res = run_asset(symbol, h1, h4)
        results[symbol] = res
        print(f"  Sharpe: {res['sharpe']:+.3f} | Return: {res['ann_return']:+.1f}% | DD: {res['max_dd']:+.1f}% | Trades: {res['num_trades']}")
    
    # Calculate weights
    weights = calculate_inv_vol_weights(results)
    print(f"\n{'='*70}")
    print("INVERSE-VOLATILITY WEIGHTS")
    print(f"{'='*70}")
    for s, w in weights.items():
        print(f"  {s}: {w:.1%}")
    
    # Build portfolio
    portfolio_equity = build_portfolio_equity(results, weights)
    
    # Calculate portfolio metrics
    returns = portfolio_equity.pct_change().dropna()
    if len(returns) > 0 and returns.std() > 0:
        periods = 252 * 24
        ann_ret = returns.mean() * periods * 100
        ann_vol = returns.std() * np.sqrt(periods) * 100
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        peak = portfolio_equity.expanding().max()
        dd = (portfolio_equity - peak) / peak
        max_dd = dd.min() * 100
    else:
        ann_ret = ann_vol = sharpe = max_dd = 0
    
    print(f"\n{'='*70}")
    print("PORTFOLIO METRICS")
    print(f"{'='*70}")
    print(f"  Sharpe Ratio:   {sharpe:>+7.3f}")
    print(f"  Ann. Return:    {ann_ret:>+7.1f}%")
    print(f"  Max Drawdown:   {max_dd:>+7.1f}%")
    if max_dd != 0:
        print(f"  Calmar Ratio:   {abs(ann_ret / max_dd):>7.2f}")
    
    # Save
    out = Path(__file__).parent.parent.parent.parent / "results" / "portfolio"
    out.mkdir(parents=True, exist_ok=True)
    portfolio_equity.to_csv(out / "portfolio_equity_curve.csv")
    
    # Summary dict for return
    metrics = {
        "sharpe": sharpe,
        "ann_return": ann_ret,
        "max_dd": max_dd,
        "weights": weights,
    }
    
    print(f"\nSaved: {out / 'portfolio_equity_curve.csv'}")
    return results, portfolio_equity, weights, metrics


if __name__ == "__main__":
    main()
