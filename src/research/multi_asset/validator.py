"""Phase 2.1: Multi-Asset Momentum Validation

Tests MultiTF v1.0.0 framework on all available assets to identify
which instruments have positive momentum edges.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np

from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.metrics import calculate_metrics


ASSETS = {
    "XAUUSD":   {"full": True,  "h4_available": True},
    "EURUSD":   {"full": True,  "h4_available": True},
    "NAS100":   {"full": True,  "h4_available": True},
    "XAGUSD_s": {"full": False, "h4_available": False},
    "XAUEUR_s": {"full": False, "h4_available": False},
    "GER40_s":  {"full": False, "h4_available": False},
    "US30_s":   {"full": False, "h4_available": False},
}


def load_asset(symbol):
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    h1_path = base / f"{symbol}_H1.parquet"
    if not h1_path.exists():
        return None, None
    h1 = pd.read_parquet(h1_path)
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    h4_path = base / f"{symbol}_H4.parquet"
    if h4_path.exists():
        h4 = pd.read_parquet(h4_path)
        if "time" in h4.columns:
            h4.set_index("time", inplace=True)
        return h1, h4
    h4 = h1.resample("4h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "spread": "mean", "tick_volume": "sum",
    }).dropna()
    return h1, h4


def run_backtest(h1, h4, symbol, use_multitf=True):
    try:
        if use_multitf and h4 is not None and len(h4) > 100:
            strategy = MultiTFStrategy(FrozenStrategyConfig())
            signals = strategy.generate_signals_series(h1, h4)
        else:
            mom = h1["close"] / h1["close"].shift(100) - 1
            signals = pd.Series(np.where(mom > 0, 1, np.where(mom < 0, -1, 0)), index=h1.index)
        
        exec_cfg = ExecutionConfig()  # auto-detect per asset
        class Mock:
            def __init__(self, sig): self.sig = sig
            def generate_signals(self, data): return self.sig.reindex(data.index).fillna(0)
        
        bt = VectorizedBacktester(h1, Mock(signals), execution_config=exec_cfg)
        bt.run()
        
        metrics = calculate_metrics(bt.equity_curve, trades=bt.trades, periods_per_year=252*24)
        return {
            "symbol": symbol, "bars": len(h1),
            "sharpe": metrics.get("sharpe_ratio", 0),
            "ann_return": metrics.get("ann_return_pct", 0),
            "max_dd": metrics.get("max_drawdown_pct", 0),
            "trades": metrics.get("num_trades", 0),
            "win_rate": metrics.get("win_rate_pct", 0),
            "profit_factor": metrics.get("profit_factor", 0),
            "avg_trade": metrics.get("avg_trade_return_pct", 0),
            "status": "MultiTF" if use_multitf else "H1-MOM100",
        }
    except Exception as e:
        return {"symbol": symbol, "bars": len(h1) if h1 is not None else 0,
                "sharpe": 0, "ann_return": 0, "max_dd": 0, "trades": 0,
                "win_rate": 0, "profit_factor": 0, "avg_trade": 0,
                "status": f"ERROR: {e}"}


def main():
    print("=" * 80)
    print("Phase 2.1: Multi-Asset Momentum Validation")
    print("=" * 80)
    
    results = []
    for symbol, info in ASSETS.items():
        print(f"\n--- {symbol} ---")
        h1, h4 = load_asset(symbol)
        if h1 is None:
            print("  Data not found")
            results.append({"symbol": symbol, "bars": 0, "sharpe": 0,
                           "ann_return": 0, "max_dd": 0, "trades": 0,
                           "win_rate": 0, "profit_factor": 0, "avg_trade": 0,
                           "status": "NO DATA"})
            continue
        
        print(f"  H1: {len(h1)} bars")
        if h4 is not None: print(f"  H4: {len(h4)} bars")
        
        use_mt = info["h4_available"] and h4 is not None and len(h4) > 100
        res = run_backtest(h1, h4, symbol, use_multitf=use_mt)
        print(f"  Sharpe: {res['sharpe']:.3f} | Return: {res['ann_return']:.1f}% | DD: {res['max_dd']:.1f}% | Trades: {res['trades']}")
        results.append(res)
    
    df = pd.DataFrame(results)
    df = df.sort_values("sharpe", ascending=False)
    
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"{'Symbol':>10s} | {'Bars':>6s} | {'Sharpe':>7s} | {'AnnRet':>7s} | {'MaxDD':>7s} | {'Trades':>6s} | {'Win%':>6s} | {'PF':>5s} | {'Status':>12s}")
    print("-" * 80)
    for _, r in df.iterrows():
        print(f"{r['symbol']:>10s} | {r['bars']:>6d} | {r['sharpe']:>7.3f} | {r['ann_return']:>+7.1f} | {r['max_dd']:>+7.1f} | {r['trades']:>6d} | {r['win_rate']:>6.1f} | {r['profit_factor']:>5.2f} | {r['status']:>12s}")
    
    out = Path(__file__).parent.parent.parent.parent / "results" / "multi_asset"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "multi_asset_validation.csv", index=False)
    print(f"\nSaved: {out / 'multi_asset_validation.csv'}")
    
    viable = df[df["sharpe"] > 0.5]
    print(f"\nViable (Sharpe > 0.5): {len(viable)} assets")
    if len(viable) > 0:
        for _, r in viable.iterrows():
            print(f"  {r['symbol']:10s} | Sharpe {r['sharpe']:.3f} | Return {r['ann_return']:+.1f}%")


if __name__ == "__main__":
    main()
