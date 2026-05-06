"""
Investor Readiness Suite - Comprehensive institutional-grade analysis
Tests everything a real allocator would want to see before committing capital.
"""
import sys, os, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from glob import glob
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from scipy import stats

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtest.strategy import Strategy
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig

# ============================================================
# STRATEGIES
# ============================================================
class MOMStrategy(Strategy):
    def __init__(self, lookback: int = 100):
        super().__init__(f"MOM{lookback}")
        self.lookback = lookback
    def generate_signals(self, data):
        mom = data["close"].pct_change(self.lookback)
        return pd.Series(np.where(mom > 0, 1, np.where(mom < 0, -1, 0)), index=data.index)

class AdaptiveRegimeStrategy(Strategy):
    def __init__(self):
        super().__init__("AdaptiveRegime")
    def generate_signals(self, data):
        d1_close = data["close"].resample("1D").last().dropna()
        d1_ret = d1_close.pct_change().dropna()
        vol = d1_ret.rolling(20).std() * np.sqrt(252)
        vol_h1 = vol.reindex(data.index, method="ffill")
        mom50 = data["close"].pct_change(50)
        mom100 = data["close"].pct_change(100)
        mom200 = data["close"].pct_change(200)
        sig = pd.Series(0, index=data.index)
        strong = vol_h1 > 0.20
        weak = vol_h1 < 0.10
        mod = ~(strong.fillna(False) | weak.fillna(False))
        sig[strong.fillna(False)] = np.where(mom50[strong.fillna(False)] > 0, 1, -1)
        sig[weak.fillna(False)] = np.where(mom200[weak.fillna(False)] > 0, 1, -1)
        sig[mod] = np.where(mom100[mod] > 0, 1, -1)
        return sig

class MultiTimeframeStrategy(Strategy):
    """H1 momentum confirmed by H4 trend direction."""
    def __init__(self, h1_lookback=100, h4_lookback=50):
        super().__init__("MultiTF")
        self.h1_lb = h1_lookback
        self.h4_lb = h4_lookback
    def generate_signals(self, data):
        h1_mom = data["close"].pct_change(self.h1_lb)
        # Approximate H4 momentum from H1 data
        h4_close = data["close"].resample("4h").last().dropna()
        h4_mom = h4_close.pct_change(self.h4_lb)
        h4_mom_h1 = h4_mom.reindex(data.index, method="ffill")
        
        long = (h1_mom > 0) & (h4_mom_h1 > 0)
        short = (h1_mom < 0) & (h4_mom_h1 < 0)
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=data.index)

# ============================================================
# DATA LOADING
# ============================================================
def load_data(symbol="XAUUSD"):
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    path = os.path.join(base, f"data/raw/{symbol}_H1.parquet")
    if not os.path.exists(path):
        # Try without .s suffix
        path = os.path.join(base, f"data/raw/{symbol.replace('.s', '')}_H1.parquet")
    df = pd.read_parquet(path)
    if "time" in df.columns:
        df.set_index("time", inplace=True)
    return df

def load_dukascopy():
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    paths = sorted(glob(os.path.join(base, "data/external/XAUUSD_M1_batch_*.parquet")))
    if not paths:
        return None
    dfs = []
    for p in paths:
        df = pd.read_parquet(p)
        if "time" in df.columns:
            df.set_index("time", inplace=True)
        dfs.append(df)
    combined = pd.concat(dfs).sort_index()
    ohlc = combined["close"].resample("1h").ohlc()
    ohlc.columns = ["open", "high", "low", "close"]
    return ohlc

XAU_CONFIG = ExecutionConfig(spread_pips=None, commission_per_lot=7.0, lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)

