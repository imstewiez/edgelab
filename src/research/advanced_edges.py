"""
Advanced edge hunting: ML, cross-asset, regime detection, ensembles.
"""
import os
import sys
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.metrics import calculate_metrics, print_metrics
from backtest.walkforward import WalkForwardAnalysis
from research.edge_hunter import FeatureEngine
from logger import setup_logger

logger = setup_logger("advanced_edges")


def build_ml_features(df: pd.DataFrame, cross_assets: Dict[str, pd.DataFrame] = None) -> pd.DataFrame:
    """Build rich feature set for ML models."""
    data = FeatureEngine.add_features(df).copy()
    
    # More lagged returns
    for lag in [1, 2, 3, 5, 10, 20, 50]:
        data[f"ret_{lag}"] = data["close"].pct_change(lag)
    
    # Price position within bar
    data["bar_position"] = (data["close"] - data["low"]) / (data["high"] - data["low"])
    
    # Rate of change of indicators
    data["rsi_slope"] = data["rsi_14"].diff(5)
    data["macd_slope"] = data["macd"].diff(3)
    data["atr_slope"] = data["atr_20"].diff(5)
    
    # Trend strength
    data["adx_proxy"] = abs(data["close"].diff(20).rolling(20).sum()) / data["atr_20"].rolling(20).sum()
    
    # Volume features
    if "tick_volume" in data.columns:
        data["vol_zscore"] = (data["tick_volume"] - data["tick_volume"].rolling(20).mean()) / data["tick_volume"].rolling(20).std()
        data["vol_trend"] = data["tick_volume"].rolling(10).mean() / data["tick_volume"].rolling(50).mean()
    
    # Cross-asset features
    if cross_assets:
        for name, other_df in cross_assets.items():
            other = other_df.set_index("time")["close"].sort_index()
            aligned = other.reindex(data["time"]).ffill()
            for lag in [1, 5, 10]:
                data[f"{name}_ret_{lag}"] = aligned.pct_change(lag).values
            # Correlation proxy
            data[f"{name}_corr_proxy"] = data["ret_5"].rolling(50).corr(pd.Series(aligned.pct_change(5), index=data.index))
    
    return data


def create_ml_target(data: pd.DataFrame, horizon: int = 5, threshold_atr: float = 0.5) -> pd.Series:
    """
    Create target: 1=up, -1=down, 0=no-trade (move too small).
    Only trade when expected move exceeds threshold in ATR terms.
    """
    future_ret = data["close"].shift(-horizon) / data["close"] - 1
    threshold = threshold_atr * data["atr_20"] / data["close"]
    
    target = pd.Series(0, index=data.index)
    target[future_ret > threshold] = 1
    target[future_ret < -threshold] = -1
    return target


