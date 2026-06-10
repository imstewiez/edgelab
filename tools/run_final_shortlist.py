from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "data" / "outputs"

STAGE_FILES = [
    "candidate_edges.csv",
    "stage2_validation.csv",
    "stage3_walkforward.csv",
    "stage4_execution_stress.csv",
    "stage5_monte_carlo.csv",
    "stage6_sensitivity.csv",
    "stage7_portfolio_risk.csv",
    "stage8_permutation_test.csv",
]

STATUS_PASS = {
    "robustness_status": ("robust_candidate", "watchlist"),
    "wf_status": ("wf_pass", "wf_watchlist"),
    "stress_status": ("stress_pass", "stress_watchlist"),
    "mc_status": ("mc_pass", "mc_watchlist"),
    "sensitivity_status": ("sensitivity_pass", "sensitivity_watchlist"),
    "portfolio_status": ("portfolio_pass", "portfolio_watchlist"),
    "permutation_status": ("perm_pass", "perm_watchlist", "permutation_pass", "permutation_watchlist"),
}

BASE_COLS = ["setup_id", "symbol", "tf", "concept", "session", "lookback", "rr", "sl_mult"]
DISPLAY_COLS = BASE_COLS + [
    "final_rank_score", "gates_passed", "real_sumR", "sumR_percentile", "permutation_score",
    "pf", "test_pf", "expR", "maxDD_R", "n", "profit_probability", "p95_dd_R",
    "wf_score", "wf_pass_rate", "stress_pass_rate", "portfolio_score", "avg_abs_corr",
    "verdict", "paper_reason",
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


def numeric(s: pd.Series, default=0.0) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(default)


def merge_stage_data(run_dir: Path) -> pd.DataFrame:
    merged = pd.DataFrame()
    for fn in STAGE_FILES:
        df = read_csv(run_dir / fn)
        if df.empty or "setup_id" not in df.columns:
            continue
        df = df.drop_duplicates("setup_id", keep="first")
        if merged.empty:
            merged = df.copy()
        else:
            new_cols = [c for c in df.columns if c == "setup_id" or c not in merged.columns]
            merged = merged.merge(df[new_cols], on="setup_id", how="left")
    return merged.replace([float("inf"), float("-inf")], pd.NA).fillna("")


def gate_pass_count(df: pd.DataFrame) -> pd.Series:
    total = pd.Series(0, index=df.index, dtype=int)
    for col, values in STATUS_PASS.items():
        if col not in df.columns:
            continue
        pat = "|".join(values)
        total += df[col].astype(str).str.contains(pat, case=False, regex=True).astype(int)
    return total


def rank(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["gates_passed"] = gate_pass_count(out)
    out["_perm"] = numeric(out.get("sumR_percentile", pd.Series(0, index=out.index))) * 100
    out["_perm_score"] = numeric(out.get("permutation_score", pd.Series(0, index=out.index)))
    out["_sumR"] = numeric(out.get("real_sumR", out.get("sumR", pd.Series(0, index=out.index))))
    out["_pf"] = numeric(out.get("pf", pd.Series(0, index=out.index)))
    out["_test_pf"] = numeric(out.get("test_pf", pd.Series(0, index=out.index)))
    out["_dd"] = numeric(out.get("maxDD_R", pd.Series(99, index=out.index)), default=99)
    out["_mc_profit"] = numeric(out.get("profit_probability", pd.Series(0, index=out.index))) * 100
    out["_wf"] = numeric(out.get("wf_score", pd.Series(0, index=out.index)))
    out["_portfolio"] = numeric(out.get("portfolio_score", pd.Series(0, index=out.index)))
    out["final_rank_score"] = (
        out["gates_passed"] * 18
        + out["_perm"] * 0.55
        + out["_perm_score"] * 0.35
        + out["_mc_profit"] * 0.12
        + out["_wf"] * 0.18
        + out["_portfolio"] * 0.18
        + out["_sumR"].clip(lower=-20, upper=80) * 0.55
        + out["_pf"].clip(lower=0, upper=3) * 8
        + out["_test_pf"].clip(lower=0, upper=3) * 5
        - out["_dd"].clip(lower=0, upper=30) * 1.5
    ).round(3)
    reasons = []
    for _, r in out.iterrows():
        bits = []
        if int(r.get("gates_passed", 0)) >= 6: bits.append("survived most validation gates")
        if float(r.get("_perm", 0)) >= 95: bits.append("event timing beats random timing")
        if float(r.get("_pf", 0)) >= 1.5: bits.append("PF above 1.5")
        if float(r.get("_dd", 99)) <= 8: bits.append("controlled discovery DD")
        if str(r.get("symbol", "")) != "XAUUSD": bits.append("non-XAUUSD diversification")
        reasons.append("; ".join(bits) or "needs manual review")
    out["paper_reason"] = reasons
    return out.sort_values("final_rank_score", ascending=False)


def diversified(df: pd.DataFrame, limit: int, max_per_symbol: int, max_per_family: int) -> pd.DataFrame:
    picks = []
    sym_counts: dict[str, int] = {}
    fam_counts: dict[str, int] = {}
    seen_setup = set()
    for _, r in df.iterrows():
        sid = str(r.get("setup_id", ""))
        sym = str(r.get("symbol", ""))
        fam = "|".join(str(r.get(c, "")) for c in ["symbol", "tf", "concept", "session"])
        if sid in seen_setup:
            continue
        if sym_counts.get(sym, 0) >= max_per_symbol:
            continue
        if fam_counts.get(fam, 0) >= max_per_family:
            continue
        picks.append(r)
        seen_setup.add(sid)
        sym_counts[sym] = sym_counts.get(sym, 0) + 1
        fam_counts[fam] = fam_counts.get(fam, 0) + 1
        if len(picks) >= limit:
            break
    return pd.DataFrame(picks)


def main() -> int:
    p = argparse.ArgumentParser(description="Reduce a large EdgeLab run into a diversified paper-forward shortlist.")
    p.add_argument("--run", default="", help="Run folder under data/outputs. Defaults to latest all_edges run by modified time.")
    p.add_argument("--limit", type=int, default=20, help="Number of setups to keep.")
    p.add_argument("--max-per-symbol", type=int, default=4, help="Maximum setups per symbol.")
    p.add_argument("--max-per-family", type=int, default=2, help="Maximum setups per symbol/tf/concept/session family.")
    p.add_argument("--min-gates", type=int, default=5, help="Minimum validation gates passed/watchlisted.")
    args = p.parse_args()

    run_dir = OUTPUTS / args.run if args.run else latest_run()
    if not run_dir or not run_dir.exists():
        print("No valid output run found.")
        return 1

    merged = merge_stage_data(run_dir)
    if merged.empty:
        print("No stage data found for run.")
        return 1
    ranked = rank(merged)
    filtered = ranked[ranked["gates_passed"] >= args.min_gates].copy()
    short = diversified(filtered, limit=args.limit, max_per_symbol=args.max_per_symbol, max_per_family=args.max_per_family)
    cols = [c for c in DISPLAY_COLS if c in short.columns]
    out_csv = run_dir / "FINAL_SHORTLIST.csv"
    out_json = run_dir / "FINAL_SHORTLIST.json"
    short[cols].to_csv(out_csv, index=False)
    out_json.write_text(json.dumps(short[cols].to_dict("records"), indent=2), encoding="utf-8")

    print(json.dumps({
        "run": run_dir.name,
        "input_setups": int(len(merged)),
        "eligible_min_gates": int(len(filtered)),
        "selected": int(len(short)),
        "by_symbol": short.groupby("symbol").size().reset_index(name="count").to_dict("records") if not short.empty and "symbol" in short.columns else [],
        "top": short[cols].head(args.limit).to_dict("records"),
        "csv": str(out_csv),
        "json": str(out_json),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
