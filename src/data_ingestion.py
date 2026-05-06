import os
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from pathlib import Path

import pandas as pd
import numpy as np
from tqdm import tqdm

from logger import setup_logger
from database import DataCatalog

logger = setup_logger("data_ingestion")

# MT5 timeframe mapping
TIMEFRAME_MAP = {
    "M1": 1,
    "M2": 2,
    "M3": 3,
    "M4": 4,
    "M5": 5,
    "M6": 6,
    "M10": 10,
    "M12": 12,
    "M15": 15,
    "M20": 20,
    "M30": 30,
    "H1": 16385,
    "H2": 16386,
    "H3": 16387,
    "H4": 16388,
    "H6": 16390,
    "H8": 16392,
    "H12": 16396,
    "D1": 16408,
    "W1": 32769,
    "MN1": 49153,
}


def load_config(config_path: str = "config/settings.json") -> Dict:
    """Load JSON configuration."""
    with open(config_path, "r") as f:
        return json.load(f)


def ensure_mt5():
    """Import MetaTrader5 and return the module. Raises helpful error if unavailable."""
    try:
        import MetaTrader5 as mt5
        return mt5
    except ImportError:
        logger.error("MetaTrader5 Python package not installed. Run: pip install MetaTrader5")
        raise


def init_mt5(config: Dict) -> bool:
    """Initialize MT5 connection."""
    mt5 = ensure_mt5()
    
    if mt5.terminal_info() is not None:
        logger.info("MT5 already initialized.")
        return True
    
    path = config["mt5"].get("path")
    kwargs = {}
    if path and os.path.exists(path):
        kwargs["path"] = path
    
    logger.info(f"Initializing MT5... (path={path or 'default'})")
    initialized = mt5.initialize(**kwargs)
    
    if not initialized:
        error = mt5.last_error()
        logger.error(f"MT5 initialization failed: {error}")
        logger.error("Make sure MT5 terminal is installed and not already running with a conflicting connection.")
        return False
    
    logger.info(f"MT5 initialized successfully. Version: {mt5.version()}")
    return True


def shutdown_mt5():
    """Shutdown MT5 connection."""
    mt5 = ensure_mt5()
    mt5.shutdown()
    logger.info("MT5 connection shut down.")


def _mt5_timeframe(tf_str: str):
    """Convert string timeframe to MT5 constant."""
    mt5 = ensure_mt5()
    code = TIMEFRAME_MAP.get(tf_str.upper())
    if code is None:
        raise ValueError(f"Unknown timeframe: {tf_str}")
    return code


def validate_symbol(mt5_symbol: str) -> bool:
    """Check if symbol is available in MT5 Market Watch."""
    mt5 = ensure_mt5()
    symbol_info = mt5.symbol_info(mt5_symbol)
    if symbol_info is None:
        logger.warning(f"Symbol {mt5_symbol} not found in MT5.")
        # Try to print available symbols that look similar
        all_symbols = mt5.symbols_get()
        if all_symbols:
            matches = [s.name for s in all_symbols if mt5_symbol.lower() in s.name.lower() or s.name.lower() in mt5_symbol.lower()]
            if matches:
                logger.info(f"Did you mean one of these? {matches[:10]}")
        return False
    if not symbol_info.visible:
        logger.info(f"Symbol {mt5_symbol} exists but is not visible. Adding to Market Watch...")
        if not mt5.symbol_select(mt5_symbol, True):
            logger.error(f"Failed to add {mt5_symbol} to Market Watch.")
            return False
    return True


