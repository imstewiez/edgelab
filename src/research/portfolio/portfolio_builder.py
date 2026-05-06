"""Phase 6: Portfolio Construction & Hedging

Tests whether combining multiple assets improves risk-adjusted returns.
Assets validated in Phase 2.1:
- XAUUSD (Sharpe 1.895, DD -13.8%)
- NAS100 (Sharpe 1.334, DD -17.8%)
- XAUEUR (Sharpe 1.202, DD -19.2%)
- EURUSD (Sharpe 1.105, DD -5.1%)
- XAGUSD (Sharpe 0.692, DD -38.1%)

Tests:
1. Equal-weight portfolio
2. Inverse-volatility weighting
3. Correlation-based hedging (long one, short another)
4. Best-pair combination

Key question: Does diversification improve the Sharpe ratio?
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


ASSETS = ["XAUUSD", "EURUSD", "NAS100"]  # Only assets with full H1+H4 data


def load_data(asset):
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    h1 = pd.read_parquet(base / f"{asset}_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    h4 = pd.read_parquet(base / f"{asset}_H4.parquet")
    if "time" in h4.columns:
        h4.set_index("time", inplace=True)
    return h1, h4


def run_single(asset, h1, h4):
    """Run backtest for single asset."""
    cfg = FrozenStrategyConfig()
    strat = MultiTFStrategy(cfg)
    signals = strat.generate_signals_series(h1, h4)
    
    class MockStrat:
        def __init__(self, sig): self.sig = sig
        def generate_signals(self, data): return self.sig.reindex(data.index).fillna(0)
    
    # Asset-calibrated costs (from Phase 2.1 validator)
    if asset in ("XAUUSD", "XAGUSD", "XAUEUR"):
        # Metals: 0.01 lot = 1 oz, 1 point = $0.01
        exec_cfg = ExecutionConfig(
            spread_pips=0.2, commission_per_lot=7.0,
            lot_size=100.0, trade_lots=0.01,
            slippage_pips=0.5, pip_value=1.0,
        )
    elif asset in ("EURUSD", "GBPUSD", "AUDUSD"):
        # FX: 0.01 lot = 1,000 units, 1 pip = $0.10
        exec_cfg = ExecutionConfig(
            spread_pips=0.2, commission_per_lot=7.0,
            lot_size=100_000.0, trade_lots=0.01,
            slippage_pips=0.5, pip_value=1.0,
        )
    elif asset in ("NAS100", "GER40", "US30"):
        # Indices: 0.01 lot = 0.01 index unit, 1 point = $0.01
        exec_cfg = ExecutionConfig(
            spread_pips=2.0, commission_per_lot=7.0,
            lot_size=1.0, trade_lots=0.01,
            slippage_pips=0.5, pip_value=1.0,
        )
    else:
        exec_cfg = ExecutionConfig(
            spread_pips=0.2, commission_per_lot=7.0,
            lot_size=100.0, trade_lots=0.01,
            slippage_pips=0.5, pip_value=1.0,
        )
    
    bt = VectorizedBacktester(h1, MockStrat(signals), execution_config=exec_cfg)
    bt.run()
    
    # Extract returns (daily P&L as fraction of initial equity)
    equity = bt.equity_curve
    returns = equity.pct_change().dropna()
    
    return {
        "asset": asset,
        "equity": equity,
        "returns": returns,
        "sharpe": None,  # calculated later
        "trades": len(bt.trades),
    }


def build_portfolio(returns_dict, weights):
    """Build portfolio returns from weighted combination."""
    # Align all returns to common index
    common_idx = None
    for asset, data in returns_dict.items():
        if asset in weights:
            if common_idx is None:
                common_idx = data["returns"].index
            else:
                common_idx = common_idx.union(data["returns"].index)
    
    # Reindex and combine
    portfolio_returns = pd.Series(0.0, index=common_idx)
    for asset, w in weights.items():
        if asset in returns_dict:
            r = returns_dict[asset]["returns"].reindex(common_idx, fill_value=0)
            portfolio_returns += r * w
    
    # Build equity curve
    equity = (1 + portfolio_returns).cumprod() * 10300.0
    
    return equity, portfolio_returns


def calculate_portfolio_metrics(equity, returns, periods_per_year=252*24):
    """Calculate metrics for portfolio."""
    # Approximate metrics from equity curve
    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
    ann_return = total_return * periods_per_year / len(equity)
    
    # Drawdown
    peak = equity.cummax()
    dd = (equity / peak - 1)
    max_dd = dd.min() * 100
    
    # Sharpe
    if returns.std() > 0:
        sharpe = returns.mean() / returns.std() * np.sqrt(periods_per_year)
    else:
        sharpe = 0
    
    return {
        "sharpe": sharpe,
        "ann_return": ann_return * 100,
        "max_dd": max_dd,
    }


def main():
    print("=" * 70)
    print("Phase 6: Portfolio Construction & Hedging")
    print("=" * 70)
    
    # Load all assets
    results = {}
    for asset in ASSETS:
        try:
            h1, h4 = load_data(asset)
            print(f"Loaded {asset}: H1={len(h1)}, H4={len(h4)}")
            results[asset] = run_single(asset, h1, h4)
        except Exception as e:
            print(f"Failed to load {asset}: {e}")
    
    # Calculate individual metrics
    print("\n" + "=" * 70)
    print("INDIVIDUAL ASSET PERFORMANCE")
    print("=" * 70)
    individual = {}
    for asset, data in results.items():
        m = calculate_portfolio_metrics(data["equity"], data["returns"])
        data.update(m)
        individual[asset] = m
        print(f"  {asset:8s} | Sharpe {m['sharpe']:>+7.3f} | Return {m['ann_return']:>+7.1f}% | DD {m['max_dd']:>7.1f}% | Trades {data['trades']:>4d}")
    
    # Portfolio combinations
    print("\n" + "=" * 70)
    print("PORTFOLIO COMBINATIONS")
    print("=" * 70)
    
    portfolios = []
    
    # 1. Equal-weight all
    n = len(results)
    eq_weights = {a: 1.0/n for a in results}
    eq_equity, eq_returns = build_portfolio(results, eq_weights)
    eq_m = calculate_portfolio_metrics(eq_equity, eq_returns)
    eq_m["name"] = "Equal-weight (all)"
    eq_m["weights"] = eq_weights
    portfolios.append(eq_m)
    print(f"  Equal-weight (all)   | Sharpe {eq_m['sharpe']:>+7.3f} | Return {eq_m['ann_return']:>+7.1f}% | DD {eq_m['max_dd']:>7.1f}%")
    
    # 2. Equal-weight top 3 (by Sharpe)
    top3 = sorted(results.items(), key=lambda x: x[1]["sharpe"], reverse=True)[:3]
    top3_assets = [a for a, _ in top3]
    top3_weights = {a: 1.0/3 for a in top3_assets}
    top3_equity, top3_returns = build_portfolio(results, top3_weights)
    top3_m = calculate_portfolio_metrics(top3_equity, top3_returns)
    top3_m["name"] = "Equal-weight top3"
    top3_m["weights"] = top3_weights
    portfolios.append(top3_m)
    print(f"  Equal-weight top3    | Sharpe {top3_m['sharpe']:>+7.3f} | Return {top3_m['ann_return']:>+7.1f}% | DD {top3_m['max_dd']:>7.1f}%")
    
    # 3. Inverse-volatility weighting (all)
    # Use return std as volatility proxy
    vols = {a: data["returns"].std() for a, data in results.items()}
    inv_vol = {a: 1.0/v if v > 0 else 0 for a, v in vols.items()}
    total_inv = sum(inv_vol.values())
    iv_weights = {a: v/total_inv for a, v in inv_vol.items()}
    iv_equity, iv_returns = build_portfolio(results, iv_weights)
    iv_m = calculate_portfolio_metrics(iv_equity, iv_returns)
    iv_m["name"] = "Inv-vol (all)"
    iv_m["weights"] = iv_weights
    portfolios.append(iv_m)
    print(f"  Inv-vol (all)        | Sharpe {iv_m['sharpe']:>+7.3f} | Return {iv_m['ann_return']:>+7.1f}% | DD {iv_m['max_dd']:>7.1f}%")
    
    # 4. Best single asset
    best_asset = max(results.items(), key=lambda x: x[1]["sharpe"])
    best_m = {
        "name": f"Best single ({best_asset[0]})",
        "sharpe": best_asset[1]["sharpe"],
        "ann_return": best_asset[1]["ann_return"],
        "max_dd": best_asset[1]["max_dd"],
    }
    portfolios.append(best_m)
    print(f"  Best single ({best_asset[0]:8s}) | Sharpe {best_m['sharpe']:>+7.3f} | Return {best_m['ann_return']:>+7.1f}% | DD {best_m['max_dd']:>7.1f}%")
    
    # 5. Pair: XAUUSD + EURUSD (lowest correlation?)
    pair_weights = {"XAUUSD": 0.5, "EURUSD": 0.5}
    pair_equity, pair_returns = build_portfolio(results, pair_weights)
    pair_m = calculate_portfolio_metrics(pair_equity, pair_returns)
    pair_m["name"] = "Pair XAUUSD+EURUSD"
    pair_m["weights"] = pair_weights
    portfolios.append(pair_m)
    print(f"  Pair XAUUSD+EURUSD   | Sharpe {pair_m['sharpe']:>+7.3f} | Return {pair_m['ann_return']:>+7.1f}% | DD {pair_m['max_dd']:>7.1f}%")
    
    # Correlation matrix
    print("\n" + "=" * 70)
    print("RETURN CORRELATION MATRIX")
    print("=" * 70)
    returns_df = pd.DataFrame({a: d["returns"] for a, d in results.items()})
    corr = returns_df.corr()
    print(corr.round(3).to_string())
    
    # Save
    out = Path(__file__).parent.parent.parent.parent / "results" / "portfolio"
    out.mkdir(parents=True, exist_ok=True)
    
    df = pd.DataFrame(portfolios)
    df.to_csv(out / "portfolio_results.csv", index=False)
    corr.to_csv(out / "correlation_matrix.csv")
    
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    best = max(portfolios, key=lambda x: x["sharpe"])
    print(f"Best portfolio: {best['name']} | Sharpe {best['sharpe']:.3f}")
    
    for p in sorted(portfolios, key=lambda x: x["sharpe"], reverse=True):
        print(f"  {p['name']:25s} | Sharpe {p['sharpe']:>+7.3f} | Return {p['ann_return']:>+7.1f}% | DD {p['max_dd']:>7.1f}%")
    
    print(f"\nSaved: {out / 'portfolio_results.csv'}")


if __name__ == "__main__":
    main()
