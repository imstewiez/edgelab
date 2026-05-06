"""
Batch Dukascopy downloader that works around tick-vault's SQLite limits
by downloading in yearly chunks and combining results.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List

try:
    from dukascopy_downloader import download_symbol_range, resample_to_timeframes
    from logger import setup_logger
except ModuleNotFoundError:
    from src.dukascopy_downloader import download_symbol_range, resample_to_timeframes
    from src.logger import setup_logger

logger = setup_logger("batch_dukascopy")


def download_yearly_batches(
    symbol: str,
    years: int = 10,
    timeframes: List[str] = None,
    output_dir: str = "data/external"
) -> dict:
    """
    Download Dukascopy data in 1-year batches to avoid memory/DB limits,
    then combine into final Parquet files.
    """
    if timeframes is None:
        timeframes = ["M1", "M5", "M15", "H1", "H4", "D1"]
    
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * years)
    
    # Process year by year
    current = start
    all_m1_files = []
    batch_num = 0
    
    while current < end:
        batch_end = min(current + timedelta(days=365), end)
        logger.info(f"Batch {batch_num}: {symbol} {current.date()} to {batch_end.date()}")
        
        batch_file = os.path.join(output_dir, f"{symbol}_M1_batch_{batch_num}.parquet")
        
        # Check if this batch already exists (resume support)
        if os.path.exists(batch_file):
            logger.info(f"Batch file exists, skipping: {batch_file}")
            all_m1_files.append(batch_file)
            current = batch_end
            batch_num += 1
            continue
        
        result = download_symbol_range(
            symbol,
            current,
            batch_end,
            output_dir=output_dir,
            max_workers=6
        )
        
        if result:
            # Rename to batch file so we can resume later
            os.rename(result, batch_file)
            all_m1_files.append(batch_file)
        else:
            logger.warning(f"No data for batch {batch_num}")
        
        current = batch_end
        batch_num += 1
    
    if not all_m1_files:
        logger.error(f"No M1 data downloaded for {symbol}")
        return {}
    
    # Combine all batch M1 files
    logger.info(f"Combining {len(all_m1_files)} batch files for {symbol} M1...")
    import pandas as pd
    m1_dfs = [pd.read_parquet(f) for f in all_m1_files]
    combined_m1 = pd.concat(m1_dfs, ignore_index=True)
    combined_m1 = combined_m1.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    
    final_m1 = os.path.join(output_dir, f"{symbol}_M1_dukascopy.parquet")
    combined_m1.to_parquet(final_m1, index=False, compression="zstd")
    logger.info(f"Final M1: {len(combined_m1):,} bars -> {final_m1}")
    
    # Resample to higher timeframes from combined M1
    results = {"M1": final_m1}
    tf_resampled = resample_to_timeframes(final_m1, symbol, timeframes, output_dir)
    results.update(tf_resampled)
    
    # Cleanup batch files to save space
    for f in all_m1_files:
        if os.path.exists(f):
            os.remove(f)
            logger.info(f"Cleaned up batch file: {f}")
    
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--output-dir", default="data/external")
    args = parser.parse_args()
    
    download_yearly_batches(args.symbol, args.years, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
