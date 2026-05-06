"""
STRATEGY BREAKER SUITE v1.0.0
Frozen MultiTF. No signal changes allowed.
Objective: Find every condition under which MultiTF fails.
"""
import sys, os, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from glob import glob
from scipy import stats
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtest.strategy import Strategy
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig, ExecutionSimulator

# ============================================================
# FROZEN MULTITF v1.0.0 - DO NOT MODIFY
# ============================================================
class MultiTF_v1(Strategy):
    """
    FROZEN v1.0.0 - Multi-Timeframe Momentum
    H1 momentum (100-bar) confirmed by H4 momentum (50-bar).
    Long only when both timeframes agree on positive momentum.
    Short only when both timeframes agree on negative momentum.
    NO CHANGES ALLOWED to signal logic, parameters, or filters.
    """
    VERSION = "1.0.0"
    STATUS = "FROZEN"
    
    def __init__(self):
        super().__init__("MultiTF_v1.0.0")
        self.h1_lookback = 100
        self.h4_lookback = 50
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        h1_mom = data["close"].pct_change(self.h1_lookback)
        h4_close = data["close"].resample("4h").last().dropna()
        h4_mom = h4_close.pct_change(self.h4_lookback)
        h4_mom_h1 = h4_mom.reindex(data.index, method="ffill")
        long = (h1_mom > 0) & (h4_mom_h1 > 0)
        short = (h1_mom < 0) & (h4_mom_h1 < 0)
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=data.index)

# ============================================================
# RISK-CONTROLLED WRAPPER (No alpha changes)
# ============================================================
@dataclass
class RiskConfig:
    max_position_size: float = 1.0
    volatility_scaling: bool = False
    atr_volatility_lookback: int = 20
    atr_reduce_percentile: float = 80.0
    atr_no_trade_percentile: float = 95.0
    max_spread_multiple: float = 1.5
    spread_filter: bool = False
    max_daily_loss_pct: float = 999.0
    max_total_drawdown_pct: float = 999.0
    kill_switch_consecutive_losses: int = 999
    flatten_before_weekend: bool = False

class RiskControlledBacktester:
    """
    Wraps any strategy with risk controls.
    Modifies position sizing and enforces kill switches.
    Does NOT modify signal generation.
    """
    
    def __init__(self, data, strategy, base_config, risk_config):
        self.data = data.copy()
        self.strategy = strategy
        self.base_config = base_config
        self.risk = risk_config
        self.killed = False
        self.kill_reason = None
        self.consecutive_losses = 0
        self.daily_pnl = 0
        self.equity = 100000.0
        
    def run(self):
        signals = self.strategy.generate_signals(self.data).reindex(self.data.index).fillna(0)
        positions = signals.shift(1).fillna(0)
        
        # Volatility scaling
        if self.risk.volatility_scaling:
            atr = (self.data["high"] - self.data["low"]).rolling(self.risk.atr_volatility_lookback).mean()
            atr_pct = atr / self.data["close"]
            atr_thresh = atr_pct.rolling(500).quantile(self.risk.atr_reduce_percentile / 100)
            no_trade_thresh = atr_pct.rolling(500).quantile(self.risk.atr_no_trade_percentile / 100)
            
            vol_scalar = np.where(atr_pct > no_trade_thresh, 0,
                         np.where(atr_pct > atr_thresh, 0.5, 1.0))
            positions = positions * vol_scalar
        
        # Spread filter
        if self.risk.spread_filter:
            if "avg_spread" in self.data.columns:
                median_spread = self.data["avg_spread"].rolling(100).median()
                too_wide = self.data["avg_spread"] > median_spread * self.risk.max_spread_multiple
                positions[too_wide] = 0
        
        # Apply risk controls during simulation
        equity_curve = [self.equity]
        adj_returns = []
        
        price_returns = self.data["close"].pct_change().fillna(0)
        gross_returns = positions * price_returns
        
        # Apply base costs
        execution = ExecutionSimulator(self.base_config)
        gross_returns = execution.apply_costs_to_returns(self.data, gross_returns, positions)
        
        for i, (t, ret) in enumerate(gross_returns.items()):
            if i == 0:
                adj_returns.append(0)
                equity_curve.append(self.equity)
                continue
            
            # Check kill switches
            if self.killed:
                adj_returns.append(0)
                equity_curve.append(self.equity)
                continue
            
            # Update equity
            self.equity *= (1 + ret)
            adj_returns.append(ret)
            
            # Track P&L for daily limit
            self.daily_pnl += ret
            
            # Check drawdown kill switch
            peak = max(equity_curve)
            dd = (self.equity - peak) / peak
            
            if dd < -self.risk.max_total_drawdown_pct / 100:
                self.killed = True
                self.kill_reason = "Max drawdown exceeded: %.1f%%" % (dd * 100)
            
            # Check daily loss
            if self.daily_pnl < -self.risk.max_daily_loss_pct / 100:
                self.killed = True
                self.kill_reason = "Daily loss exceeded: %.2f%%" % (self.daily_pnl * 100)
            
            # Check consecutive losses (approximate from returns)
            if ret < 0:
                self.consecutive_losses += 1
            else:
                self.consecutive_losses = 0
            
            if self.consecutive_losses >= self.risk.kill_switch_consecutive_losses:
                self.killed = True
                self.kill_reason = "Consecutive losses: %d" % self.consecutive_losses
            
            equity_curve.append(self.equity)
        
        equity_series = pd.Series(equity_curve, index=self.data.index)
        
        return pd.Series(adj_returns, index=self.data.index), equity_series, self.killed, self.kill_reason