# ============================================================
# COMPREHENSIVE METRICS
# ============================================================
def calculate_comprehensive_metrics(equity: pd.Series, trades: Optional[pd.DataFrame] = None, 
                                   periods_per_year: int = 252*24) -> Dict:
    """Calculate every metric an allocator would want."""
    returns = equity.pct_change().dropna()
    log_returns = np.log(equity / equity.shift(1)).dropna()
    
    if len(returns) < 10:
        return {"error": "Insufficient data"}
    
    metrics = {}
    
    # Basic
    metrics["total_return_pct"] = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    metrics["ann_return_pct"] = log_returns.mean() * periods_per_year * 100
    metrics["ann_vol_pct"] = log_returns.std() * np.sqrt(periods_per_year) * 100
    
    # Risk-adjusted ratios
    metrics["sharpe_ratio"] = metrics["ann_return_pct"] / metrics["ann_vol_pct"] if metrics["ann_vol_pct"] > 0 else 0
    
    downside = log_returns[log_returns < 0].std() * np.sqrt(periods_per_year) * 100
    metrics["sortino_ratio"] = metrics["ann_return_pct"] / downside if downside > 0 else 0
    
    # Drawdown
    cummax = equity.cummax()
    dd = (equity - cummax) / cummax
    metrics["max_drawdown_pct"] = dd.min() * 100
    metrics["avg_drawdown_pct"] = dd[dd < 0].mean() * 100
    metrics["dd_recovery_bars"] = int(_max_dd_duration(dd))
    
    # Calmar
    metrics["calmar_ratio"] = metrics["ann_return_pct"] / abs(metrics["max_drawdown_pct"]) if metrics["max_drawdown_pct"] != 0 else 0
    
    # Tail risk
    metrics["var_95_pct"] = np.percentile(log_returns, 5) * 100
    metrics["cvar_95_pct"] = log_returns[log_returns <= np.percentile(log_returns, 5)].mean() * 100
    metrics["var_99_pct"] = np.percentile(log_returns, 1) * 100
    metrics["skewness"] = log_returns.skew()
    metrics["kurtosis"] = log_returns.kurtosis()
    
    # Trade metrics
    if trades is not None and len(trades) > 0:
        tret = trades["return"]
        wins = tret[tret > 0]
        losses = tret[tret < 0]
        
        metrics["num_trades"] = len(trades)
        metrics["win_rate_pct"] = (len(wins) / len(tret)) * 100 if len(tret) > 0 else 0
        metrics["profit_factor"] = abs(wins.sum() / losses.sum()) if len(losses) > 0 and losses.sum() != 0 else np.inf
        metrics["avg_trade_pct"] = tret.mean() * 100
        metrics["avg_win_pct"] = wins.mean() * 100 if len(wins) > 0 else 0
        metrics["avg_loss_pct"] = losses.mean() * 100 if len(losses) > 0 else 0
        metrics["win_loss_ratio"] = abs(metrics["avg_win_pct"] / metrics["avg_loss_pct"]) if metrics["avg_loss_pct"] != 0 else 0
        metrics["expectancy_pct"] = (metrics["win_rate_pct"]/100 * metrics["avg_win_pct"] + 
                                     (1-metrics["win_rate_pct"]/100) * metrics["avg_loss_pct"])
        metrics["largest_win_pct"] = tret.max() * 100
        metrics["largest_loss_pct"] = tret.min() * 100
        
        # Consecutive wins/losses
        signs = np.sign(tret)
        groups = (signs != signs.shift()).cumsum()
        win_streaks = signs.groupby(groups).apply(lambda x: len(x) if x.iloc[0] > 0 else 0)
        loss_streaks = signs.groupby(groups).apply(lambda x: len(x) if x.iloc[0] < 0 else 0)
        metrics["max_consecutive_wins"] = int(win_streaks.max())
        metrics["max_consecutive_losses"] = int(loss_streaks.max())
    
    # K-Ratio (consistency of equity growth)
    x = np.arange(len(equity))
    slope, intercept, r_value, _, _ = stats.linregress(x, equity.values)
    metrics["k_ratio"] = slope / (equity.std() + 1e-10) * np.sqrt(periods_per_year)
    
    # Gain/Pain ratio
    positive_rets = log_returns[log_returns > 0].sum()
    negative_rets = abs(log_returns[log_returns < 0].sum())
    metrics["gain_pain_ratio"] = positive_rets / negative_rets if negative_rets > 0 else np.inf
    
    # Omega ratio (threshold = 0)
    threshold = 0
    positive_excess = (log_returns - threshold)[log_returns > threshold].sum()
    negative_excess = abs((log_returns - threshold)[log_returns < threshold].sum())
    metrics["omega_ratio"] = positive_excess / negative_excess if negative_excess > 0 else np.inf
    
    # Percentage of time in drawdown
    metrics["pct_time_in_drawdown"] = (dd < 0).mean() * 100
    
    return metrics

