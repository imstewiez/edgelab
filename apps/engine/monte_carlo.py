from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from pipeline_io import EDGE_COLUMNS, MC_COLUMNS, STRESS_COLUMNS, VALIDATION_COLUMNS, WF_COLUMNS, safe_read_csv, safe_to_csv
from quantlab_core import OUTPUTS_DIR, HORIZON, backtest, feature_path, filter_by_setup_keys, row_setup_id, session_mask, signals

MONTE_CARLO_PATH = OUTPUTS_DIR / "latest_monte_carlo.json"


def _latest_output_dir() -> Path | None:
    if not OUTPUTS_DIR.exists():
        return None
    runs = sorted([p for p in OUTPUTS_DIR.iterdir() if p.is_dir()], reverse=True)
    return runs[0] if runs else None


def _num(v, default=0.0):
    try:
        if v == "" or pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


def _max_drawdown(values: np.ndarray) -> float:
    if len(values) == 0:
        return 0.0
    eq = np.cumsum(values); peak = np.maximum.accumulate(eq)
    return float(np.max(peak - eq))


def _max_loss_streak(values: np.ndarray) -> int:
    cur = 0; worst = 0
    for x in values:
        if x <= 0:
            cur += 1; worst = max(worst, cur)
        else:
            cur = 0
    return int(worst)


def _simulate(R: np.ndarray, sims: int = 500, skip_prob: float = 0.03, slip_sigma: float = 0.035):
    rng = np.random.default_rng(42)
    totals, dds, streaks = [], [], []
    if len(R) == 0:
        return {"median_totalR": 0, "p05_totalR": 0, "p95_dd_R": 0, "p99_dd_R": 0, "p95_loss_streak": 0, "profit_probability": 0, "ruin_probability": 1}
    for _ in range(sims):
        sample = rng.choice(R, size=len(R), replace=True)
        sample = sample[rng.random(len(sample)) > skip_prob]
        if len(sample) == 0:
            sample = np.array([-1.0])
        stressed = sample + rng.normal(loc=-0.012, scale=slip_sigma, size=len(sample))
        totals.append(float(np.sum(stressed))); dds.append(_max_drawdown(stressed)); streaks.append(_max_loss_streak(stressed))
    totals = np.array(totals); dds = np.array(dds); streaks = np.array(streaks)
    return {"median_totalR": round(float(np.median(totals)), 3), "p05_totalR": round(float(np.percentile(totals, 5)), 3), "p95_dd_R": round(float(np.percentile(dds, 95)), 3), "p99_dd_R": round(float(np.percentile(dds, 99)), 3), "p95_loss_streak": int(np.percentile(streaks, 95)), "profit_probability": round(float((totals > 0).mean()), 3), "ruin_probability": round(float((dds > 20).mean()), 3)}


def _load_candidate_source(run_dir: Path) -> pd.DataFrame:
    source = safe_read_csv(run_dir / "candidate_edges.csv", EDGE_COLUMNS)
    if source.empty:
        return source
    for file_name, status_col, allowed, cols in [
        ("stage4_execution_stress.csv", "stress_status", {"stress_pass", "stress_watchlist"}, STRESS_COLUMNS),
        ("stage3_walkforward.csv", "wf_status", {"wf_pass", "wf_watchlist"}, WF_COLUMNS),
        ("stage2_validation.csv", "robustness_status", {"robust_candidate", "watchlist"}, VALIDATION_COLUMNS),
    ]:
        p = run_dir / file_name
        if not p.exists():
            continue
        gate = safe_read_csv(p, cols)
        if gate.empty:
            continue
        if status_col in gate.columns:
            gate = gate[gate[status_col].isin(allowed)]
        filtered = filter_by_setup_keys(source, gate)
        if len(filtered):
            return filtered.head(80)
    return source.head(80)


