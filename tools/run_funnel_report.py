from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "data" / "outputs"

STAGES = [
    ("discovery_candidates", "candidate_edges.csv", None, None),
    ("validation", "stage2_validation.csv", "robustness_status", ["robust_candidate", "watchlist"]),
    ("walkforward", "stage3_walkforward.csv", "wf_status", ["wf_pass", "wf_watchlist"]),
    ("stress", "stage4_execution_stress.csv", "stress_status", ["stress_pass", "stress_watchlist"]),
    ("monte_carlo", "stage5_monte_carlo.csv", "mc_status", ["mc_pass", "mc_watchlist"]),
    ("sensitivity", "stage6_sensitivity.csv", "sensitivity_status", ["sensitivity_pass", "sensitivity_watchlist"]),
    ("portfolio", "stage7_portfolio_risk.csv", "portfolio_status", ["portfolio_pass", "portfolio_watchlist"]),
    ("permutation", "stage8_permutation_test.csv", "permutation_status", ["perm_pass", "perm_watchlist", "permutation_pass", "permutation_watchlist"]),
]

SCORE_COLS = [
    "permutation_score", "portfolio_score", "sensitivity_score", "mc_score", "wf_score", "robustness_score", "score",
]


def latest_run() -> Path | None:
    if not OUTPUTS.exists():
        return None
    runs = [p for p in OUTPUTS.iterdir() if p.is_dir() and (p / "all_edges.csv").exists()]
    return max(runs, key=lambda p: (p / "all_edges.csv").stat().st_mtime) if runs else None


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path).replace([float("inf"), float("-inf")], pd.NA).fillna("")


def pass_filter(df: pd.DataFrame, status_col: str | None, pass_values: list[str] | None) -> pd.DataFrame:
    if df.empty or not status_col or status_col not in df.columns or not pass_values:
        return df
    values = "|".join(pass_values)
    return df[df[status_col].astype(str).str.contains(values, case=False, regex=True)].copy()


def grouped(df: pd.DataFrame, cols: list[str], limit=20):
    if df.empty or not set(cols).issubset(df.columns):
        return []
    return df.groupby(cols).size().reset_index(name="count").sort_values("count", ascending=False).head(limit).to_dict("records")


def best_rows(df: pd.DataFrame, limit=20):
    if df.empty:
        return []
    out = df.copy()
    score_col = next((c for c in SCORE_COLS if c in out.columns), None)
    if score_col:
        out["_rank_score"] = pd.to_numeric(out[score_col], errors="coerce").fillna(0)
        out = out.sort_values("_rank_score", ascending=False)
    cols = [c for c in [
        "setup_id", "symbol", "tf", "concept", "session", "lookback", "rr", "sl_mult",
        "pf", "test_pf", "expR", "maxDD_R", "score", "robustness_score", "wf_score", "stress_pass_rate",
        "mc_score", "profit_probability", "sensitivity_score", "portfolio_score", "permutation_score",
        "real_sumR", "sumR_percentile", "verdict", "wf_verdict",
    ] if c in out.columns]
    return out[cols].head(limit).to_dict("records")


def summarize(run_dir: Path) -> dict:
    report = {"run": run_dir.name, "stage_counts": [], "by_symbol": {}, "by_concept": {}, "top_current_stage": []}
    last_passed = pd.DataFrame()
    for name, fn, status_col, pass_values in STAGES:
        raw = read_csv(run_dir / fn)
        passed = pass_filter(raw, status_col, pass_values)
        if not passed.empty:
            last_passed = passed
        report["stage_counts"].append({
            "stage": name,
            "file": fn,
            "rows": int(len(raw)),
            "passing_or_watchlist": int(len(passed)),
            "status_col": status_col or "",
        })
        report["by_symbol"][name] = grouped(passed if status_col else raw, ["symbol"])
        report["by_concept"][name] = grouped(passed if status_col else raw, ["concept"])
    report["top_current_stage"] = best_rows(last_passed, 30)
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="One-command EdgeLab stage funnel report for an output run.")
    p.add_argument("--run", default="", help="Run folder under data/outputs. Defaults to latest all_edges run by modified time.")
    args = p.parse_args()
    run_dir = OUTPUTS / args.run if args.run else latest_run()
    if not run_dir or not run_dir.exists():
        print("No valid output run found.")
        return 1
    report = summarize(run_dir)
    out_path = run_dir / "FUNNEL_REPORT.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "run": report["run"],
        "stage_counts": report["stage_counts"],
        "latest_stage_top": report["top_current_stage"][:10],
        "funnel_path": str(out_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
