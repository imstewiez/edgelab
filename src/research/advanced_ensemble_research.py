"""
Advanced Ensemble Research - Testing Architecturally Different Approaches
Uses the project's actual backtest engine with correct cost modeling.
"""
import sys, os, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from glob import glob
from typing import Dict, List

# Use project's actual infrastructure
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtest.strategy import Strategy
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig

# --- XAUUSD Cost Config ---------------------------------------------
XAU_CONFIG = ExecutionConfig(
    spread_pips=None,
    commission_per_lot=7.0,
    lot_size=100.0,
    trade_lots=1.0,
    slippage_pips=0.0,
    pip_value=1.0,
)

# --- Data Loading ---------------------------------------------------
def load_all_h1() -> Dict[str, pd.DataFrame]:
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    data = {}
    for path in glob(os.path.join(base, "data/raw/*_H1.parquet")):
        symbol = os.path.basename(path).replace("_H1.parquet", "")
        df = pd.read_parquet(path)
        if "time" in df.columns:
            df.set_index("time", inplace=True)
        data[symbol] = df
    for path in glob(os.path.join(base, "data/external/*_H1.parquet")):
        symbol = os.path.basename(path).replace("_H1.parquet", "")
        if symbol not in data:
            df = pd.read_parquet(path)
            if "time" in df.columns:
                df.set_index("time", inplace=True)
            data[symbol] = df
    return data

def load_dukascopy_h1() -> pd.DataFrame:
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    paths = sorted(glob(os.path.join(base, "data/external/XAUUSD_M1_batch_*.parquet")))
    if not paths:
        return pd.DataFrame()
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

# --- Strategy Implementations ---------------------------------------

class MOM100Strategy(Strategy):
    """Base MOM100 - our validated edge."""
    def __init__(self, lookback=100):
        super().__init__(f"MOM{lookback}")
        self.lookback = lookback
    def generate_signals(self, data):
        mom = data["close"].pct_change(self.lookback)
        return pd.Series(np.where(mom > 0, 1, np.where(mom < 0, -1, 0)), index=data.index)

class AdaptiveRegimeStrategy(Strategy):
    """Switch momentum lookback based on D1 volatility regime."""
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

class MultiHorizonConsensusStrategy(Strategy):
    """Weighted vote of MOM50/100/150, weight by signal stability."""
    def __init__(self, lookbacks=(50, 100, 150)):
        super().__init__("MultiHorizon")
        self.lookbacks = lookbacks
    def generate_signals(self, data):
        signals = {}
        for lb in self.lookbacks:
            mom = data["close"].pct_change(lb)
            signals[lb] = np.where(mom > 0, 1, -1)
        
        weights = {}
        for lb in self.lookbacks:
            sig_ret = signals[lb] * data["close"].pct_change()
            stability = 1.0 / (pd.Series(sig_ret).rolling(100).std().fillna(0.01) + 0.001)
            weights[lb] = stability
        
        total_w = sum(weights.values())
        consensus = sum(signals[lb] * (weights[lb] / total_w) for lb in self.lookbacks)
        return pd.Series(np.where(consensus > 0.3, 1, np.where(consensus < -0.3, -1, 0)), index=data.index)

class VolScaledMomentumStrategy(Strategy):
    """Position size = signal_strength / realized_vol."""
    def __init__(self, lookback=100):
        super().__init__("VolScaled")
        self.lookback = lookback
    def generate_signals(self, data):
        mom = data["close"].pct_change(self.lookback)
        realized_vol = data["close"].pct_change().rolling(20).std()
        raw_size = mom / (realized_vol.fillna(0.001) * np.sqrt(252))
        scaled = np.clip(raw_size / 2.0, -1.0, 1.0)
        return pd.Series(np.where(np.abs(scaled) > 0.3, np.sign(scaled) * np.abs(scaled), 0), index=data.index)

class SessionAwareStrategy(Strategy):
    """Different momentum by trading session."""
    def __init__(self, lookback=100):
        super().__init__("SessionAware")
        self.lookback = lookback
    def generate_signals(self, data):
        hour = data.index.hour
        mom = data["close"].pct_change(self.lookback)
        mom_fast = data["close"].pct_change(80)
        mom_slow = data["close"].pct_change(150)
        
        sig = pd.Series(0, index=data.index)
        asian = (hour >= 0) & (hour < 8)
        london = (hour >= 8) & (hour < 16)
        ny = (hour >= 16) | (hour < 0)
        
        sig[asian] = np.where(mom_slow[asian] > 0.015, 1, np.where(mom_slow[asian] < -0.015, -1, 0))
        sig[london] = np.where(mom_fast[london] > 0, 1, np.where(mom_fast[london] < 0, -1, 0))
        sig[ny] = np.where(mom[ny] > 0.005, 1, np.where(mom[ny] < -0.005, -1, 0))
        return sig

