"""
Dukascopy historical tick data downloader.
Downloads compressed tick data, decodes it, resamples to OHLCV, and stores as Parquet.

Dukascopy provides free tick history back to ~2003 for majors.
URL format: https://www.dukascopy.com/datafeed/{SYMBOL}/{YYYY}/{MM-1}/{DD}/{HH}h_ticks.bi5
"""
import json
import lzma
import os
import struct
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from tqdm import tqdm

try:
    from logger import setup_logger
except ModuleNotFoundError:
    from src.logger import setup_logger

logger = setup_logger("dukascopy")

# Price scaling factors for Dukascopy tick data
# Values are the divisor to convert integer prices to float
PIPET_SCALES = {
    "EURUSD": 100_000,
    "GBPUSD": 100_000,
    "USDJPY": 1_000,
    "AUDUSD": 100_000,
    "USDCAD": 100_000,
    "USDCHF": 100_000,
    "NZDUSD": 100_000,
    "XAUUSD": 1_000,
    "XAGUSD": 1_000,
}

# Dukascopy symbol name mapping (some symbols have different names)
SYMBOL_MAP = {
    "EURUSD": "EURUSD",
    "XAUUSD": "XAUUSD",
    "NAS100": "USATECH.IDX",  # May or may not exist on Dukascopy
}

BASE_URL = "https://www.dukascopy.com/datafeed"


def _hour_chunks(start: datetime, end: datetime) -> List[datetime]:
    """Generate hourly datetime chunks between start and end."""
    chunks = []
    current = start.replace(minute=0, second=0, microsecond=0)
    while current <= end:
        chunks.append(current)
        current += timedelta(hours=1)
    return chunks


def _make_url(symbol: str, dt: datetime) -> str:
    """Build Dukascopy URL for a given symbol and hour."""
    # Month is 0-indexed in Dukascopy URLs
    return f"{BASE_URL}/{symbol}/{dt.year}/{dt.month - 1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"


def _download_hour(url: str, retries: int = 3, timeout: int = 30) -> Optional[bytes]:
    """Download a single .bi5 file with retries. Returns None if 404 (no data)."""
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=timeout) as response:
                return response.read()
        except HTTPError as e:
            if e.code == 404:
                return None  # No data for this hour (weekend/holiday)
            logger.debug(f"HTTP {e.code} for {url}, attempt {attempt + 1}/{retries}")
        except Exception as e:
            logger.debug(f"Error downloading {url}: {e}, attempt {attempt + 1}/{retries}")
    return None


def _decode_ticks(data: bytes, pip_scale: float) -> Optional[pd.DataFrame]:
    """
    Decode Dukascopy .bi5 binary tick data.
    Format per record (20 bytes, big-endian):
        uint32: milliseconds within hour
        uint32: ask price * scale
        uint32: bid price * scale
        float32: ask volume
        float32: bid volume
    """
    if not data or len(data) < 20:
        return None

    # Dukascopy uses LZMA compression
    try:
        decompressed = lzma.decompress(data, format=lzma.FORMAT_AUTO)
    except lzma.LZMAError:
        return None

    record_size = 20
    n_records = len(decompressed) // record_size
    if n_records == 0:
        return None

    # Unpack all records efficiently using struct
    fmt = ">IIIff"  # big-endian: uint32, uint32, uint32, float32, float32
    records = []
    offset = 0
    for _ in range(n_records):
        rec = decompressed[offset:offset + record_size]
        ms, ask_raw, bid_raw, ask_vol, bid_vol = struct.unpack(fmt, rec)
        records.append((ms, ask_raw, bid_raw, ask_vol, bid_vol))
        offset += record_size

    df = pd.DataFrame(records, columns=["ms", "ask_raw", "bid_raw", "ask_vol", "bid_vol"])
    df["ask"] = df["ask_raw"] / pip_scale
    df["bid"] = df["bid_raw"] / pip_scale
    df["mid"] = (df["ask"] + df["bid"]) / 2
    df["spread"] = df["ask"] - df["bid"]
    return df


def _ticks_to_ohlcv(tick_df: pd.DataFrame, hour_dt: datetime, timeframe: str = "M1") -> pd.DataFrame:
    """
    Convert tick DataFrame to OHLCV bars.
    tick_df must have 'ms' (milliseconds within hour) and 'mid'/'spread' columns.
    """
    tick_df = tick_df.copy()
    tick_df["time"] = hour_dt + pd.to_timedelta(tick_df["ms"], unit="ms")
    tick_df = tick_df.set_index("time").sort_index()

    # Use mid price for OHLC
    ohlc = tick_df["mid"].resample(timeframe).agg(["first", "max", "min", "last"])
    ohlc.columns = ["open", "high", "low", "close"]

    # Volume: use tick count as proxy (Dukascopy volumes are not contract volume)
    volume = tick_df["mid"].resample(timeframe).count()
    volume.name = "tick_volume"

    # Spread: average spread per bar
    avg_spread = tick_df["spread"].resample(timeframe).mean()
    avg_spread.name = "avg_spread"

    df = pd.concat([ohlc, volume, avg_spread], axis=1).dropna()
    df = df.reset_index()
    return df