class MLStrategy:
    """Machine learning strategy with walk-forward retraining."""
    
    def __init__(
        self,
        model_type: str = "rf",  # "rf", "gb", "lr"
        horizon: int = 5,
        threshold_atr: float = 0.5,
        prob_threshold: float = 0.55,  # Min probability to take a trade
        max_position: float = 1.0,
    ):
        self.model_type = model_type
        self.horizon = horizon
        self.threshold_atr = threshold_atr
        self.prob_threshold = prob_threshold
        self.max_position = max_position
        self.scaler = StandardScaler()
        self.model = None
        self.feature_cols = None
        self.name = f"ML_{model_type}_h{horizon}"
    
    def _build_model(self):
        if self.model_type == "rf":
            return RandomForestClassifier(
                n_estimators=100,
                max_depth=5,
                min_samples_leaf=50,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            )
        elif self.model_type == "gb":
            return GradientBoostingClassifier(
                n_estimators=100,
                max_depth=3,
                min_samples_leaf=50,
                random_state=42,
            )
        elif self.model_type == "lr":
            return LogisticRegression(
                max_iter=1000,
                class_weight="balanced",
                random_state=42,
            )
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")
    
    def prepare(self, data: pd.DataFrame, cross_assets: Dict = None) -> pd.DataFrame:
        return build_ml_features(data, cross_assets)
    
    def fit(self, train_data: pd.DataFrame):
        """Train model on in-sample data."""
        data = self.prepare(train_data)
        target = create_ml_target(data, self.horizon, self.threshold_atr)
        
        # Select feature columns (exclude non-features)
        exclude = ["time", "open", "high", "low", "close", "tick_volume", 
                   "spread", "real_volume", "volume"]
        self.feature_cols = [c for c in data.columns if c not in exclude]
        
        # Drop rows with NaNs
        valid = data[self.feature_cols + ["close"]].notna().all(axis=1) & target.notna()
        X = data.loc[valid, self.feature_cols]
        y = target[valid]
        
        if len(y.unique()) < 2:
            logger.warning("Not enough target variety to train model")
            self.model = None
            return
        
        self.model = self._build_model()
        
        if self.model_type == "lr":
            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled, y)
        else:
            self.model.fit(X, y)
        
        # Feature importance
        if hasattr(self.model, "feature_importances_"):
            imp = pd.Series(self.model.feature_importances_, index=self.feature_cols)
            logger.info(f"Top features: {imp.sort_values(ascending=False).head(5).to_dict()}")
    
    def predict(self, data: pd.DataFrame) -> pd.Series:
        """Generate probability-weighted signals."""
        if self.model is None or self.feature_cols is None:
            return pd.Series(0, index=data.index)
        
        data = self.prepare(data)
        valid = data[self.feature_cols].notna().all(axis=1)
        X = data.loc[valid, self.feature_cols]
        
        if self.model_type == "lr":
            X_scaled = self.scaler.transform(X)
            probs = self.model.predict_proba(X_scaled)
        else:
            probs = self.model.predict_proba(X)
        
        # probs shape: (n_samples, n_classes)
        classes = self.model.classes_
        
        # Map probabilities to positions
        signals = pd.Series(0.0, index=data.index)
        for i, cls in enumerate(classes):
            if cls == 1:
                long_prob = probs[:, i]
                signals.loc[valid] += np.where(long_prob > self.prob_threshold, 
                                               (long_prob - 0.5) * 2 * self.max_position, 0)
            elif cls == -1:
                short_prob = probs[:, i]
                signals.loc[valid] -= np.where(short_prob > self.prob_threshold,
                                                (short_prob - 0.5) * 2 * self.max_position, 0)
        
        return signals.clip(-self.max_position, self.max_position)


class VolatilityTargetingStrategy:
    """
    Always-in trend strategy with volatility targeting.
    Position size = target_vol / realized_vol.
    """
    
    def __init__(self, target_vol: float = 0.10, vol_lookback: int = 20):
        self.target_vol = target_vol
        self.vol_lookback = vol_lookback
        self.name = "VolTarget_Trend"
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        data = FeatureEngine.add_features(data)
        
        # Base trend signal
        trend = np.where(data["close"] > data["sma_20"], 1, -1)
        
        # Volatility scaling
        log_ret = np.log(data["close"] / data["close"].shift(1))
        realized_vol = log_ret.rolling(self.vol_lookback).std() * np.sqrt(365 * 24)
        size = self.target_vol / realized_vol
        size = size.clip(0.1, 2.0)
        
        signals = pd.Series(trend * size, index=data.index)
        return signals.fillna(0)


class CrossAssetLeadLagStrategy:
    """Trade XAUUSD based on lead-lag with EURUSD and NAS100."""
    
    def __init__(self, lead_lag: int = 5):
        self.lead_lag = lead_lag
        self.name = f"CrossAsset_LeadLag_{lead_lag}"
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        # This strategy requires cross-asset data to be merged beforehand
        if "eurusd_ret_5" not in data.columns and "nas100_ret_5" not in data.columns:
            return pd.Series(0, index=data.index)
        
        signals = pd.Series(0.0, index=data.index)
        
        # If EURUSD is falling (dollar strength), gold often rises
        if "eurusd_ret_5" in data.columns:
            signals[data["eurusd_ret_5"] < -0.005] = 1
            signals[data["eurusd_ret_5"] > 0.005] = -1
        
        # If NAS100 is crashing, gold often rallies (flight to safety)
        if "nas100_ret_5" in data.columns:
            signals[data["nas100_ret_5"] < -0.02] += 0.5
            signals[data["nas100_ret_5"] > 0.02] -= 0.5
        
        return signals.clip(-1, 1)


