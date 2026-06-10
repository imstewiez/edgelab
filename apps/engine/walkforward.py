from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from pipeline_io import EDGE_COLUMNS, WF_COLUMNS, safe_read_csv, safe_to_csv
from quantlab_core import OUTPUTS_DIR, HORIZON, backtest, feature_path, row_setup_id, session_mask, signals, st
from stage_limits import limit_candidates

WALKFORWARD_PATH = OUTPUTS_DIR / "latest_walkforward.json"


def _latest_output_dir() -> Path | None:
    if not OUTPUTS_DIR.exists():
        return None
    runs = sorted([p for p in OUTPUTS_DIR.iterdir() if p.is_dir()], reverse=True)
    return runs[0] if runs else None


def _safe_float(v, default=0.0):
    try:
        if v == "" or pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


def _window_stats(df: pd.DataFrame, row: dict, windows: int = 5):
    symbol = str(row.get("symbol"))
    tf = str(row.get("tf"))
    concept = str(row.get("concept"))
    lookback = int(_safe_float(row.get("lookback"), 20))
    session = str(row.get("session", "all"))
    rr = _safe_float(row.get("rr"), 1.0)
    sl_mult = _safe_float(row.get("sl_mult"), 1.0)
    start = pd.to_datetime(df.time.min())
    end = pd.to_datetime(df.time.max())
    if start >= end:
        return []
    cuts = pd.date_range(start=start, end=end, periods=windows + 1)
    rows = []
    time_col = pd.to_datetime(df.time)
    for i in range(len(cuts) - 1):
        w0, w1 = cuts[i], cuts[i + 1]
        chunk = df[(time_col >= w0) & (time_col < w1)].copy()
        if len(chunk) < 400 and tf != "D1":
            continue
        if len(chunk) < 80 and tf == "D1":
            continue
        b0, s0 = signals(chunk, concept, lookback)
        sm = session_mask(chunk, session)
        trades = backtest(chunk, b0 & sm, s0 & sm, rr, sl_mult, HORIZON.get(tf, 48), symbol=symbol)
        base = st(trades)
        if not base:
            rows.append({"window": i + 1, "start": str(w0.date()), "end": str(w1.date()), "trades": 0, "pf": 0, "expR": 0, "maxDD_R": 0, "sumR": 0, "passed": False})
            continue
        rows.append({"window": i + 1, "start": str(w0.date()), "end": str(w1.date()), "trades": int(base["n"]), "pf": float(base["pf"]), "expR": float(base["expR"]), "maxDD_R": float(base["maxDD_R"]), "sumR": float(base["sumR"]), "avg_cost_R": round(float(trades.cost_r.mean()), 5) if "cost_r" in trades else 0, "passed": bool(base["n"] >= 8 and base["pf"] >= 1.0 and base["sumR"] > 0)})
    return rows


def _grade_walkforward(rows: list[dict]):
    if not rows:
        return {"wf_status": "no_windows", "wf_score": 0, "wf_verdict": "Not enough data for walk-forward windows"}
    pfs = [r["pf"] for r in rows if r["trades"] > 0]
    exp_rs = [r["expR"] for r in rows if r["trades"] > 0]
    dds = [r["maxDD_R"] for r in rows if r["trades"] > 0]
    passed_count = sum(1 for r in rows if r["passed"])
    active_windows = len([r for r in rows if r["trades"] > 0])
    pass_rate = passed_count / max(1, len(rows))
    active_rate = active_windows / max(1, len(rows))
    median_pf = float(np.median(pfs)) if pfs else 0
    min_pf = float(np.min(pfs)) if pfs else 0
    median_exp = float(np.median(exp_rs)) if exp_rs else 0
    max_dd = float(np.max(dds)) if dds else 999
    score = 0
    reasons = []
    if len(rows) >= 4: score += 15
    else: reasons.append("too few windows")
    if active_rate >= 0.75: score += 15
    else: reasons.append("too many inactive windows")
    if pass_rate >= 0.60: score += 25
    elif pass_rate >= 0.45: score += 12
    else: reasons.append("not enough profitable windows")
    if median_pf >= 1.25: score += 20
    elif median_pf >= 1.10: score += 10
    else: reasons.append("median window PF too low")
    if min_pf >= 0.90: score += 10
    else: reasons.append("one or more windows collapse")
    if median_exp > 0: score += 10
    else: reasons.append("median expectancy is not positive")
    if max_dd <= 10: score += 5
    else: reasons.append("walk-forward DD too high")
    status = "wf_pass" if score >= 75 and not reasons else ("wf_watchlist" if score >= 55 else "wf_fail")
    return {"wf_status": status, "wf_score": int(score), "wf_windows": len(rows), "wf_active_windows": active_windows, "wf_passed_windows": passed_count, "wf_pass_rate": round(pass_rate, 3), "wf_median_pf": round(median_pf, 3), "wf_min_pf": round(min_pf, 3), "wf_median_expR": round(median_exp, 4), "wf_maxDD_R": round(max_dd, 3), "wf_verdict": "; ".join(reasons) if reasons else "Passed first walk-forward gate"}