def download_symbol_range(
    symbol: str,
    start: datetime,
    end: datetime,
    output_dir: str = "data/external",
    max_workers: int = 6,
    save_ticks: bool = False,
) -> Optional[str]:
    """
    Download Dukascopy tick data for a date range, resample to M1, save as Parquet.
    Returns path to saved file or None.
    """
    dukascopy_symbol = SYMBOL_MAP.get(symbol, symbol)
    pip_scale = PIPET_SCALES.get(symbol)
    if pip_scale is None:
        logger.warning(f"Unknown pip scale for {symbol}, assuming 100000. Add it to PIPET_SCALES.")
        pip_scale = 100_000

    logger.info(f"Downloading {symbol} ({dukascopy_symbol}) from {start.date()} to {end.date()}")

    hours = _hour_chunks(start, end)
    logger.info(f"Total hours to fetch: {len(hours):,}")

    all_bars = []
    failed_hours = 0
    empty_hours = 0

    # Progress bar for sequential feedback
    with tqdm(total=len(hours), desc=f"DL {symbol}", unit="hr") as pbar:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_hour = {
                executor.submit(_download_hour, _make_url(dukascopy_symbol, h)): h
                for h in hours
            }

            for future in as_completed(future_to_hour):
                hour_dt = future_to_hour[future]
                try:
                    raw_data = future.result()
                except Exception as exc:
                    logger.debug(f"Hour {hour_dt} generated an exception: {exc}")
                    failed_hours += 1
                    pbar.update(1)
                    continue

                if raw_data is None:
                    empty_hours += 1
                    pbar.update(1)
                    continue

                ticks = _decode_ticks(raw_data, pip_scale)
                if ticks is None or ticks.empty:
                    empty_hours += 1
                    pbar.update(1)
                    continue

                bars = _ticks_to_ohlcv(ticks, hour_dt, timeframe="1min")
                if not bars.empty:
                    all_bars.append(bars)

                pbar.update(1)

    if not all_bars:
        logger.error(f"No data downloaded for {symbol}. Check symbol name and date range.")
        return None

    combined = pd.concat(all_bars, ignore_index=True)
    combined = combined.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, f"{symbol}_M1_dukascopy.parquet")
    combined.to_parquet(filepath, index=False, compression="zstd")

    logger.info(
        f"Saved {len(combined):,} M1 bars to {filepath} | "
        f"Failed: {failed_hours} | Empty: {empty_hours} | "
        f"Range: {combined['time'].min()} to {combined['time'].max()}"
    )
    return filepath


def resample_to_timeframes(
    m1_path: str,
    symbol: str,
    timeframes: List[str],
    output_dir: str = "data/external"
) -> Dict[str, str]:
    """
    Read M1 Parquet and resample to higher timeframes.
    Returns dict of timeframe -> filepath.
    """
    df = pd.read_parquet(m1_path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()

    results = {}
    tf_map = {
        "M1": "1min", "M5": "5min", "M15": "15min",
        "H1": "1h", "H4": "4h", "D1": "1D"
    }

    for tf in timeframes:
        if tf == "M1":
            results[tf] = m1_path
            continue

        rule = tf_map.get(tf)
        if not rule:
            logger.warning(f"Unknown timeframe: {tf}")
            continue

        ohlc = df[["open", "high", "low", "close"]].resample(rule).agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        })
        vol = df["tick_volume"].resample(rule).sum()
        spread = df["avg_spread"].resample(rule).mean()

        resampled = pd.concat([ohlc, vol, spread], axis=1).dropna().reset_index()

        filepath = os.path.join(output_dir, f"{symbol}_{tf}_dukascopy.parquet")
        resampled.to_parquet(filepath, index=False, compression="zstd")
        results[tf] = filepath
        logger.info(f"Resampled {tf}: {len(resampled):,} bars -> {filepath}")

    return results


def run_dukascopy_download(config_path: str = "config/settings.json"):
    """Entry point: download configured symbols from Dukascopy."""
    with open(config_path) as f:
        config = json.load(f)

    symbols = [s for s in config["symbols"] if s["name"] in PIPET_SCALES]
    timeframes = config["timeframes"]
    raw_dir = config["data"]["raw_dir"]
    external_dir = os.path.join(os.path.dirname(raw_dir), "external")

    # Default: download last 15 years
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * 15)

    for sym_cfg in symbols:
        symbol = sym_cfg["name"]
        m1_path = download_symbol_range(symbol, start, end, output_dir=external_dir, max_workers=6)
        if m1_path:
            resample_to_timeframes(m1_path, symbol, timeframes, output_dir=external_dir)


if __name__ == "__main__":
    run_dukascopy_download()