def run_ml_walkforward(
    data: pd.DataFrame,
    model_type: str = "rf",
    train_size: int = 3000,
    test_size: int = 500,
    cross_assets: Dict = None,
) -> Dict:
    """Run walk-forward ML backtest."""
    
    n = len(data)
    all_returns = []
    all_positions = []
    all_equity = []
    
    exec_cfg = ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0)
    initial_capital = 100_000.0
    equity = initial_capital
    
    windows = []
    start = 0
    while start + train_size + test_size <= n:
        windows.append((start, start + train_size, start + train_size, start + train_size + test_size))
        start += test_size
    
    logger.info(f"ML walk-forward: {len(windows)} windows | Model: {model_type}")
    
    for i, (tr_s, tr_e, te_s, te_e) in enumerate(windows):
        train = data.iloc[tr_s:tr_e].copy()
        test = data.iloc[te_s:te_e].copy()
        
        ml = MLStrategy(model_type=model_type)
        ml.fit(train)
        
        # Generate signals on test set
        signals = ml.predict(test)
        positions = signals.shift(1).fillna(0)
        
        # Calculate returns
        price_ret = test["close"].pct_change().fillna(0)
        strat_ret = positions * price_ret
        
        # Apply costs
        simulator = ExecutionSimulatorFixed(exec_cfg)
        strat_ret = simulator.apply_costs_to_returns(test, strat_ret, positions)
        
        # Update equity
        window_equity = equity * (1 + strat_ret).cumprod()
        equity = window_equity.iloc[-1]
        
        all_returns.append(strat_ret)
        all_positions.append(positions)
        all_equity.append(window_equity)
        
        window_sharpe = strat_ret.mean() / strat_ret.std() * np.sqrt(365 * 24) if strat_ret.std() > 0 else 0
        logger.info(f"  Window {i+1}: Equity={equity:,.0f} | Sharpe={window_sharpe:.3f}")
    
    combined_returns = pd.concat(all_returns).sort_index()
    combined_equity = initial_capital * (1 + combined_returns).cumprod()
    
    metrics = calculate_metrics(combined_equity, periods_per_year=365 * 24)
    return {
        "metrics": metrics,
        "equity_curve": combined_equity,
        "returns": combined_returns,
        "windows": len(windows),
    }


class ExecutionSimulatorFixed:
    """Simplified cost model for XAUUSD."""
    def __init__(self, config: ExecutionConfig):
        self.cfg = config
    
    def apply_costs_to_returns(self, data, returns, positions):
        adj = returns.copy()
        changes = positions.diff().fillna(0) != 0
        # XAUUSD round-turn cost ≈ 0.013%
        cost_pct = 0.00013
        adj[changes] -= cost_pct
        return adj


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument("--model", default="rf", choices=["rf", "gb", "lr"])
    args = parser.parse_args()
    
    # Load primary data
    df = pd.read_parquet(f"data/raw/{args.symbol}_{args.timeframe}.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    
    # Load cross-asset data if available
    cross_assets = {}
    for sym in ["EURUSD", "NAS100"]:
        path = f"data/raw/{sym}_{args.timeframe}.parquet"
        if os.path.exists(path):
            other = pd.read_parquet(path)
            other["time"] = pd.to_datetime(other["time"], utc=True)
            cross_assets[sym.lower()] = other.sort_values("time").reset_index(drop=True)
            logger.info(f"Loaded cross-asset: {sym}")
    
    print(f"\nLoaded {len(df)} rows of {args.symbol} {args.timeframe}")
    print("=" * 80)
    print("ADVANCED EDGE HUNTING: ML + CROSS-ASSET + REGIMES")
    print("=" * 80)
    
    # 1. ML Strategy
    print("\n--- 1. MACHINE LEARNING STRATEGY ---")
    ml_result = run_ml_walkforward(df, model_type=args.model, cross_assets=cross_assets)
    print_metrics(ml_result["metrics"])
    
    # 2. Volatility Targeting
    print("\n--- 2. VOLATILITY TARGETING TREND ---")
    vol_strat = VolatilityTargetingStrategy(target_vol=0.15)
    bt = VectorizedBacktester(df, vol_strat, execution_config=ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0), periods_per_year=365*24)
    m = bt.run()
    print_metrics(m)
    
    # 3. Cross-asset (if data available)
    if cross_assets:
        print("\n--- 3. CROSS-ASSET LEAD-LAG ---")
        # Merge cross-asset features into main data
        merged = build_ml_features(df, cross_assets)
        ca_strat = CrossAssetLeadLagStrategy(lead_lag=5)
        ca_strat.name = "CrossAsset"
        
        # Hack: pass merged data as the strategy's input
        class CrossAssetWrapper:
            name = "CrossAsset"
            def __init__(self, merged_data):
                self.merged = merged_data
            def generate_signals(self, data):
                return CrossAssetLeadLagStrategy(5).generate_signals(self.merged)
        
        wrapper = CrossAssetWrapper(merged)
        bt2 = VectorizedBacktester(df, wrapper, execution_config=ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0), periods_per_year=365*24)
        m2 = bt2.run()
        print_metrics(m2)
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