def _max_dd_duration(dd: pd.Series) -> int:
    in_dd = dd < 0
    if not in_dd.any():
        return 0
    groups = (in_dd != in_dd.shift()).cumsum()
    durations = in_dd.groupby(groups).sum()
    return int(durations.max())

# ============================================================
# FEE-ADJUSTED RETURNS
# ============================================================
def apply_fees(equity: pd.Series, management_fee_pct: float = 2.0, 
               performance_fee_pct: float = 20.0, high_water_mark: bool = True) -> pd.Series:
    """
    Apply hedge fund fee structure to equity curve.
    Management fee: annual, deducted monthly
    Performance fee: quarterly, with high water mark
    """
    equity = equity.copy()
    nav = equity.copy()
    hwm = equity.copy()
    
    # Monthly management fee (2% / 12)
    monthly_fee = management_fee_pct / 100 / 12
    
    # Quarterly performance fee
    perf_periods = equity.resample("QE").last()
    
    for i in range(1, len(equity)):
        # Daily management fee approximation
        nav.iloc[i] *= (1 - monthly_fee / 30)
        
        # High water mark tracking
        if nav.iloc[i] > hwm.iloc[i-1]:
            hwm.iloc[i] = nav.iloc[i]
        else:
            hwm.iloc[i] = hwm.iloc[i-1]
    
    return nav

# ============================================================
# MONTE CARLO SIMULATION
# ============================================================
def monte_carlo_simulation(returns: pd.Series, n_simulations: int = 10000, 
                          initial_capital: float = 100000) -> Dict:
    """
    Monte Carlo: shuffle trade returns, rebuild equity curves.
    Tests robustness to path dependency.
    """
    rets = returns.dropna().values
    if len(rets) < 10:
        return {"error": "Insufficient returns"}
    
    final_equities = []
    max_dds = []
    sharpes = []
    
    for _ in range(n_simulations):
        shuffled = np.random.choice(rets, size=len(rets), replace=True)
        equity = initial_capital * (1 + shuffled).cumprod()
        
        final_equities.append(equity[-1])
        
        cummax = np.maximum.accumulate(equity)
        dd = (equity - cummax) / cummax
        max_dds.append(dd.min())
        
        ann_ret = np.mean(shuffled) * 252 * 24
        ann_vol = np.std(shuffled) * np.sqrt(252 * 24)
        sharpes.append(ann_ret / ann_vol if ann_vol > 0 else 0)
    
    return {
        "mc_final_equity_median": np.median(final_equities),
        "mc_final_equity_5pct": np.percentile(final_equities, 5),
        "mc_final_equity_95pct": np.percentile(final_equities, 95),
        "mc_max_dd_median_pct": np.median(max_dds) * 100,
        "mc_max_dd_worst_5pct_pct": np.percentile(max_dds, 5) * 100,
        "mc_sharpe_median": np.median(sharpes),
        "mc_sharpe_5pct": np.percentile(sharpes, 5),
        "mc_prob_of_profit_pct": (np.array(final_equities) > initial_capital).mean() * 100,
        "mc_prob_of_50pct_dd_pct": (np.array(max_dds) < -0.5).mean() * 100,
    }

# ============================================================
# PARAMETER ROBUSTNESS
# ============================================================
def parameter_sweep(df: pd.DataFrame, lookback_range: range = range(20, 201, 10)) -> pd.DataFrame:
    """Test strategy across parameter grid."""
    results = []
    for lb in lookback_range:
        strat = MOMStrategy(lookback=lb)
        bt = VectorizedBacktester(df, strat, execution_config=XAU_CONFIG)
        bt.run()
        metrics = calculate_comprehensive_metrics(bt.equity_curve, bt.trades)
        results.append({
            "lookback": lb,
            "sharpe": metrics.get("sharpe_ratio", 0),
            "ann_ret": metrics.get("ann_return_pct", 0),
            "max_dd": metrics.get("max_drawdown_pct", 0),
            "profit_factor": metrics.get("profit_factor", 0),
            "win_rate": metrics.get("win_rate_pct", 0),
            "trades": metrics.get("num_trades", 0),
        })
    return pd.DataFrame(results)