def run_walkforward(scan_name: str | None = None, logger: Callable[[str], None] = print):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = OUTPUTS_DIR / scan_name if scan_name else _latest_output_dir()
    if not run_dir or not run_dir.exists():
        raise RuntimeError("No discovery run found. Run Discover Edges first.")
    all_candidates = safe_read_csv(run_dir / "candidate_edges.csv", EDGE_COLUMNS)
    candidates = limit_candidates(all_candidates, "walkforward", logger)
    logger(f"Walk-forward validating {len(candidates)} ranked candidates from {run_dir.name} ({len(all_candidates)} discovered)")
    summary_rows = []
    details = {}
    for idx, row in enumerate(candidates.to_dict("records"), 1):
        symbol = str(row.get("symbol")); tf = str(row.get("tf")); concept = str(row.get("concept")); setup_id = row.get("setup_id") or row_setup_id(row)
        logger(f"[{idx}/{len(candidates)}] WF {symbol} {tf} {concept}")
        fp = feature_path(symbol, tf)
        if not fp.exists():
            continue
        rows = _window_stats(pd.read_pickle(fp), row, windows=5)
        base = {"setup_id": setup_id, "symbol": symbol, "tf": tf, "concept": concept, "lookback": row.get("lookback", ""), "session": row.get("session", ""), "rr": row.get("rr", ""), "sl_mult": row.get("sl_mult", ""), "n": row.get("n", ""), "pf": row.get("pf", ""), "test_pf": row.get("test_pf", ""), "expR": row.get("expR", ""), "maxDD_R": row.get("maxDD_R", ""), "positive_month_pct": row.get("positive_month_pct", ""), "avg_cost_R": row.get("avg_cost_R", "")}
        base.update(_grade_walkforward(rows)); summary_rows.append(base); details[setup_id] = rows
    out = pd.DataFrame(summary_rows).sort_values("wf_score", ascending=False) if summary_rows else pd.DataFrame(columns=WF_COLUMNS)
    out = safe_to_csv(out, run_dir / "stage3_walkforward.csv", WF_COLUMNS)
    summary = {"scan_name": run_dir.name, "validated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "candidates_discovered": int(len(all_candidates)), "candidates_checked": int(len(out)), "wf_pass": int((out.wf_status == "wf_pass").sum()) if not out.empty else 0, "wf_watchlist": int((out.wf_status == "wf_watchlist").sum()) if not out.empty else 0, "wf_fail": int((out.wf_status == "wf_fail").sum()) if not out.empty else 0, "ea_ready": 0, "stage": "Stage 3 ranked walk-forward matrix", "warning": "Walk-forward is gated to the best ranked candidates for speed. EA-ready remains 0 until execution stress, Monte Carlo and live-forward paper tracking pass.", "top": out.head(25).replace([np.inf, -np.inf], np.nan).fillna("").to_dict("records") if not out.empty else [], "details": details}
    (run_dir / "WALKFORWARD_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    WALKFORWARD_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def read_walkforward(scan_name: str | None = None):
    if scan_name:
        p = OUTPUTS_DIR / scan_name / "WALKFORWARD_SUMMARY.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    if WALKFORWARD_PATH.exists():
        return json.loads(WALKFORWARD_PATH.read_text(encoding="utf-8"))
    return {"candidates_checked": 0, "wf_pass": 0, "wf_watchlist": 0, "wf_fail": 0, "ea_ready": 0, "top": [], "warning": "No walk-forward run yet."}
