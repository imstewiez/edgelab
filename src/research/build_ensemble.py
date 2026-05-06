"""
Build the REAL ensemble:
- 4 cross-regime strategies on XAUUSD
- Apply best strategy to other pairs too
- Portfolio-level optimization with correlation-aware sizing
"""
import sys, os, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from glob import glob
from typing import Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtest.strategy import Strategy
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig

# --- Cost configs per asset type ------------------------------------
def get_config(symbol: str):
    if "XAU" in symbol or "XAG" in symbol:
        return ExecutionConfig(spread_pips=None, commission_per_lot=7.0, lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
    elif "GER" in symbol or "US30" in symbol or "NAS" in symbol:
        return ExecutionConfig(spread_pips=None, commission_per_lot=7.0, lot_size=1.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
    else:
        return ExecutionConfig(spread_pips=None, commission_per_lot=7.0, lot_size=100000.0, trade_lots=1.0, slippage_pips=0.0, pip_value=10.0)

# --- Strategies -----------------------------------------------------
class MOM100Strategy(Strategy):
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

class MultiHorizonStrategy(Strategy):
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

class TimeExitStrategy(Strategy):
    def __init__(self, lookback=100, max_hold=50):
        super().__init__("TimeExit")
        self.lookback = lookback
        self.max_hold = max_hold
    def generate_signals(self, data):
        mom = data["close"].pct_change(self.lookback)
        base_sig = np.where(mom > 0, 1, np.where(mom < 0, -1, 0))
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

# --- Data loading ---------------------------------------------------
def load_all_h1():
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    data = {}
    for path in glob(os.path.join(base, "data/raw/*_H1.parquet")):
        sym = os.path.basename(path).replace("_H1.parquet", "")
        df = pd.read_parquet(path)
        if "time" in df.columns:
            df.set_index("time", inplace=True)
        data[sym] = df
    return data

def load_dukascopy_h1():
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

# --- Run single strategy on single pair -----------------------------
def test_strategy(data, strategy, config):
    bt = VectorizedBacktester(data, strategy, execution_config=config)
    return bt.run()

# --- Portfolio ensemble builder -------------------------------------
class PortfolioEnsemble:
    """
    Multi-pair, multi-strategy ensemble with dynamic weighting.
    """
    def __init__(self, strategies_per_pair: Dict[str, List[Strategy]], 
                 pair_data: Dict[str, pd.DataFrame],
                 train_window: int = 2000):
        self.strategies = strategies_per_pair
        self.data = pair_data
        self.train_window = train_window
        
    def optimize_weights(self, pair: str, train_data: pd.DataFrame) -> Dict[str, float]:
        """Find optimal strategy weights for a pair using recent Sharpe."""
        sharpes = {}
        for strat in self.strategies.get(pair, []):
            try:
                config = get_config(pair)
                bt = VectorizedBacktester(train_data, strat, execution_config=config)
                metrics = bt.run()
                sharpes[strat.name] = max(0, metrics.get("sharpe_ratio", 0))
            except:
                sharpes[strat.name] = 0
        
        # Softmax weighting
        if sum(sharpes.values()) < 0.001:
            return {k: 1.0/len(sharpes) for k in sharpes}
        
        exp_s = {k: np.exp(v * 2) for k, v in sharpes.items()}  # Sharpe * 2 for sharper differentiation
        total = sum(exp_s.values())
        return {k: v/total for k, v in exp_s.items()}
    
    def run_portfolio_backtest(self, test_window: int = 1000):
        """Walk-forward portfolio backtest."""
        all_pair_returns = {}
        
        for pair, df in self.data.items():
            if len(df) < self.train_window + test_window:
                continue
            
            print("\n--- Pair: %s ---" % pair)
            
            # Walk-forward
            returns = []
            weights_history = []
            
            for start in range(0, len(df) - self.train_window - test_window, test_window):
                train = df.iloc[start:start + self.train_window]
                test = df.iloc[start + self.train_window:start + self.train_window + test_window]
                
                weights = self.optimize_weights(pair, train)
                weights_history.append(weights)
                
                # Generate combined signals for test period
                combined_signal = pd.Series(0.0, index=test.index)
                for strat in self.strategies.get(pair, []):
                    w = weights.get(strat.name, 0)
                    if w < 0.01:
                        continue
                    sig = strat.generate_signals(test).reindex(test.index).fillna(0)
                    combined_signal += sig * w
                
                # Run combined backtest
                config = get_config(pair)
                bt = VectorizedBacktester(test, MockStrategy(combined_signal), execution_config=config)
                metrics = bt.run()
                
                # Collect returns
                ret_series = bt.returns.copy()
                ret_series.index = test.index
                returns.append(ret_series)
                
                print("  Window %d-%d: Sharpe=%.3f, Ret=%.1f%%, DD=%.1f%%" % (
                    start, start + self.train_window + test_window,
                    metrics.get("sharpe_ratio", 0), metrics.get("ann_return_pct", 0),
                    metrics.get("max_drawdown_pct", 0)))
            
            if returns:
                all_pair_returns[pair] = pd.concat(returns).sort_index()
        
        return all_pair_returns

class MockStrategy(Strategy):
    """Wrapper for pre-computed signals."""
    def __init__(self, signals):
        super().__init__("Mock")
        self._signals = signals
    def generate_signals(self, data):
        return self._signals.reindex(data.index).fillna(0)

# --- Main -----------------------------------------------------------
def main():
    print("=" * 80)
    print("PORTFOLIO ENSEMBLE BUILDER")
    print("=" * 80)
    
    all_data = load_all_h1()
    dukas = load_dukascopy_h1()
    
    # Define which pairs to trade with which strategies
    xau_strats = [
        MOM100Strategy(100),
        AdaptiveRegimeStrategy(),
        MultiHorizonStrategy(),
        TimeExitStrategy(),
    ]
    
    strategies_per_pair = {}
    for sym in all_data:
        if "XAU" in sym:
            strategies_per_pair[sym] = xau_strats
        else:
            # Other pairs get simpler momentum
            strategies_per_pair[sym] = [MOM100Strategy(100), AdaptiveRegimeStrategy()]
    
    # Test each pair individually first
    print("\n" + "=" * 80)
    print("INDIVIDUAL PAIR RESULTS (Full History)")
    print("=" * 80)
    
    pair_results = []
    all_returns = {}
    
    for sym, df in all_data.items():
        config = get_config(sym)
        best_sharpe = -999
        best_strat = None
        best_metrics = None
        
        for strat in strategies_per_pair.get(sym, []):
            try:
                metrics = test_strategy(df, strat, config)
                if metrics.get("sharpe_ratio", -999) > best_sharpe:
                    best_sharpe = metrics.get("sharpe_ratio", -999)
                    best_strat = strat.name
                    best_metrics = metrics
            except Exception as e:
                pass
        
        if best_metrics:
            pair_results.append({
                "Pair": sym,
                "BestStrategy": best_strat,
                "Sharpe": round(best_metrics.get("sharpe_ratio", 0), 3),
                "AnnRet%": round(best_metrics.get("ann_return_pct", 0), 1),
                "AnnVol%": round(best_metrics.get("ann_vol_pct", 0), 1),
                "MaxDD%": round(best_metrics.get("max_drawdown_pct", 0), 1),
                "Trades": best_metrics.get("num_trades", 0),
            })
            
            # Also store returns series for correlation analysis
            bt = VectorizedBacktester(df, next(s for s in strategies_per_pair[sym] if s.name == best_strat), execution_config=config)
            bt.run()
            all_returns[sym] = bt.returns
    
    df_results = pd.DataFrame(pair_results)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    print(df_results.to_string(index=False))
    
    # Correlation matrix
    print("\n" + "=" * 80)
    print("PAIR RETURN CORRELATION MATRIX")
    print("=" * 80)
    
    if len(all_returns) > 1:
        aligned = pd.DataFrame(all_returns).fillna(0)
        corr = aligned.corr()
        print(corr.round(3).to_string())
        
        avg_corr = corr.values[np.triu_indices_from(corr.values, k=1)].mean()
        print("\nAverage pairwise correlation: %.3f" % avg_corr)
    
    # Equal-weight portfolio
    print("\n" + "=" * 80)
    print("EQUAL-WEIGHT PORTFOLIO (All Pairs)")
    print("=" * 80)
    
    if len(all_returns) > 1:
        aligned = pd.DataFrame(all_returns).fillna(0)
        # Equal weight across pairs
        portfolio_ret = aligned.mean(axis=1)
        equity = 100000 * (1 + portfolio_ret).cumprod()
        
        from backtest.metrics import calculate_metrics
        port_metrics = calculate_metrics(equity, periods_per_year=252*24)
        
        for k, v in port_metrics.items():
            print("  %s: %s" % (k, v))
    
    # XAUUSD-only ensemble (our best pair)
    print("\n" + "=" * 80)
    print("XAUUSD-ONLY ENSEMBLE (Walk-Forward Weighted)")
    print("=" * 80)
    
    xau = None
    for k in all_data:
        if "XAUUSD" in k:
            xau = all_data[k]
            break
    
    if xau is not None:
        ensemble = PortfolioEnsemble(
            {"XAUUSD": xau_strats},
            {"XAUUSD": xau},
            train_window=3000
        )
        
        # Manual walk-forward for XAUUSD
        train_w = 3000
        test_w = 1000
        portfolio_returns = []
        
        for start in range(0, len(xau) - train_w - test_w, test_w):
            train = xau.iloc[start:start + train_w]
            test = xau.iloc[start + train_w:start + train_w + test_w]
            
            weights = ensemble.optimize_weights("XAUUSD", train)
            print("\nWindow %d-%d weights: %s" % (start, start + train_w + test_w, 
                  {k: round(v, 3) for k, v in weights.items()}))
            
            combined_signal = pd.Series(0.0, index=test.index)
            for strat in xau_strats:
                w = weights.get(strat.name, 0)
                if w < 0.01:
                    continue
                sig = strat.generate_signals(test).reindex(test.index).fillna(0)
                combined_signal += sig * w
            
            bt = VectorizedBacktester(test, MockStrategy(combined_signal), execution_config=get_config("XAUUSD"))
            metrics = bt.run()
            
            ret_series = bt.returns.copy()
            ret_series.index = test.index
            portfolio_returns.append(ret_series)
            
            print("  Sharpe=%.3f, AnnRet=%.1f%%, DD=%.1f%%, Trades=%d" % (
                metrics.get("sharpe_ratio", 0), metrics.get("ann_return_pct", 0),
                metrics.get("max_drawdown_pct", 0), metrics.get("num_trades", 0)))
        
        if portfolio_returns:
            all_ret = pd.concat(portfolio_returns).sort_index()
            equity = 100000 * (1 + all_ret).cumprod()
            from backtest.metrics import calculate_metrics
            final_metrics = calculate_metrics(equity, periods_per_year=252*24)
            
            print("\n" + "-" * 60)
            print("XAUUSD ENSEMBLE - FINAL COMBINED RESULTS:")
            print("-" * 60)
            for k, v in final_metrics.items():
                print("  %s: %s" % (k, v))

if __name__ == "__main__":
    main()
