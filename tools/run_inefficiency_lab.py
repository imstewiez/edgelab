from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "apps" / "engine"
sys.path.insert(0, str(ENGINE))

from inefficiency_lab import run_inefficiency_lab  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OHLC price-action/liquidity inefficiency profiler.")
    parser.add_argument("--scan-name", default=None, help="Output folder name under data/outputs.")
    parser.add_argument("--mode", default="balanced", choices=["balanced", "deep"], help="Profiler scope.")
    args = parser.parse_args()
    summary = run_inefficiency_lab(scan_name=args.scan_name, mode=args.mode, logger=print)
    print(json.dumps({
        "scan_name": summary.get("scan_name"),
        "datasets_profiled": summary.get("datasets_profiled"),
        "patterns_profiled": summary.get("patterns_profiled"),
        "strong_inefficiencies": summary.get("strong_inefficiencies"),
        "watchlist_inefficiencies": summary.get("watchlist_inefficiencies"),
        "top": summary.get("top", [])[:10],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
