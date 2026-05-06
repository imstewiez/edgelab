"""
Cross-regime validation of ALL strategies on both bull and sideways data.
The MultiTF result looks too good - let's verify it's not just bull market beta.
"""
import sys, os, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from glob import glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtest.strategy import Strategy
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig

XAU_CONFIG = ExecutionConfig(spread_pips=None, commission_per_lot=7.0, lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)

class MOMStrategy(Strategy):
    def __init__(self, lookback=100):
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
    def __init__(self, h1_lookback=100, h4_lookback=50):
        super().__init__("MultiTF")
        self.h1_lb = h1_lookback
        self.h4_lb = h4_lookback
    def generate_signals(self, data):
        h1_mom = data["close"].pct_change(self.h1_lb)
        h4_close = data["close"].resample("4h").last().dropna()
        h4_mom = h4_close.pct_change(self.h4_lb)
        h4_mom_h1 = h4_mom.reindex(data.index, method="ffill")
        long = (h1_mom > 0) & (h4_mom_h1 > 0)
        short = (h1_mom < 0) & (h4_mom_h1 < 0)
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=data.index)

class DualMomentumStrategy(Strategy):
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

def load_data():
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    df = pd.read_parquet(os.path.join(base, "data/raw/XAUUSD_H1.parquet"))
    if "time" in df.columns:
        df.set_index("time", inplace=True)
    
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
    return df, dukas

def run():
    xau, dukas = load_data()
    
    bull = xau[xau.index >= "2021-01-01"]
    sideways = xau[xau.index < "2021-01-01"]
    
    strategies = [
        MOMStrategy(100),
        AdaptiveRegimeStrategy(),
        MultiTimeframeStrategy(),
        DualMomentumStrategy(),
        MOMStrategy(20),  # The "best" from parameter sweep
    ]
    
    print("=" * 100)
    print("CROSS-REGIME VALIDATION - Is MultiTF real or just bull market beta?")
    print("=" * 100)
    
    results = []
    
    for strat in strategies:
        print("\n--- %s ---" % strat.name)
        
        for regime_name, data in [("BULL (2021-2026)", bull), 
                                   ("SIDEWAYS (pre-2021)", sideways),
                                   ("DUKASCOPY (2016-2019)", dukas)]:
            if len(data) < 500:
                continue
            
            bt = VectorizedBacktester(data, strat, execution_config=XAU_CONFIG)
            bt.run()
            
            rets = bt.returns.dropna()
            if len(rets) < 10:
                continue
                
            ann_ret = rets.mean() * 252 * 24 * 100
            ann_vol = rets.std() * np.sqrt(252 * 24) * 100
            sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
            
            cummax = bt.equity_curve.cummax()
            dd = (bt.equity_curve - cummax) / cummax
            max_dd = dd.min() * 100
            
            trades = bt.trades
            pf = 0
            wr = 0
            if trades is not None and len(trades) > 0:
                wins = trades["return"][trades["return"] > 0]
                losses = trades["return"][trades["return"] < 0]
                pf = abs(wins.sum() / losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 0
                wr = (len(wins) / len(trades)) * 100
            
            results.append({
                "Strategy": strat.name,
                "Regime": regime_name,
                "Sharpe": round(sharpe, 3),
                "AnnRet%": round(ann_ret, 1),
                "AnnVol%": round(ann_vol, 1),
                "MaxDD%": round(max_dd, 1),
                "PF": round(pf, 2),
                "WR%": round(wr, 1),
                "Trades": len(trades) if trades is not None else 0,
            })
            
            print("  %-25s: Sharpe=%6.3f, Ret=%6.1f%%, Vol=%5.1f%%, DD=%6.1f%%, PF=%5.2f, WR=%4.1f%%, Trades=%d" % (
                regime_name, sharpe, ann_ret, ann_vol, max_dd, pf, wr, len(trades) if trades is not None else 0))
    
    print("\n" + "=" * 100)
    print("SUMMARY TABLE")
    print("=" * 100)
    df = pd.DataFrame(results)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    print(df.to_string(index=False))
    
    print("\n" + "=" * 100)
    print("CROSS-REGIME ANALYSIS")
    print("=" * 100)
    for strategy in df["Strategy"].unique():
        strat_data = df[df["Strategy"] == strategy]
        sharpes = strat_data["Sharpe"].values
        if len(sharpes) >= 2:
            min_sharpe = min(sharpes)
            avg_sharpe = np.mean(sharpes)
            avg_dd = strat_data["MaxDD%"].mean()
            avg_pf = strat_data["PF"].mean()
            print("  %-15s: min_sharpe=%6.3f, avg_sharpe=%5.3f, avg_DD=%5.1f%%, avg_PF=%4.2f" % (
                strategy, min_sharpe, avg_sharpe, avg_dd, avg_pf))

if __name__ == "__main__":
    run()