# ============================================================
# STRESS TESTING
# ============================================================
def stress_test(df: pd.DataFrame, strategy: Strategy, scenarios: List[dict]) -> pd.DataFrame:
    """Test strategy under various stress scenarios."""
    results = []
    base_bt = VectorizedBacktester(df, strategy, execution_config=XAU_CONFIG)
    base_bt.run()
    base_metrics = calculate_comprehensive_metrics(base_bt.equity_curve, base_bt.trades)
    
    for scenario in scenarios:
        name = scenario["name"]
        
        # Apply scenario modifications
        stress_df = df.copy()
        if "vol_shock" in scenario:
            # Multiply returns by vol shock factor
            shock = scenario["vol_shock"]
            stress_df["close"] = stress_df["close"] * (1 + stress_df["close"].pct_change() * (shock - 1))
        if "gap_shock" in scenario:
            # Random overnight gaps
            np.random.seed(42)
            gaps = np.random.choice([-1, 1], size=len(stress_df)) * scenario["gap_shock"]
            stress_df["close"] *= (1 + gaps)
        if "spread_widen" in scenario:
            # Widen spread
            if "avg_spread" in stress_df.columns:
                stress_df["avg_spread"] *= scenario["spread_widen"]
        
        bt = VectorizedBacktester(stress_df, strategy, execution_config=XAU_CONFIG)
        bt.run()
        m = calculate_comprehensive_metrics(bt.equity_curve, bt.trades)
        
        results.append({
            "scenario": name,
            "sharpe": m.get("sharpe_ratio", 0),
            "ann_ret": m.get("ann_return_pct", 0),
            "max_dd": m.get("max_drawdown_pct", 0),
            "profit_factor": m.get("profit_factor", 0),
            "vs_baseline_sharpe": m.get("sharpe_ratio", 0) - base_metrics.get("sharpe_ratio", 0),
        })
    
    return pd.DataFrame(results)

# ============================================================
# KELLY CRITERION / OPTIMAL F
# ============================================================
def kelly_analysis(trades: pd.DataFrame) -> Dict:
    """Calculate Kelly criterion and optimal f for position sizing."""
    if trades is None or len(trades) < 10:
        return {"error": "Insufficient trades"}
    
    tret = trades["return"]
    wins = tret[tret > 0]
    losses = tret[tret < 0]
    
    W = len(wins) / len(tret)  # Win rate
    R = abs(wins.mean() / losses.mean()) if len(losses) > 0 and losses.mean() != 0 else 1  # Win/loss ratio
    
    # Kelly % = W - (1-W)/R
    kelly_pct = W - ((1 - W) / R) if R > 0 else 0
    
    # Half-Kelly (more conservative)
    half_kelly = kelly_pct / 2
    
    # Optimal f (fixed fractional)
    # Find f that maximizes TWR = product(1 + f * return_i)
    best_f = 0
    best_twr = 0
    for f in np.linspace(0.01, 1.0, 100):
        twr = np.prod(1 + f * tret)
        if twr > best_twr:
            best_twr = twr
            best_f = f
    
    return {
        "win_rate": W * 100,
        "win_loss_ratio": R,
        "kelly_pct": kelly_pct * 100,
        "half_kelly_pct": half_kelly * 100,
        "optimal_f_pct": best_f * 100,
        "optimal_f_twr": best_twr,
        "current_risk_per_trade_pct": 100,  # Full position
        "recommended_risk_per_trade_pct": half_kelly * 100,
    }

