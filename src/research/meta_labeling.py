"""
Meta-labeling approach for XAUUSD.
Primary model: trend-following signal
Secondary model: ML classifier predicting which primary trades will succeed.
"""
import os
import sys
from typing import Dict

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.metrics import calculate_metrics, print_metrics
from research.edge_hunter import FeatureEngine
from logger import setup_logger

logger = setup_logger("meta_labeling")


def build_meta_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build features for meta-labeling model."""
    data = FeatureEngine.add_features(df).copy()
    
    # Entry-specific features
    for lag in [1, 2, 3, 5, 10]:
        data[f"ret_{lag}"] = data["close"].pct_change(lag)
    
    data["bar_position"] = (data["close"] - data["low"]) / (data["high"] - data["low"])
    data["rsi_slope"] = data["rsi_14"].diff(3)
    data["macd_hist_slope"] = data["macd"].diff(3)
    data["bb_width"] = (data["bb_upper_20"] - data["bb_lower_20"]) / data["sma_20"]
    
    # Volatility regime
    data["vol_zscore"] = (data["atr_20"] - data["atr_20"].rolling(50).mean()) / data["atr_20"].rolling(50).std()
    
    # Volume (if available)
    if "tick_volume" in data.columns:
        data["vol_ratio"] = data["tick_volume"] / data["tick_volume"].rolling(20).mean()
        data["vol_zscore"] = (data["tick_volume"] - data["tick_volume"].rolling(20).mean()) / data["tick_volume"].rolling(20).std()
    
    return data


class MetaLabelingStrategy:
    """
    Primary model: simple momentum + trend filter
    Secondary model: predicts which primary trades will be profitable
    """
    
    def __init__(
        self,
        momentum_lookback: int = 20,
        trend_lookback: int = 1200,
        hold_horizon: int = 20,
        ml_model_type: str = "rf",
        prob_threshold: float = 0.55,
        train_size: int = 3000,
    ):
        self.momentum_lookback = momentum_lookback
        self.trend_lookback = trend_lookback
        self.hold_horizon = hold_horizon
        self.ml_model_type = ml_model_type
        self.prob_threshold = prob_threshold
        self.train_size = train_size
        self.name = f"MetaLabel_{ml_model_type}"
    
    def _build_model(self):
        if self.ml_model_type == "rf":
            return RandomForestClassifier(
                n_estimators=100,
                max_depth=4,
                min_samples_leaf=100,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            )
        else:
            return LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)
    
    def generate_primary_signal(self, data: pd.DataFrame) -> pd.Series:
        """Base trend-following signal."""
        mom = data["close"].pct_change(self.momentum_lookback)
        trend_sma = data["close"].rolling(self.trend_lookback).mean()
        
        signals = pd.Series(0, index=data.index)
        signals[(mom > 0) & (data["close"] > trend_sma)] = 1
        signals[(mom < 0) & (data["close"] < trend_sma)] = -1
        return signals
    
    def train_meta_model(self, data: pd.DataFrame):
        """Train secondary model on past data."""
        data = build_meta_features(data)
        primary = self.generate_primary_signal(data)
        
        # Identify primary trade entry points
        entries = (primary != 0) & (primary.shift(1) == 0)
        
        # For each entry, calculate future return
        future_ret = data["close"].shift(-self.hold_horizon) / data["close"] - 1
        
        # Target: 1 if trade profitable, 0 if not
        target = pd.Series(np.nan, index=data.index)
        target[entries & (primary == 1)] = (future_ret > 0).astype(int)
        target[entries & (primary == -1)] = (future_ret < 0).astype(int)
        
        # Features at entry point
        exclude = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
        feature_cols = [c for c in data.columns if c not in exclude]
        
        valid = entries & target.notna() & data[feature_cols].notna().all(axis=1)
        X = data.loc[valid, feature_cols]
        y = target[valid]
        
        if len(y.unique()) < 2 or len(y) < 100:
            logger.warning("Insufficient data to train meta model")
            return None, feature_cols
        
        model = self._build_model()
        model.fit(X, y)
        
        if hasattr(model, "feature_importances_"):
            imp = pd.Series(model.feature_importances_, index=feature_cols)
            logger.info(f"Meta-model top features: {imp.sort_values(ascending=False).head(5).to_dict()}")
        
        return model, feature_cols
    
    def predict_meta(self, data: pd.DataFrame, model, feature_cols) -> pd.Series:
        """Apply meta-model to filter primary signals."""
        data = build_meta_features(data)
        primary = self.generate_primary_signal(data)
        entries = (primary != 0) & (primary.shift(1) == 0)
        
        valid = entries & data[feature_cols].notna().all(axis=1)
        if not valid.any():
            return pd.Series(0, index=data.index)
        
        X = data.loc[valid, feature_cols]
        probs = model.predict_proba(X)[:, 1]  # Probability of success
        
        # Filter: only keep entries where prob > threshold
        filtered = pd.Series(0, index=data.index)
        for i, idx in enumerate(X.index):
            if probs[i] >= self.prob_threshold:
                filtered.loc[idx] = primary.loc[idx]
        
        # Forward-fill the position until primary signal flips or meta says exit
        # Simplified: hold until primary signal changes
        position = pd.Series(0, index=data.index)
        current_pos = 0
        for i in range(len(data)):
            if filtered.iloc[i] != 0:
                current_pos = filtered.iloc[i]
            elif primary.iloc[i] == 0:
                current_pos = 0
            # If primary flipped but meta didn't confirm new entry, exit
            elif primary.iloc[i] != current_pos:
                current_pos = 0
            position.iloc[i] = current_pos
        
        return position
    
    def walk_forward(self, data: pd.DataFrame) -> Dict:
        """Run walk-forward meta-labeling backtest."""
        n = len(data)
        all_returns = []
        all_positions = []
        
        exec_cfg = ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0)
        initial_capital = 100_000.0
        equity = initial_capital
        
        windows = []
        step = 500
        start = self.train_size
        while start + step <= n:
            windows.append((start - self.train_size, start, start, start + step))
            start += step
        
        logger.info(f"Meta-labeling walk-forward: {len(windows)} windows")
        
        for i, (tr_s, tr_e, te_s, te_e) in enumerate(windows):
            train = data.iloc[tr_s:tr_e].copy()
            test = data.iloc[te_s:te_e].copy()
            
            model, feature_cols = self.train_meta_model(train)
            if model is None:
                # No model, stay flat
                equity_curve = pd.Series(equity, index=test.index)
                all_returns.append(pd.Series(0, index=test.index))
                continue
            
            positions = self.predict_meta(test, model, feature_cols)
            positions = positions.shift(1).fillna(0)  # Execute next bar
            
            price_ret = test["close"].pct_change().fillna(0)
            strat_ret = positions * price_ret
            
            # Apply costs
            changes = positions.diff().fillna(0) != 0
            strat_ret[changes] -= 0.00013  # XAUUSD round-turn cost
            
            window_equity = equity * (1 + strat_ret).cumprod()
            equity = window_equity.iloc[-1]
            
            all_returns.append(strat_ret)
            all_positions.append(positions)
            
            win_rate = (strat_ret[strat_ret != 0] > 0).mean() * 100 if (strat_ret != 0).any() else 0
            logger.info(f"  Window {i+1}: Equity={equity:,.0f} | WinRate={win_rate:.1f}% | Trades={changes.sum()}")
        
        combined_returns = pd.concat(all_returns).sort_index()
        combined_equity = initial_capital * (1 + combined_returns).cumprod()
        
        metrics = calculate_metrics(combined_equity, periods_per_year=365 * 24)
        return {
            "metrics": metrics,
            "equity_curve": combined_equity,
            "returns": combined_returns,
        }


def compare_approaches(data: pd.DataFrame):
    """Compare primary vs meta-labeling."""
    results = []
    
    # 1. Primary model only (momentum + trend)
    print("\n--- PRIMARY MODEL (Momentum + Trend) ---")
    primary = MetaLabelingStrategy(ml_model_type="none", prob_threshold=0.0)
    
    class PrimaryWrapper:
        name = "Primary_Trend"
        def generate_signals(self, d):
            return primary.generate_primary_signal(d)
    
    bt1 = VectorizedBacktester(data, PrimaryWrapper(), execution_config=ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0), periods_per_year=365*24)
    m1 = bt1.run()
    print_metrics(m1)
    results.append({"approach": "Primary Only", **extract_metrics(m1)})
    
    # 2. Meta-labeling with RF
    print("\n--- META-LABELING (RF Filter) ---")
    meta = MetaLabelingStrategy(ml_model_type="rf", prob_threshold=0.55)
    res = meta.walk_forward(data)
    print_metrics(res["metrics"])
    results.append({"approach": "Meta RF", **extract_metrics(res["metrics"])})
    
    # 3. Meta-labeling with LR
    print("\n--- META-LABELING (Logistic Regression) ---")
    meta2 = MetaLabelingStrategy(ml_model_type="lr", prob_threshold=0.55)
    res2 = meta2.walk_forward(data)
    print_metrics(res2["metrics"])
    results.append({"approach": "Meta LR", **extract_metrics(res2["metrics"])})
    
    return pd.DataFrame(results)


def extract_metrics(m: Dict) -> Dict:
    return {
        "sharpe": round(m.get("sharpe_ratio", 0), 3),
        "total_return_pct": round(m.get("total_return_pct", 0), 2),
        "ann_return_pct": round(m.get("ann_return_pct", 0), 2),
        "ann_vol_pct": round(m.get("ann_vol_pct", 0), 2),
        "max_dd_pct": round(m.get("max_drawdown_pct", 0), 2),
        "win_rate_pct": round(m.get("win_rate_pct", 0), 1),
        "num_trades": m.get("num_trades", 0),
    }


if __name__ == "__main__":
    df = pd.read_parquet("data/raw/XAUUSD_H1.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    
    print(f"Loaded {len(df)} rows")
    print("=" * 80)
    print("META-LABELING RESEARCH")
    print("=" * 80)
    
    summary = compare_approaches(df)
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(summary.to_string(index=False))
    
    os.makedirs("data/processed", exist_ok=True)
    summary.to_csv("data/processed/meta_labeling_results.csv", index=False)
