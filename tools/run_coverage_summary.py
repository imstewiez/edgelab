from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "data" / "outputs"


def latest_run() -> Path | None:
    if not OUTPUTS.exists():
        return None
    runs = sorted([p for p in OUTPUTS.iterdir() if p.is_dir()], reverse=True)
    return runs[0] if runs else None


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path).replace([float("inf"), float("-inf")], pd.NA).fillna("")


def grouped(df: pd.DataFrame, cols: list[str], limit=50):
    if df.empty or not set(cols).issubset(df.columns):
        return []
    g = df.groupby(cols).size().reset_index(name="count").sort_values("count", ascending=False)
    return g.head(limit).to_dict("records")


def summarize(run_dir: Path) -> dict:
    all_edges = read_csv(run_dir / "all_edges.csv")
    candidates = read_csv(run_dir / "candidate_edges.csv")
    datasets = read_csv(run_dir / "datasets_scanned.csv")
    return {
        "run": run_dir.name,
        "datasets_scanned": int(len(datasets)),
        "edges_tested": int(len(all_edges)),
        "candidates": int(len(candidates)),
        "dataset_coverage": datasets[[c for c in ["symbol", "tf", "rows", "source_rows", "start", "end"] if c in datasets.columns]].to_dict("records") if not datasets.empty else [],
        "all_edges_by_symbol": grouped(all_edges, ["symbol"]),
        "all_edges_by_tf": grouped(all_edges, ["tf"]),
        "all_edges_by_concept": grouped(all_edges, ["concept"]),
        "all_edges_by_symbol_tf": grouped(all_edges, ["symbol", "tf"]),
        "candidates_by_symbol": grouped(candidates, ["symbol"]),
        "candidates_by_tf": grouped(candidates, ["tf"]),
        "candidates_by_concept": grouped(candidates, ["concept"]),
        "candidates_by_symbol_tf": grouped(candidates, ["symbol", "tf"]),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Summarize what a discovery run actually tested and shortlisted.")
    p.add_argument("--run", default="", help="Run folder name under data/outputs. Defaults to latest.")
    args = p.parse_args()
    run_dir = OUTPUTS / args.run if args.run else latest_run()
    if not run_dir or not run_dir.exists():
        print("No output run found.")
        return 1
    report = summarize(run_dir)
    out_path = run_dir / "COVERAGE_SUMMARY.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "run": report["run"],
        "datasets_scanned": report["datasets_scanned"],
        "edges_tested": report["edges_tested"],
        "candidates": report["candidates"],
        "candidates_by_symbol": report["candidates_by_symbol"],
        "all_edges_by_symbol": report["all_edges_by_symbol"],
        "candidates_by_concept": report["candidates_by_concept"],
        "coverage_path": str(out_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