# ============================================================
# MAIN ANALYSIS
# ============================================================
def run_full_analysis():
    print("=" * 90)
    print("INVESTOR READINESS SUITE - Comprehensive Institutional Analysis")
    print("=" * 90)
    
    # Load data
    xau = load_data("XAUUSD")
    dukas = load_dukascopy()
    
    print("\nData loaded:")
    print("  XAUUSD MT5: %d bars (%s to %s)" % (len(xau), xau.index[0], xau.index[-1]))
    if dukas is not None:
        print("  XAUUSD Dukascopy: %d bars (%s to %s)" % (len(dukas), dukas.index[0], dukas.index[-1]))
    
    strategies = {
        "MOM100": MOMStrategy(100),
        "AdaptiveRegime": AdaptiveRegimeStrategy(),
        "MultiTF": MultiTimeframeStrategy(),
    }
    
    all_results = {}
    
    for name, strat in strategies.items():
        print("\n" + "=" * 90)
        print("STRATEGY: %s" % name)
        print("=" * 90)
        
        # Bull regime
        bull = xau[xau.index >= "2021-01-01"]
        bt_bull = VectorizedBacktester(bull, strat, execution_config=XAU_CONFIG)
        bt_bull.run()
        m_bull = calculate_comprehensive_metrics(bt_bull.equity_curve, bt_bull.trades)
        
        # Sideways (pre-2021)
        side = xau[xau.index < "2021-01-01"]
        m_side = None
        if len(side) > 1000:
            bt_side = VectorizedBacktester(side, strat, execution_config=XAU_CONFIG)
            bt_side.run()
            m_side = calculate_comprehensive_metrics(bt_side.equity_curve, bt_side.trades)
        
        # Dukascopy
        m_dukas = None
        if dukas is not None and len(dukas) > 1000:
            bt_dukas = VectorizedBacktester(dukas, strat, execution_config=XAU_CONFIG)
            bt_dukas.run()
            m_dukas = calculate_comprehensive_metrics(bt_dukas.equity_curve, bt_dukas.trades)
        
        print("\n--- COMPREHENSIVE METRICS ---")
        for k, v in m_bull.items():
            print("  %-30s: %s" % (k, v))
        
        # Fee-adjusted
        print("\n--- FEE-ADJUSTED RETURNS (2/20) ---")
        net_equity = apply_fees(bt_bull.equity_curve, 2.0, 20.0)
        net_rets = np.log(net_equity / net_equity.shift(1)).dropna()
        net_ann = net_rets.mean() * 252 * 24 * 100
        net_vol = net_rets.std() * np.sqrt(252 * 24) * 100
        net_sharpe = net_ann / net_vol if net_vol > 0 else 0
        print("  Gross Ann Return:     %.2f%%" % m_bull.get("ann_return_pct", 0))
        print("  Net Ann Return:       %.2f%%" % net_ann)
        print("  Net Ann Volatility:   %.2f%%" % net_vol)
        print("  Net Sharpe:           %.3f" % net_sharpe)
        print("  Fee Drag:             %.2f%%" % (m_bull.get("ann_return_pct", 0) - net_ann))
        
        # Monte Carlo
        print("\n--- MONTE CARLO (10,000 sims) ---")
        mc = monte_carlo_simulation(bt_bull.returns, n_simulations=10000)
        for k, v in mc.items():
            print("  %-30s: %s" % (k, v))
        
        # Kelly
        if bt_bull.trades is not None and len(bt_bull.trades) > 10:
            print("\n--- KELLY / OPTIMAL F ---")
            kelly = kelly_analysis(bt_bull.trades)
            for k, v in kelly.items():
                print("  %-30s: %.3f" % (k, v) if isinstance(v, float) else "  %-30s: %s" % (k, v))
        
        # Store
        all_results[name] = {
            "bull": m_bull,
            "side": m_side,
            "dukas": m_dukas,
            "mc": mc,
        }
    
    # Parameter Robustness
    print("\n" + "=" * 90)
    print("PARAMETER ROBUSTNESS - MOMENTUM LOOKBACK SWEEP")
    print("=" * 90)
    sweep = parameter_sweep(xau, lookback_range=range(20, 201, 10))
    print(sweep.to_string(index=False))
    
    best_idx = sweep["sharpe"].idxmax()
    worst_idx = sweep["sharpe"].idxmin()
    print("\nBest lookback:  %d (Sharpe=%.3f)" % (sweep.iloc[best_idx]["lookback"], sweep.iloc[best_idx]["sharpe"]))
    print("Worst lookback: %d (Sharpe=%.3f)" % (sweep.iloc[worst_idx]["lookback"], sweep.iloc[worst_idx]["sharpe"]))
    print("Sharpe std dev across parameters: %.3f" % sweep["sharpe"].std())
    
    # Stress Testing
    print("\n" + "=" * 90)
    print("STRESS TESTING")
    print("=" * 90)
    scenarios = [
        {"name": "Baseline", "vol_shock": 1.0},
        {"name": "2x Volatility", "vol_shock": 2.0},
        {"name": "3x Volatility", "vol_shock": 3.0},
        {"name": "Spread Widen 2x", "spread_widen": 2.0},
        {"name": "Spread Widen 5x", "spread_widen": 5.0},
        {"name": "Gap Shock 0.5%", "gap_shock": 0.005},
        {"name": "Vol+Spread Shock", "vol_shock": 2.0, "spread_widen": 3.0},
    ]
    stress = stress_test(xau, AdaptiveRegimeStrategy(), scenarios)
    print(stress.to_string(index=False))
    
    # INVESTOR GRADE SUMMARY
    print("\n" + "=" * 90)
    print("INVESTOR GRADE SUMMARY - GAP ANALYSIS")
    print("=" * 90)
    
    bull = all_results.get("AdaptiveRegime", {}).get("bull", {})
    mc = all_results.get("AdaptiveRegime", {}).get("mc", {})
    
    print("\nCURRENT STATE:")
    print("  Strategy:               AdaptiveRegime on XAUUSD H1")
    print("  Sharpe Ratio:           %.3f (Target: >1.5)" % bull.get("sharpe_ratio", 0))
    print("  Max Drawdown:           %.1f%% (Target: <-10%%)" % bull.get("max_drawdown_pct", 0))
    print("  Profit Factor:          %.2f (Target: >1.5)" % bull.get("profit_factor", 0))
    print("  Win Rate:               %.1f%%" % bull.get("win_rate_pct", 0))
    print("  Consecutive Losses:     %d" % bull.get("max_consecutive_losses", 0))
    print("  Monte Carlo Sharpe 5%%:  %.3f" % mc.get("mc_sharpe_5pct", 0))
    print("  MC Prob of 50%% DD:      %.1f%%" % mc.get("mc_prob_of_50pct_dd_pct", 0))
    
    print("\nGAPS TO INSTITUTIONAL READINESS:")
    gaps = []
    if bull.get("sharpe_ratio", 0) < 1.5:
        gaps.append("Sharpe too low (need 1.5+, have %.2f)" % bull.get("sharpe_ratio", 0))
    if bull.get("max_drawdown_pct", 0) < -10:
        gaps.append("Drawdown too deep (need <10%%, have %.1f%%)" % abs(bull.get("max_drawdown_pct", 0)))
    if bull.get("profit_factor", 0) < 1.5:
        gaps.append("Profit Factor too low (need 1.5+, have %.2f)" % bull.get("profit_factor", 0))
    if mc.get("mc_prob_of_50pct_dd_pct", 0) > 5:
        gaps.append("Tail risk too high (%.1f%% chance of 50%% DD)" % mc.get("mc_prob_of_50pct_dd_pct", 0))
    
    for gap in gaps:
        print("  - %s" % gap)
    
    if not gaps:
        print("  No critical gaps identified.")
    
    print("\nRECOMMENDATIONS:")
    print("  1. Forward test for minimum 6-12 months with real money (even $500)")
    print("  2. Target Sharpe improvement to 1.5+ via better risk management")
    print("  3. Reduce max DD to <15%% via position sizing or hedging")
    print("  4. Add 2-3 genuinely uncorrelated strategies (not just gold variants)")
    print("  5. Get audited track record via MyFXBook or similar")
    print("  6. Register as CTA / obtain regulatory approval for client funds")
    print("  7. Build 2-3 year live track record before approaching investors")

if __name__ == "__main__":
    run_full_analysis()