class PullbackMomentumStrategy(Strategy):
    """MOM100 signal + pullback to EMA20."""
    def __init__(self, mom_lb=100, ema=20):
        super().__init__("Pullback")
        self.mom_lb = mom_lb
        self.ema = ema
    def generate_signals(self, data):
        mom = data["close"].pct_change(self.mom_lb)
        ema = data["close"].ewm(span=self.ema).mean()
        dist = (data["close"] - ema) / ema
        long = (mom > 0) & (dist < 0.002)
        short = (mom < 0) & (dist > -0.002)
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=data.index)

class DualMomentumStrategy(Strategy):
    """Absolute + relative momentum must agree."""
    def __init__(self, lookback=100, filter_lb=20):
        super().__init__("DualMomentum")
        self.lookback = lookback
        self.filter_lb = filter_lb
    def generate_signals(self, data):
        abs_mom = data["close"].pct_change(self.lookback)
        rel_mom = data["close"].pct_change(self.filter_lb)
        long = (abs_mom > 0) & (rel_mom > 0)
        short = (abs_mom < 0) & (rel_mom < 0)
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=data.index)

class ADXFilteredMomentumStrategy(Strategy):
    """MOM100 only when ADX > 20 (trending)."""
    def __init__(self, lookback=100, adx_period=14):
        super().__init__("ADXFilter")
        self.lookback = lookback
        self.adx_period = adx_period
    def generate_signals(self, data):
        mom = data["close"].pct_change(self.lookback)
        
        tr1 = data["high"] - data["low"]
        tr2 = abs(data["high"] - data["close"].shift(1))
        tr3 = abs(data["low"] - data["close"].shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(self.adx_period).mean()
        
        plus_dm = data["high"].diff()
        minus_dm = -data["low"].diff()
        plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0)
        minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0)
        
        plus_di = 100 * pd.Series(plus_dm).rolling(self.adx_period).mean() / atr
        minus_di = 100 * pd.Series(minus_dm).rolling(self.adx_period).mean() / atr
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        adx = dx.rolling(self.adx_period).mean()
        
        sig = pd.Series(0, index=data.index)
        trending = adx > 20
        sig[trending.fillna(False)] = np.where(mom[trending.fillna(False)] > 0, 1, -1)
        return sig

class GoldSilverRatioStrategy(Strategy):
    """Mean-reversion on XAUUSD/XAGUSD ratio."""
    def __init__(self, lookback=100, z_thresh=1.0):
        super().__init__("GoldSilverRatio")
        self.lookback = lookback
        self.z_thresh = z_thresh
        self.xau_data = None
        self.xag_data = None
    def set_data(self, xau, xag):
        self.xau_data = xau
        self.xag_data = xag
    def generate_signals(self, data):
        if self.xau_data is None or self.xag_data is None:
            return pd.Series(0, index=data.index)
        ratio = self.xau_data["close"] / self.xag_data["close"]
        ratio_ma = ratio.rolling(self.lookback).mean()
        ratio_std = ratio.rolling(self.lookback).std()
        z = (ratio - ratio_ma) / ratio_std
        
        sig = pd.Series(0, index=data.index)
        sig[z < -self.z_thresh] = 1   # Ratio low -> gold cheap vs silver -> long gold
        sig[z > self.z_thresh] = -1   # Ratio high -> gold expensive vs silver -> short gold
        return sig

class BollingerMomentumStrategy(Strategy):
    """MOM100 only when price at Bollinger extreme (trend confirmation)."""
    def __init__(self, mom_lb=100, bb_period=20, bb_std=2.0):
        super().__init__("BBMomentum")
        self.mom_lb = mom_lb
        self.bb_period = bb_period
        self.bb_std = bb_std
    def generate_signals(self, data):
        mom = data["close"].pct_change(self.mom_lb)
        ma = data["close"].rolling(self.bb_period).mean()
        std = data["close"].rolling(self.bb_period).std()
        upper = ma + self.bb_std * std
        lower = ma - self.bb_std * std
        
        # Long only if mom>0 AND price near upper band (strong uptrend)
        # Short only if mom<0 AND price near lower band (strong downtrend)
        long = (mom > 0) & (data["close"] > upper)
        short = (mom < 0) & (data["close"] < lower)
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=data.index)

class TimeExitMomentumStrategy(Strategy):
    """MOM100 with max hold time of 50 bars."""
    def __init__(self, lookback=100, max_hold=50):
        super().__init__("TimeExit")
        self.lookback = lookback
        self.max_hold = max_hold
    def generate_signals(self, data):
        mom = data["close"].pct_change(self.lookback)
        base_sig = np.where(mom > 0, 1, np.where(mom < 0, -1, 0))
        
        # Track position duration and force exit after max_hold bars
        sig = pd.Series(0, index=data.index)
        pos = 0
        entry_idx = 0
        for i, (t, s) in enumerate(zip(data.index, base_sig)):
            if pos == 0 and s != 0:
                pos = s
                entry_idx = i
            elif pos != 0:
                if s != pos and s != 0:
                    pos = s
                    entry_idx = i
                elif i - entry_idx >= self.max_hold:
                    pos = 0
            sig.iloc[i] = pos
        return sig