def _row_monte_carlo(row: dict):
    symbol = str(row.get("symbol")); tf = str(row.get("tf")); concept = str(row.get("concept")); lookback = int(_num(row.get("lookback"), 20)); session = str(row.get("session", "all")); rr = _num(row.get("rr"), 1.0); sl_mult = _num(row.get("sl_mult"), 1.0); setup_id = row.get("setup_id") or row_setup_id(row)
    fp = feature_path(symbol, tf)
    if not fp.exists():
        return None
    df = pd.read_pickle(fp); b0, s0 = signals(df, concept, lookback); sm = session_mask(df, session)
    trades = backtest(df, b0 & sm, s0 & sm, rr, sl_mult, HORIZON.get(tf, 48), symbol=symbol)
    if trades.empty or len(trades) < 20:
        return None
    R = trades.R.astype(float).to_numpy(); mc = _simulate(R); score = 0; reasons = []
    if mc["profit_probability"] >= 0.80: score += 30
    else: reasons.append("profit probability too low")
    if mc["p05_totalR"] > 0: score += 25
    else: reasons.append("5th percentile total return is negative")
    if mc["p95_dd_R"] <= 12: score += 25
    elif mc["p95_dd_R"] <= 18: score += 12
    else: reasons.append("simulated drawdown too high")
    if mc["p95_loss_streak"] <= 8: score += 10
    else: reasons.append("loss-streak tail too high")
    if mc["ruin_probability"] <= 0.03: score += 10
    else: reasons.append("ruin probability too high")
    status = "mc_pass" if score >= 80 and not reasons else ("mc_watchlist" if score >= 55 else "mc_fail")
    return {"setup_id": setup_id, "symbol": symbol, "tf": tf, "concept": concept, "session": session, "lookback": lookback, "rr": rr, "sl_mult": sl_mult, "trades": int(len(R)), "avg_cost_R": round(float(trades.cost_r.mean()), 5) if "cost_r" in trades else 0, "mc_status": status, "mc_score": int(score), **mc, "verdict": "; ".join(reasons) if reasons else "Passed first Monte Carlo robustness gate", "ea_ready": False}


def run_monte_carlo(scan_name: str | None = None, logger: Callable[[str], None] = print):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = OUTPUTS_DIR / scan_name if scan_name else _latest_output_dir()
    if not run_dir or not run_dir.exists():
        raise RuntimeError("No discovery run found. Run Discover Edges first.")
    candidates = _load_candidate_source(run_dir)
    logger(f"Monte Carlo testing {len(candidates)} candidates from {run_dir.name}")
    rows = []
    for i, row in enumerate(candidates.to_dict("records"), 1):
        logger(f"[{i}/{len(candidates)}] MC {row.get('symbol','')} {row.get('tf','')} {row.get('concept','')}")
        out = _row_monte_carlo(row)
        if out:
            rows.append(out)
    df = pd.DataFrame(rows).sort_values("mc_score", ascending=False) if rows else pd.DataFrame(columns=MC_COLUMNS)
    df = safe_to_csv(df, run_dir / "stage5_monte_carlo.csv", MC_COLUMNS)
    summary = {"scan_name": run_dir.name, "validated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "candidates_checked": int(len(df)), "mc_pass": int((df.mc_status == "mc_pass").sum()) if not df.empty else 0, "mc_watchlist": int((df.mc_status == "mc_watchlist").sum()) if not df.empty else 0, "mc_fail": int((df.mc_status == "mc_fail").sum()) if not df.empty else 0, "ea_ready": 0, "stage": "Stage 5 Monte Carlo robustness", "warning": "Monte Carlo uses the exact setup_id trade R sequence from the current broker-aware OHLC backtest. It is a robustness gate, not live-proof.", "top": df.head(25).replace([np.inf, -np.inf], np.nan).fillna("").to_dict("records") if not df.empty else []}
    (run_dir / "MONTE_CARLO_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    MONTE_CARLO_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def read_monte_carlo(scan_name: str | None = None):
    if scan_name:
        p = OUTPUTS_DIR / scan_name / "MONTE_CARLO_SUMMARY.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    if MONTE_CARLO_PATH.exists():
        return json.loads(MONTE_CARLO_PATH.read_text(encoding="utf-8"))
    return {"candidates_checked": 0, "mc_pass": 0, "mc_watchlist": 0, "mc_fail": 0, "ea_ready": 0, "top": [], "warning": "No Monte Carlo run yet."}