def fetch_rates(
    mt5_symbol: str,
    timeframe: str,
    date_from: datetime,
    date_to: datetime,
    chunk_days: int = 60
) -> Optional[pd.DataFrame]:
    """
    Fetch historical rates from MT5 in chunks to avoid request limits.
    
    MT5 can return max ~100k bars per request. For M1 data, that's ~69 days.
    We use conservative chunking.
    """
    mt5 = ensure_mt5()
    tf_code = _mt5_timeframe(timeframe)
    
    # Adjust chunk size based on timeframe
    bars_per_day = {"M1": 1440, "M5": 288, "M15": 96, "H1": 24, "H4": 6, "D1": 1}.get(timeframe.upper(), 1440)
    max_bars = 90000
    chunk_days = min(chunk_days, max(1, max_bars // max(bars_per_day, 1)))
    
    all_frames = []
    current = date_from
    total_expected = 0
    
    pbar = tqdm(desc=f"{mt5_symbol} {timeframe}", unit="chunks")
    while current < date_to:
        chunk_end = min(current + pd.Timedelta(days=chunk_days), date_to)
        
        rates = mt5.copy_rates_range(mt5_symbol, tf_code, current, chunk_end)
        
        if rates is None or len(rates) == 0:
            logger.debug(f"No data for {mt5_symbol} {timeframe} from {current} to {chunk_end}")
            current = chunk_end
            pbar.update(1)
            continue
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        all_frames.append(df)
        total_expected += len(df)
        
        current = chunk_end
        pbar.update(1)
    
    pbar.close()
    
    if not all_frames:
        return None
    
    combined = pd.concat(all_frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=['time']).sort_values('time').reset_index(drop=True)
    return combined


def ingest_symbol(
    symbol_cfg: Dict,
    timeframe: str,
    date_from: datetime,
    date_to: datetime,
    raw_dir: str,
    catalog: DataCatalog
) -> Tuple[bool, str]:
    """
    Download and store data for a single symbol/timeframe.
    Returns (success, message).
    """
    mt5_name = symbol_cfg["mt5_name"]
    name = symbol_cfg["name"]
    
    logger.info(f"Starting ingestion: {name} ({mt5_name}) {timeframe} from {date_from.date()} to {date_to.date()}")
    
    # Validate symbol
    if not validate_symbol(mt5_name):
        catalog.log_download(name, timeframe, date_from.isoformat(), date_to.isoformat(), 
                             0, "FAILED", f"Symbol {mt5_name} not available")
        return False, f"Symbol {mt5_name} not available in MT5"
    
    # Fetch
    df = fetch_rates(mt5_name, timeframe, date_from, date_to)
    
    if df is None or df.empty:
        catalog.log_download(name, timeframe, date_from.isoformat(), date_to.isoformat(),
                             0, "FAILED", "No data returned")
        return False, "No data returned from MT5"
    
    # Save to Parquet
    os.makedirs(raw_dir, exist_ok=True)
    safe_symbol = name.replace("/", "")
    filename = f"{safe_symbol}_{timeframe}.parquet"
    filepath = os.path.join(raw_dir, filename)
    
    df.to_parquet(filepath, index=False, compression='zstd')
    file_size = os.path.getsize(filepath)
    
    start_str = df['time'].min().isoformat()
    end_str = df['time'].max().isoformat()
    rows = len(df)
    
    catalog.register(
        symbol=name,
        mt5_symbol=mt5_name,
        timeframe=timeframe,
        start_date=start_str,
        end_date=end_str,
        rows_count=rows,
        file_path=filepath,
        file_size_bytes=file_size
    )
    catalog.log_download(name, timeframe, date_from.isoformat(), date_to.isoformat(),
                         rows, "SUCCESS", None)
    
    logger.info(f"Saved {rows:,} rows ({file_size/1024:.1f} KB) to {filepath}")
    return True, f"Downloaded {rows:,} rows"


def run_full_ingestion(config_path: str = "config/settings.json"):
    """Main entry point: ingest all configured symbols and timeframes."""
    config = load_config(config_path)
    
    if not init_mt5(config):
        logger.error("Cannot proceed without MT5 connection.")
        return
    
    catalog = DataCatalog(config["data"]["database_path"])
    raw_dir = config["data"]["raw_dir"]
    
    # Parse dates
    start_str = config["data"]["default_start"]
    end_str = config["data"].get("default_end")
    date_from = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    date_to = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) if end_str else datetime.now(timezone.utc)
    
    symbols = config["symbols"]
    timeframes = config["timeframes"]
    
    summary = []
    for sym in symbols:
        for tf in timeframes:
            success, msg = ingest_symbol(sym, tf, date_from, date_to, raw_dir, catalog)
            summary.append({
                "symbol": sym["name"],
                "timeframe": tf,
                "success": success,
                "message": msg
            })
    
    shutdown_mt5()
    
    # Print summary
    logger.info("=" * 60)
    logger.info("INGESTION SUMMARY")
    logger.info("=" * 60)
    for s in summary:
        status = "OK" if s["success"] else "FAIL"
        logger.info(f"[{status}] {s['symbol']} {s['timeframe']}: {s['message']}")


if __name__ == "__main__":
    run_full_ingestion()