# --- Research Runner ------------------------------------------------
def run_backtest(df, strategy, config=XAU_CONFIG):
    bt = VectorizedBacktester(df, strategy, execution_config=config)
    return bt.run()

def run_research():
    print("=" * 80)
    print("ADVANCED ENSEMBLE RESEARCH - Architecturally Different Approaches")
    print("=" * 80)
    
    all_data = load_all_h1()
    dukas_data = load_dukascopy_h1()
    
    print("\nLoaded pairs: %s" % list(all_data.keys()))
    if len(dukas_data) > 0:
        print("Dukascopy H1: %d bars (%s to %s)" % (len(dukas_data), dukas_data.index[0], dukas_data.index[-1]))
    else:
        print("No Dukascopy data yet")
    
    xau = None
    for k in all_data:
        if "XAUUSD" in k:
            xau = all_data[k]
            print("\nUsing %s: %d bars, %s to %s" % (k, len(xau), xau.index[0], xau.index[-1]))
            break
    
    if xau is None:
        print("No XAUUSD data found!")
        return
    
    bull_data = xau[xau.index >= "2021-01-01"]
    pre_data = xau[xau.index < "2021-01-01"]
    
    strategies = [
        MOM100Strategy(lookback=100),
        AdaptiveRegimeStrategy(),
        MultiHorizonConsensusStrategy(),
        VolScaledMomentumStrategy(),
        SessionAwareStrategy(),
        PullbackMomentumStrategy(),
        DualMomentumStrategy(),
        ADXFilteredMomentumStrategy(),
        BollingerMomentumStrategy(),
        TimeExitMomentumStrategy(),
    ]
    
    # Add Gold-Silver ratio if XAGUSD available
    xag = None
    for k in all_data:
        if "XAGUSD" in k:
            xag = all_data[k]
            break
    if xag is not None:
        gsr = GoldSilverRatioStrategy()
        gsr.set_data(xau, xag)
        strategies.append(gsr)
    
    results = []
    
    for strat in strategies:
        print("\n%s" % ("-" * 60))
        print("Testing: %s" % strat.name)
        print("-" * 60)
        
        for regime_name, data in [("Bull (2021-2026)", bull_data),
                                   ("Sideways (pre-2021)", pre_data),
                                   ("Dukascopy (2016-2019)", dukas_data)]:
            if len(data) < 500:
                continue
            try:
                metrics = run_backtest(data, strat)
                results.append({
                    "Strategy": strat.name,
                    "Regime": regime_name,
                    "Sharpe": round(metrics.get("sharpe_ratio", 0), 3),
                    "AnnRet%": round(metrics.get("ann_return_pct", 0), 1),
                    "AnnVol%": round(metrics.get("ann_vol_pct", 0), 1),
                    "MaxDD%": round(metrics.get("max_drawdown_pct", 0), 1),
                    "Trades": metrics.get("num_trades", 0),
                    "WinRate%": metrics.get("win_rate_pct", 0),
                })
                print("  %-25s: Sharpe=%6.3f, AnnRet=%5.1f%%, Vol=%4.1f%%, DD=%5.1f%%, Trades=%4d, WR=%4.1f%%" % (
                    regime_name, metrics.get("sharpe_ratio", 0),
                    metrics.get("ann_return_pct", 0), metrics.get("ann_vol_pct", 0),
                    metrics.get("max_drawdown_pct", 0), metrics.get("num_trades", 0),
                    metrics.get("win_rate_pct", 0) or 0))
            except Exception as e:
                print("  %-25s: ERROR - %s" % (regime_name, e))
    
    print("\n%s" % ("=" * 80))
    print("SUMMARY TABLE")
    print("=" * 80)
    df_results = pd.DataFrame(results)
    if not df_results.empty:
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 200)
        print(df_results.to_string(index=False))
        
        print("\n%s" % ("-" * 60))
        print("CROSS-REGIME ANALYSIS")
        print("-" * 60)
        
        for strategy in df_results["Strategy"].unique():
            strat_data = df_results[df_results["Strategy"] == strategy]
            sharpes = strat_data["Sharpe"].values
            if len(sharpes) >= 2:
                min_sharpe = min(sharpes)
                avg_sharpe = np.mean(sharpes)
                avg_dd = strat_data["MaxDD%"].mean()
                print("  %-22s: min_sharpe=%6.3f, avg_sharpe=%5.3f, avg_DD=%5.1f%%" % (
                    strategy, min_sharpe, avg_sharpe, avg_dd))
    
    return df_results

if __name__ == "__main__":
    run_research()
