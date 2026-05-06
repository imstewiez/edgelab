"""
Yahoo Finance downloader for indices and equities.
Useful for instruments not available on Dukascopy (e.g., NAS100 via ^NDX).
"""
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

try:
    from logger import setup_logger
except ModuleNotFoundError:
    from src.logger import setup_logger

logger = setup_logger("yahoo")

TICKER_MAP = {
    "NAS100": "^NDX",      # Nasdaq-100 index
    "US30": "^DJI",        # Dow Jones
    "US500": "^GSPC",      # S&P 500
    "VIX": "^VIX",         # Volatility index
}


def download_ohlcv(
    symbol: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    period: str = "max",
    interval: str = "1h",
    output_dir: str = "data/external"
) -> Optional[str]:
    """
    Download OHLCV data from Yahoo Finance.
    
    Args:
        symbol: Our internal symbol name (e.g., NAS100)
        start/end: datetime range (if None, uses period)
        period: yfinance period string ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max")
        interval: "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"
        output_dir: where to save Parquet
    """
    ticker = TICKER_MAP.get(symbol, symbol)
    logger.info(f"Downloading {symbol} ({ticker}) from Yahoo Finance | interval={interval} period={period}")
    
    try:
        df = yf.download(
            ticker,
            start=start,
            end=end,
            period=period if start is None else None,
            interval=interval,
            progress=False,
            auto_adjust=False  # Keep original OHLC
        )
    except Exception as e:
        logger.error(f"Yahoo Finance download failed for {ticker}: {e}")
        return None
    
    if df.empty:
        logger.warning(f"No data returned for {ticker}")
        return None
    
    # Flatten multi-index columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # Rename columns to match our standard
    df = df.reset_index()
    
    # Handle different index names (Datetime vs Date)
    time_col = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(columns={
        time_col: "time",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume"
    })
    
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, f"{symbol}_{interval}_yahoo.parquet")
    df.to_parquet(filepath, index=False, compression="zstd")
    
    logger.info(
        f"Saved {len(df):,} rows ({interval}) to {filepath} | "
        f"Range: {df['time'].min()} to {df['time'].max()}"
    )
    return filepath


def resample_yahoo_to_timeframes(
    raw_path: str,
    symbol: str,
    target_timeframes: List[str],
    output_dir: str = "data/external"
) -> Dict[str, str]:
    """Resample Yahoo Finance data (assumed 1h) to higher timeframes."""
    df = pd.read_parquet(raw_path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    
    results = {}
    tf_map = {
        "M1": "1min", "M5": "5min", "M15": "15min",
        "H1": "1h", "H4": "4h", "D1": "1D"
    }
    
    for tf in target_timeframes:
        rule = tf_map.get(tf)
        if not rule:
            continue
        
        ohlc = df[["open", "high", "low", "close"]].resample(rule).agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        })
        vol = df["volume"].resample(rule).sum()
        combined = pd.concat([ohlc, vol], axis=1).dropna().reset_index()
        
        filepath = os.path.join(output_dir, f"{symbol}_{tf}_yahoo.parquet")
        combined.to_parquet(filepath, index=False, compression="zstd")
        results[tf] = filepath
        logger.info(f"Resampled {symbol} {tf}: {len(combined):,} bars -> {filepath}")
    
    return results


def run_yahoo_download(config_path: str = "config/settings.json"):
    """Download indices from Yahoo Finance per config."""
    with open(config_path) as f:
        config = json.load(f)
    
    external_dir = os.path.join(config["data"]["raw_dir"], "..", "external")
    os.makedirs(external_dir, exist_ok=True)
    
    for sym_cfg in config["symbols"]:
        symbol = sym_cfg["name"]
        if symbol not in TICKER_MAP:
            continue
        
        # Download hourly (max history available for 1h is ~730 days on Yahoo)
        # For longer history, use daily
        path_h1 = download_ohlcv(symbol, period="max", interval="1h", output_dir=external_dir)
        if path_h1:
            resample_yahoo_to_timeframes(path_h1, symbol, config["timeframes"], external_dir)
        
        # Also download daily for long-term history
        path_d1 = download_ohlcv(symbol, period="max", interval="1d", output_dir=external_dir)
        if path_d1:
            # Rename to D1_long for distinction
            long_path = os.path.join(external_dir, f"{symbol}_D1_long_yahoo.parquet")
            os.rename(path_d1, long_path)
            logger.info(f"Long-term daily data: {long_path}")


if __name__ == "__main__":
    run_yahoo_download()