# ============================================================
# METRICS
# ============================================================
def calc_metrics(equity, returns):
    log_rets = np.log(equity / equity.shift(1)).dropna()
    ann_ret = log_rets.mean() * 252 * 24 * 100
    ann_vol = log_rets.std() * np.sqrt(252 * 24) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    
    cummax = equity.cummax()
    dd = (equity - cummax) / cummax
    max_dd = dd.min() * 100
    
    return {
        "sharpe": sharpe, "ann_ret": ann_ret, "ann_vol": ann_vol,
        "max_dd": max_dd, "total_ret": (equity.iloc[-1] / equity.iloc[0] - 1) * 100,
    }

# ============================================================
# DATA LOADING
# ============================================================
def load_data():
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    xau = pd.read_parquet(os.path.join(base, "data/raw/XAUUSD_H1.parquet"))
    if "time" in xau.columns:
        xau.set_index("time", inplace=True)
    
    dukas_paths = sorted(glob(os.path.join(base, "data/external/XAUUSD_M1_batch_*.parquet")))
    dfs = []
    for p in dukas_paths:
        d = pd.read_parquet(p)
        if "time" in d.columns:
            d.set_index("time", inplace=True)
        dfs.append(d)
    dukas = pd.concat(dfs).sort_index()
    dukas = dukas["close"].resample("1h").ohlc()
    dukas.columns = ["open", "high", "low", "close"]
    
    return xau, dukas

