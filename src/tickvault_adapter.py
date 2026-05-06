"""
Adapter to use tick-vault for Dukascopy downloads,
then convert tick data to OHLCV Parquet files matching our pipeline.
"""
import asyncio
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd

try:
    from logger import setup_logger
except ModuleNotFoundError:
    from src.logger import setup_logger

logger = setup_logger("tickvault_adapter")

# Map our symbols to Dukascopy names
SYMBOL_MAP = {
    "EURUSD": "EURUSD",
    "XAUUSD": "XAUUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
}


def _ticks_to_ohlcv(tick_df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample tick DataFrame (columns: time, ask, bid, ask_volume, bid_volume) to OHLCV."""
    tick_df = tick_df.copy()
    tick_df["time"] = pd.to_datetime(tick_df["time"], utc=True)
    tick_df["mid"] = (tick_df["ask"] + tick_df["bid"]) / 2
    tick_df = tick_df.set_index("time").sort_index()
    
    rule_map = {
        "M1": "1min", "M5": "5min", "M15": "15min",
        "H1": "1h", "H4": "4h", "D1": "1D"
    }
    rule = rule_map.get(timeframe)
    if not rule:
        raise ValueError(f"Unknown timeframe: {timeframe}")
    
    ohlc = tick_df["mid"].resample(rule).agg(["first", "max", "min", "last"])
    ohlc.columns = ["open", "high", "low", "close"]
    
    # Use tick count as volume proxy
    volume = tick_df["mid"].resample(rule).count()
    volume.name = "tick_volume"
    
    spread = (tick_df["ask"] - tick_df["bid"]).resample(rule).mean()
    spread.name = "avg_spread"
    
    df = pd.concat([ohlc, volume, spread], axis=1).dropna().reset_index()
    return df


async def download_and_convert(
    symbol: str,
    start: datetime,
    end: datetime,
    timeframes: List[str],
    output_dir: str = "data/external",
    cleanup_bi5: bool = True,
) -> Dict[str, str]:
    """
    Download ticks via tick-vault, resample to candles, save as Parquet.
    Returns dict of timeframe -> filepath.
    """
    try:
        from tick_vault import download_range, read_tick_data, reload_config
    except ImportError:
        logger.error("tick-vault not installed. Run: pip install tick-vault")
        raise
    
    dukascopy_symbol = SYMBOL_MAP.get(symbol, symbol)
    tv_base = os.path.join(output_dir, "tick_vault")
    os.makedirs(tv_base, exist_ok=True)
    
    reload_config(base_directory=tv_base)
    
    logger.info(f"[tick-vault] Starting download for {symbol} ({dukascopy_symbol}) {start.date()} to {end.date()}")
    await download_range(dukascopy_symbol, start, end)
    
    logger.info(f"[tick-vault] Reading tick data for {symbol}")
    ticks = read_tick_data(dukascopy_symbol, start, end, strict=False, show_progress=True)
    
    if ticks is None or ticks.empty:
        logger.error(f"No tick data retrieved for {symbol}")
        return {}
    
    logger.info(f"Retrieved {len(ticks):,} ticks for {symbol}")
    
    results = {}
    for tf in timeframes:
        logger.info(f"Resampling {symbol} to {tf}...")
        candles = _ticks_to_ohlcv(ticks, tf)
        if candles.empty:
            logger.warning(f"No candles generated for {symbol} {tf}")
            continue
        
        filepath = os.path.join(output_dir, f"{symbol}_{tf}_dukascopy.parquet")
        candles.to_parquet(filepath, index=False, compression="zstd")
        results[tf] = filepath
        logger.info(
            f"Saved {len(candles):,} {tf} bars to {filepath} | "
            f"Range: {candles['time'].min()} to {candles['time'].max()}"
        )
    
    # Cleanup raw .bi5 files to save disk space
    if cleanup_bi5:
        bi5_dir = os.path.join(tv_base, "downloads", dukascopy_symbol)
        if os.path.exists(bi5_dir):
            shutil.rmtree(bi5_dir)
            logger.info(f"Cleaned up raw .bi5 files in {bi5_dir}")
    
    return results


def run_download(
    symbol: str,
    years: int = 10,
    timeframes: Optional[List[str]] = None,
    output_dir: str = "data/external"
):
    """Synchronous wrapper for download_and_convert."""
    if timeframes is None:
        timeframes = ["M1", "M5", "M15", "H1", "H4", "D1"]
    
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * years)
    
    results = asyncio.run(download_and_convert(symbol, start, end, timeframes, output_dir))
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--output-dir", default="data/external")
    args = parser.parse_args()
    
    run_download(args.symbol, args.years, output_dir=args.output_dir)
