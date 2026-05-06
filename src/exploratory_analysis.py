"""
Exploratory analysis for FX market data.
Generates statistical summaries, correlations, regime detection, and data quality reports.
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from logger import setup_logger
from database import DataCatalog

logger = setup_logger("exploration")


def load_dataset(symbol: str, timeframe: str, raw_dir: str = "data/raw") -> Optional[pd.DataFrame]:
    """Load a Parquet dataset into a DataFrame."""
    path = os.path.join(raw_dir, f"{symbol}_{timeframe}.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    df['time'] = pd.to_datetime(df['time'], utc=True)
    df = df.sort_values('time').reset_index(drop=True)
    return df


def compute_returns(df: pd.DataFrame, method: str = "log") -> pd.DataFrame:
    """Add return columns to the dataframe."""
    df = df.copy()
    if method == "log":
        df['return'] = np.log(df['close'] / df['close'].shift(1))
    else:
        df['return'] = df['close'].pct_change()
    df['return_abs'] = df['return'].abs()
    df['range'] = df['high'] - df['low']
    df['body'] = (df['close'] - df['open']).abs()
    return df


def analyze_symbol_timeframe(symbol: str, timeframe: str, raw_dir: str = "data/raw") -> Dict:
    """Run full analysis on a single dataset."""
    df = load_dataset(symbol, timeframe, raw_dir)
    if df is None:
        return {"symbol": symbol, "timeframe": timeframe, "error": "No data"}
    
    df = compute_returns(df)
    returns = df['return'].dropna()
    
    # Basic stats
    total_bars = len(df)
    start = df['time'].min()
    end = df['time'].max()
    duration_days = (end - start).total_seconds() / 86400
    
    # Price stats
    price_mean = df['close'].mean()
    price_std = df['close'].std()
    
    # Return stats (annualized where applicable)
    periods_per_year = {
        "M1": 365 * 24 * 60, "M5": 365 * 24 * 12, "M15": 365 * 24 * 4,
        "H1": 365 * 24, "H4": 365 * 6, "D1": 365
    }.get(timeframe, 252)
    
    mean_ret = returns.mean()
    std_ret = returns.std()
    ann_return = mean_ret * periods_per_year
    ann_vol = std_ret * np.sqrt(periods_per_year)
    sharpe = ann_return / ann_vol if ann_vol > 0 else np.nan
    skew = returns.skew()
    kurt = returns.kurtosis()  # excess kurtosis
    max_dd = (df['close'] / df['close'].cummax() - 1).min()
    
    # Range / spread analysis
    avg_range = df['range'].mean()
    avg_spread_pct = (avg_range / price_mean) * 100 if price_mean != 0 else np.nan
    
    # Data quality
    expected_bars = duration_days * periods_per_year / 365
    coverage_pct = (total_bars / expected_bars) * 100 if expected_bars > 0 else 0
    duplicate_times = df['time'].duplicated().sum()
    gap_threshold = pd.Timedelta(minutes=10) if timeframe in ["M1", "M5"] else pd.Timedelta(hours=2)
    time_diffs = df['time'].diff().dropna()
    gaps = (time_diffs > gap_threshold).sum()
    
    # Regime detection: rolling volatility quintiles
    if len(returns) >= 100:
        rolling_vol = returns.rolling(window=min(100, len(returns)//4)).std() * np.sqrt(periods_per_year)
        low_vol_pct = (rolling_vol < rolling_vol.quantile(0.33)).mean() * 100
        high_vol_pct = (rolling_vol > rolling_vol.quantile(0.67)).mean() * 100
    else:
        low_vol_pct = high_vol_pct = np.nan
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": total_bars,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_days": round(duration_days, 1),
        "coverage_pct": round(coverage_pct, 1),
        "price_mean": round(price_mean, 5),
        "ann_return_pct": round(ann_return * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "skewness": round(skew, 3),
        "kurtosis": round(kurt, 3),
        "max_dd_pct": round(max_dd * 100, 2),
        "avg_range": round(avg_range, 5),
        "avg_spread_pct": round(avg_spread_pct, 4),
        "gaps": int(gaps),
        "duplicates": int(duplicate_times),
        "low_vol_pct": round(low_vol_pct, 1),
        "high_vol_pct": round(high_vol_pct, 1),
    }


def correlation_matrix(symbols: List[str], timeframe: str, raw_dir: str = "data/raw") -> Optional[pd.DataFrame]:
    """Compute correlation matrix of returns across symbols."""
    frames = {}
    for sym in symbols:
        df = load_dataset(sym, timeframe, raw_dir)
        if df is not None:
            df = compute_returns(df)
            frames[sym] = df.set_index('time')['return']
    
    if len(frames) < 2:
        return None
    
    combined = pd.DataFrame(frames).dropna()
    return combined.corr()


def run_exploration(config_path: str = "config/settings.json", output_dir: str = "data/processed"):
    """Run full exploratory analysis and save reports."""
    with open(config_path) as f:
        config = json.load(f)
    
    symbols = [s["name"] for s in config["symbols"]]
    timeframes = config["timeframes"]
    raw_dir = config["data"]["raw_dir"]
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info("Starting exploratory analysis...")
    
    # 1. Individual analyses
    all_results = []
    for sym in symbols:
        for tf in timeframes:
            logger.info(f"Analyzing {sym} {tf}...")
            result = analyze_symbol_timeframe(sym, tf, raw_dir)
            all_results.append(result)
    
    summary_df = pd.DataFrame(all_results)
    summary_path = os.path.join(output_dir, "summary_stats.csv")
    summary_df.to_csv(summary_path, index=False)
    logger.info(f"Summary stats saved to {summary_path}")
    
    # 2. Correlation matrices per timeframe
    for tf in timeframes:
        corr = correlation_matrix(symbols, tf, raw_dir)
        if corr is not None:
            corr_path = os.path.join(output_dir, f"correlation_{tf}.csv")
            corr.to_csv(corr_path)
            logger.info(f"Correlation matrix ({tf}) saved to {corr_path}")
    
    # 3. Print human-readable report
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("EXPLORATORY ANALYSIS REPORT")
    report_lines.append(f"Generated: {datetime.utcnow().isoformat()}")
    report_lines.append("=" * 80)
    
    report_lines.append("\n--- DATA COVERAGE & QUALITY ---")
    for _, row in summary_df.iterrows():
        if 'error' in row and pd.notna(row['error']):
            continue
        report_lines.append(
            f"{row['symbol']:8} {row['timeframe']:3} | "
            f"Bars: {row['bars']:>6,} | Duration: {row['duration_days']:>5.0f}d | "
            f"Coverage: {row['coverage_pct']:>5.1f}% | Gaps: {row['gaps']} | Dups: {row['duplicates']}"
        )
    
    report_lines.append("\n--- RETURN CHARACTERISTICS ---")
    for _, row in summary_df.iterrows():
        if 'error' in row and pd.notna(row['error']):
            continue
        report_lines.append(
            f"{row['symbol']:8} {row['timeframe']:3} | "
            f"AnnRet: {row['ann_return_pct']:>7.2f}% | AnnVol: {row['ann_vol_pct']:>6.2f}% | "
            f"Sharpe: {row['sharpe']:>6.3f} | Skew: {row['skewness']:>6.3f} | Kurt: {row['kurtosis']:>7.3f}"
        )
    
    report_lines.append("\n--- DRAWDOWN & RISK ---")
    for _, row in summary_df.iterrows():
        if 'error' in row and pd.notna(row['error']):
            continue
        report_lines.append(
            f"{row['symbol']:8} {row['timeframe']:3} | "
            f"MaxDD: {row['max_dd_pct']:>7.2f}% | AvgRange: {row['avg_range']:>10.5f} | "
            f"LowVol%: {row['low_vol_pct']:>5.1f} | HighVol%: {row['high_vol_pct']:>5.1f}"
        )
    
    report_lines.append("\n--- CORRELATIONS (H1) ---")
    corr_h1 = correlation_matrix(symbols, "H1", raw_dir)
    if corr_h1 is not None:
        report_lines.append(corr_h1.round(3).to_string())
    
    report_text = "\n".join(report_lines)
    report_path = os.path.join(output_dir, "report.txt")
    with open(report_path, "w") as f:
        f.write(report_text)
    
    logger.info(f"Full report saved to {report_path}")
    print("\n" + report_text)
    
    return summary_df


if __name__ == "__main__":
    run_exploration()