# ============================================================
# STRATEGY BREAKER SUITE
# ============================================================
class StrategyBreakerSuite:
    def __init__(self, data_bull, data_sideways, strategy):
        self.bull = data_bull
        self.side = data_sideways
        self.combined = pd.concat([data_sideways, data_bull]).sort_index()
        self.strategy = strategy
        self.results = []
    
    def _run_test(self, data, config, label, risk_cfg=None):
        if risk_cfg:
            bt = RiskControlledBacktester(data, self.strategy, config, risk_cfg)
            rets, equity, killed, reason = bt.run()
        else:
            bt = VectorizedBacktester(data, self.strategy, execution_config=config)
            bt.run()
            rets = bt.returns
            equity = bt.equity_curve
            killed = False
            reason = None
        
        m = calc_metrics(equity, rets)
        m["label"] = label
        m["killed"] = killed
        m["kill_reason"] = reason
        self.results.append(m)
        return m
    
    # --- 1. COST FRAGILITY ---
    def test_cost_fragility(self):
        print("\n" + "=" * 80)
        print("1. COST FRAGILITY")
        print("=" * 80)
        
        for spread_mult in [1.0, 1.5, 2.0, 3.0]:
            # Approximate: modify config or add synthetic spread
            cfg = ExecutionConfig(spread_pips=0.2 * spread_mult, commission_per_lot=7.0, 
                                 lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
            m = self._run_test(self.combined, cfg, "spread_%.1fx" % spread_mult)
            print("  Spread %.1fx: Sharpe=%.3f, DD=%.1f%%, TotalRet=%.1f%%" % (
                spread_mult, m["sharpe"], m["max_dd"], m["total_ret"]))
        
        for slip_pips in [0.0, 0.5, 1.0, 2.0]:
            cfg = ExecutionConfig(spread_pips=0.2, commission_per_lot=7.0,
                                 lot_size=100.0, trade_lots=1.0, slippage_pips=slip_pips, pip_value=1.0)
            m = self._run_test(self.combined, cfg, "slippage_%.1fp" % slip_pips)
            print("  Slippage %.1fp: Sharpe=%.3f, DD=%.1f%%, TotalRet=%.1f%%" % (
                slip_pips, m["sharpe"], m["max_dd"], m["total_ret"]))
        
        for comm_mult in [1.0, 1.5, 2.0]:
            cfg = ExecutionConfig(spread_pips=0.2, commission_per_lot=7.0 * comm_mult,
                                 lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
            m = self._run_test(self.combined, cfg, "commission_%.1fx" % comm_mult)
            print("  Commission %.1fx: Sharpe=%.3f, DD=%.1f%%, TotalRet=%.1f%%" % (
                comm_mult, m["sharpe"], m["max_dd"], m["total_ret"]))
    
    # --- 2. VOLATILITY SHOCK ---
    def test_volatility_shock(self):
        print("\n" + "=" * 80)
        print("2. VOLATILITY SHOCK")
        print("=" * 80)
        
        for vol_mult in [1.0, 1.5, 2.0, 3.0]:
            stress_df = self.combined.copy()
            rets = stress_df["close"].pct_change()
            # Add random vol shock
            np.random.seed(42)
            noise = np.random.randn(len(rets)) * rets.std() * (vol_mult - 1)
            stress_df["close"] = stress_df["close"] * (1 + noise)
            stress_df["high"] = stress_df["high"] * (1 + abs(noise))
            stress_df["low"] = stress_df["low"] * (1 - abs(noise))
            
            cfg = ExecutionConfig(spread_pips=0.2, commission_per_lot=7.0,
                                 lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
            m = self._run_test(stress_df, cfg, "vol_%.1fx" % vol_mult)
            print("  Vol %.1fx: Sharpe=%.3f, DD=%.1f%%, TotalRet=%.1f%% %s" % (
                vol_mult, m["sharpe"], m["max_dd"], m["total_ret"],
                "[KILLED: %s]" % m["kill_reason"] if m["killed"] else ""))
    
    # --- 3. WALK-FORWARD PER WINDOW ---
    def test_walk_forward_windows(self):
        print("\n" + "=" * 80)
        print("3. WALK-FORWARD PER WINDOW")
        print("=" * 80)
        
        train = 3000
        step = 1000
        cfg = ExecutionConfig(spread_pips=0.2, commission_per_lot=7.0,
                             lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
        
        window_metrics = []
        for start in range(0, len(self.combined) - train - step, step):
            test = self.combined.iloc[start + train:start + train + step]
            bt = VectorizedBacktester(test, self.strategy, execution_config=cfg)
            bt.run()
            m = calc_metrics(bt.equity_curve, bt.returns)
            window_metrics.append(m)
        
        sharpes = [w["sharpe"] for w in window_metrics]
        dds = [w["max_dd"] for w in window_metrics]
        
        print("  Windows tested:     %d" % len(window_metrics))
        print("  Sharpe mean:        %.3f" % np.mean(sharpes))
        print("  Sharpe median:      %.3f" % np.median(sharpes))
        print("  Sharpe std:         %.3f" % np.std(sharpes))
        print("  Sharpe min:         %.3f" % min(sharpes))
        print("  Sharpe max:         %.3f" % max(sharpes))
        print("  Sharpe 5th %%ile:    %.3f" % np.percentile(sharpes, 5))
        print("  Positive windows:   %d/%d (%.1f%%)" % (
            sum(1 for s in sharpes if s > 0), len(sharpes),
            sum(1 for s in sharpes if s > 0) / len(sharpes) * 100))
        print("  Worst 5 windows:")
        worst = sorted(window_metrics, key=lambda x: x["sharpe"])[:5]
        for i, w in enumerate(worst):
            print("    #%d: Sharpe=%.3f, Ret=%.1f%%, DD=%.1f%%" % (
                i+1, w["sharpe"], w["total_ret"], w["max_dd"]))
    
    # --- 4. PARAMETER PERTURBATION ---
    def test_parameter_perturbation(self):
        print("\n" + "=" * 80)
        print("4. PARAMETER PERTURBATION (FROZEN PARAMS - info only)")
        print("=" * 80)
        print("  MultiTF v1.0.0 has fixed parameters:")
        print("    H1 lookback:  %d bars (cannot change)" % self.strategy.h1_lookback)
        print("    H4 lookback:  %d bars (cannot change)" % self.strategy.h4_lookback)
        print("  No perturbation performed - strategy is frozen.")
    
    # --- 5. MONTE CARLO & BLOCK BOOTSTRAP ---
    def test_trade_dependency(self):
        print("\n" + "=" * 80)
        print("5. TRADE DEPENDENCY - MONTE CARLO")
        print("=" * 80)
        
        cfg = ExecutionConfig(spread_pips=0.2, commission_per_lot=7.0,
                             lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
        bt = VectorizedBacktester(self.combined, self.strategy, execution_config=cfg)
        bt.run()
        rets = bt.returns.dropna().values
        
        n_sims = 10000
        initial = 100000
        final_eq = []
        max_dds = []
        
        for _ in range(n_sims):
            shuffled = np.random.choice(rets, size=len(rets), replace=True)
            equity = initial * (1 + shuffled).cumprod()
            final_eq.append(equity[-1])
            cm = np.maximum.accumulate(equity)
            dd = (equity - cm) / cm
            max_dds.append(dd.min())
        
        print("  Simulations:        %d" % n_sims)
        print("  Median final eq:    $%.0f" % np.median(final_eq))
        print("  5th %%ile final:     $%.0f" % np.percentile(final_eq, 5))
        print("  95th %%ile final:    $%.0f" % np.percentile(final_eq, 95))
        print("  Median max DD:      %.1f%%" % (np.median(max_dds) * 100))
        print("  Worst 5%% DD:        %.1f%%" % (np.percentile(max_dds, 5) * 100))
        print("  Prob 30%% DD:        %.1f%%" % ((np.array(max_dds) < -0.30).mean() * 100))
        print("  Prob 40%% DD:        %.1f%%" % ((np.array(max_dds) < -0.40).mean() * 100))
        print("  Prob 50%% DD:        %.1f%%" % ((np.array(max_dds) < -0.50).mean() * 100))
    
    # --- 6. REGIME FAILURE ANALYSIS ---
    def test_regime_failure(self):
        print("\n" + "=" * 80)
        print("6. REGIME FAILURE ANALYSIS")
        print("=" * 80)
        
        cfg = ExecutionConfig(spread_pips=0.2, commission_per_lot=7.0,
                             lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
        
        regimes = [
            ("Bull (2021-2026)", self.bull),
            ("Sideways (2016-2019)", self.side),
            ("Combined", self.combined),
        ]
        
        # Add vol regimes on combined
        combined = self.combined.copy()
        vol = combined["close"].pct_change().rolling(20).std() * np.sqrt(252 * 24)
        high_vol = combined[vol > vol.quantile(0.8)]
        low_vol = combined[vol < vol.quantile(0.2)]
        
        regimes.extend([
            ("High Vol (top 20%%)", high_vol),
            ("Low Vol (bottom 20%%)", low_vol),
        ])
        
        for name, data in regimes:
            if len(data) < 500:
                continue
            bt = VectorizedBacktester(data, self.strategy, execution_config=cfg)
            bt.run()
            m = calc_metrics(bt.equity_curve, bt.returns)
            print("  %-25s: Sharpe=%.3f, Ret=%.1f%%, Vol=%.1f%%, DD=%.1f%%" % (
                name, m["sharpe"], m["ann_ret"], m["ann_vol"], m["max_dd"]))
    
    # --- 7. TAIL RISK ---
    def test_tail_risk(self):
        print("\n" + "=" * 80)
        print("7. TAIL RISK ANALYSIS")
        print("=" * 80)
        
        cfg = ExecutionConfig(spread_pips=0.2, commission_per_lot=7.0,
                             lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
        bt = VectorizedBacktester(self.combined, self.strategy, execution_config=cfg)
        bt.run()
        
        rets = bt.returns.dropna()
        equity = bt.equity_curve
        
        print("  Worst single bar:     %.3f%%" % (rets.min() * 100))
        print("  Worst day (24 bars):  %.3f%%" % (rets.rolling(24).sum().min() * 100))
        print("  Worst week:           %.3f%%" % (rets.rolling(24*5).sum().min() * 100))
        print("  Worst month:          %.3f%%" % (rets.rolling(24*21).sum().min() * 100))
        print("  95%% VaR (daily):      %.3f%%" % (np.percentile(rets, 5) * 100))
        print("  99%% VaR (daily):      %.3f%%" % (np.percentile(rets, 1) * 100))
        print("  CVaR 95%%:             %.3f%%" % (rets[rets <= np.percentile(rets, 5)].mean() * 100))
        print("  CVaR 99%%:             %.3f%%" % (rets[rets <= np.percentile(rets, 1)].mean() * 100))
        print("  Skewness:             %.3f" % rets.skew())
        print("  Kurtosis:             %.3f" % rets.kurtosis())
    
    # --- 8. WITH RISK CONTROLS ---
    def test_with_risk_controls(self):
        print("\n" + "=" * 80)
        print("8. WITH RISK CONTROLS")
        print("=" * 80)
        
        cfg = ExecutionConfig(spread_pips=0.2, commission_per_lot=7.0,
                             lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
        
        risk = RiskConfig(
            max_position_size=1.0,
            volatility_scaling=True,
            atr_volatility_lookback=20,
            atr_reduce_percentile=80.0,
            atr_no_trade_percentile=95.0,
            spread_filter=False,
            max_daily_loss_pct=1.0,
            max_total_drawdown_pct=15.0,
            kill_switch_consecutive_losses=10,
        )
        
        for vol_mult in [1.0, 1.5, 2.0, 3.0]:
            stress_df = self.combined.copy()
            if vol_mult > 1.0:
                rets = stress_df["close"].pct_change()
                np.random.seed(42)
                noise = np.random.randn(len(rets)) * rets.std() * (vol_mult - 1)
                stress_df["close"] = stress_df["close"] * (1 + noise)
                stress_df["high"] = stress_df["high"] * (1 + abs(noise))
                stress_df["low"] = stress_df["low"] * (1 - abs(noise))
            
            bt = RiskControlledBacktester(stress_df, self.strategy, cfg, risk)
            rets, equity, killed, reason = bt.run()
            m = calc_metrics(equity, rets)
            
            print("  Vol %.1fx: Sharpe=%.3f, DD=%.1f%%, TotalRet=%.1f%% %s" % (
                vol_mult, m["sharpe"], m["max_dd"], m["total_ret"],
                "[KILLED: %s]" % reason if killed else ""))
    
    def run_all(self):
        print("=" * 80)
        print("STRATEGY BREAKER SUITE - MultiTF v1.0.0")
        print("STATUS: FROZEN - No signal changes permitted")
        print("=" * 80)
        
        self.test_cost_fragility()
        self.test_volatility_shock()
        self.test_walk_forward_windows()
        self.test_parameter_perturbation()
        self.test_trade_dependency()
        self.test_regime_failure()
        self.test_tail_risk()
        self.test_with_risk_controls()
        
        print("\n" + "=" * 80)
        print("BREAKER SUITE COMPLETE")
        print("=" * 80)

def main():
    xau, dukas = load_data()
    bull = xau[xau.index >= "2021-01-01"]
    
    suite = StrategyBreakerSuite(bull, dukas, MultiTF_v1())
    suite.run_all()

if __name__ == "__main__":
    main()
