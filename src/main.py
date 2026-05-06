#!/usr/bin/env python3
"""
FX Trading Bot — Main entry point.

Workflow:
  1. Discover symbols:   python src/discover_symbols.py --search NAS
  2. Update config:      Edit config/settings.json with correct symbol names
  3. Ingest data:        python src/main.py --ingest
  4. Explore data:       (Coming next)
"""
import argparse
import sys

from data_ingestion import run_full_ingestion
from logger import setup_logger

logger = setup_logger("main")


def main():
    parser = argparse.ArgumentParser(description="FX Trading Bot")
    parser.add_argument("--ingest", action="store_true", help="Run full data ingestion from MT5")
    parser.add_argument("--config", default="config/settings.json", help="Path to config file")
    args = parser.parse_args()
    
    if args.ingest:
        logger.info("Starting data ingestion...")
        run_full_ingestion(args.config)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
