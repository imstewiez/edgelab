from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from quantlab_core import OUTPUTS_DIR, HORIZON, backtest, feature_path, filter_by_setup_keys, row_setup_id, session_mask, signals, st

SENSITIVITY_PATH = OUTPUTS_DIR / "latest_sensitivity.json"


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


def _candidate_source(run_dir: Path) -> pd.DataFrame:
    cand = run_dir / "candidate_edges.csv"
    if not cand.exists():
        raise RuntimeError("No candidate_edges.csv found. Run Discover first.")
    source = pd.read_csv(cand).replace([np.inf, -np.inf], np.nan).fillna("")
    for file_name, status_col, allowed in [
        ("stage5_monte_carlo.csv", "mc_status", {"mc_pass", "mc_watchlist"}),
        ("stage4_execution_stress.csv", "stress_status", {"stress_pass", "stress_watchlist"}),
        ("stage3_walkforward.csv", "wf_status", {"wf_pass", "wf_watchlist"}),
        ("stage2_validation.csv", "robustness_status", {"robust_candidate", "watchlist"}),
    ]:
        p = run_dir / file_name
        if not p.exists():
            continue
        gate = pd.read_csv(p).replace([np.inf, -np.inf], np.nan).fillna("")
        if status_col in gate.columns:
            gate = gate[gate[status_col].isin(allowed)]
        filtered = filter_by_setup_keys(source, gate)
        if len(filtered):
            return filtered.head(70)
    return source.head(70)


def _variants(row: dict):
    lb = int(_num(row.get("lookback"), 20))
    rr = _num(row.get("rr"), 1.0)
    sl = _num(row.get("sl_mult"), 1.0)
    for lookback in sorted({max(5, int(lb * 0.65)), max(5, lb - 8), lb, lb + 8, int(lb * 1.35)}):
        for risk_reward in sorted({round(max(0.6, rr - 0.4), 2), round(rr, 2), round(rr + 0.4, 2)}):
            for stop_mult in sorted({round(max(0.5, sl - 0.4), 2), round(sl, 2), round(sl + 0.4, 2)}):
                yield lookback, risk_reward, stop_mult


def _test_row(row: dict):
    symbol = str(row.get("symbol"))
    tf = str(row.get("tf"))
    concept = str(row.get("concept"))
    session = str(row.get("session", "all"))
    fp = feature_path(symbol, tf)
    if not fp.exists():
        return None
    df = pd.read_pickle(fp)
    mask = session_mask(df, session)
    rows = []
    for lookback, rr, sl_mult in _variants(row):
        buy, sell = signals(df, concept, lookback)
        trades = backtest(df, buy & mask, sell & mask, rr, sl_mult, HORIZON.get(tf, 48), symbol=symbol)
        stats = st(trades)
        if not stats:
            continue
        passed = stats["n"] >= 25 and stats["pf"] >= 1.12 and stats["expR"] > 0 and stats["maxDD_R"] <= 18
        rows.append({"lookback": lookback, "rr": rr, "sl_mult": sl_mult, "trades": stats["n"], "pf": stats["pf"], "expR": stats["expR"], "maxDD_R": stats["maxDD_R"], "passed": passed})
    if not rows:
        return None
    variants = pd.DataFrame(rows)
    pass_rate = float(variants.passed.mean())
    median_pf = float(variants.pf.median())
    min_pf = float(variants.pf.min())
    median_exp = float(variants.expR.median())
    max_dd = float(variants.maxDD_R.max())
    score = 0
    reasons = []
    if pass_rate >= 0.55:
        score += 35
    elif pass_rate >= 0.35:
        score += 18
    else:
        reasons.append("parameter area is too narrow")
    if median_pf >= 1.25:
        score += 25
    elif median_pf >= 1.12:
        score += 12
    else:
        reasons.append("median PF is weak")
    if min_pf >= 0.95:
        score += 15
    else:
        reasons.append("nearby settings weaken")
    if median_exp > 0:
        score += 15
    else:
        reasons.append("median expectancy is not positive")
    if max_dd <= 16:
        score += 10
    else:
        reasons.append("drawdown expands")
    status = "sensitivity_pass" if score >= 75 and pass_rate >= 0.45 else ("sensitivity_watchlist" if score >= 50 else "sensitivity_fail")
    return {"setup_id": row.get("setup_id") or row_setup_id(row), "symbol": symbol, "tf": tf, "concept": concept, "session": session, "base_lookback": row.get("lookback", ""), "lookback": row.get("lookback", ""), "base_rr": row.get("rr", ""), "rr": row.get("rr", ""), "base_sl_mult": row.get("sl_mult", ""), "sl_mult": row.get("sl_mult", ""), "variants_tested": int(len(variants)), "variants_passed": int(variants.passed.sum()), "pass_rate": round(pass_rate, 3), "median_pf": round(median_pf, 3), "min_pf": round(min_pf, 3), "median_expR": round(median_exp, 4), "maxDD_R": round(max_dd, 3), "sensitivity_score": int(score), "sensitivity_status": status, "verdict": "; ".join(reasons) if reasons else "Stable across nearby parameters", "ea_ready": False}


def run_sensitivity(scan_name: str | None = None, logger: Callable[[str], None] = print):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = OUTPUTS_DIR / scan_name if scan_name else _latest_output_dir()
    if not run_dir or not run_dir.exists():
        raise RuntimeError("No discovery run found. Run Discover first.")
    candidates = _candidate_source(run_dir)
    logger(f"Parameter-sensitivity testing {len(candidates)} candidates from {run_dir.name}")
    rows = []
    for i, row in enumerate(candidates.to_dict("records"), 1):
        logger(f"[{i}/{len(candidates)}] Sensitivity {row.get('symbol','')} {row.get('tf','')} {row.get('concept','')}")
        result = _test_row(row)
        if result:
            rows.append(result)
    df = pd.DataFrame(rows).sort_values("sensitivity_score", ascending=False) if rows else pd.DataFrame()
    df.to_csv(run_dir / "stage6_sensitivity.csv", index=False)
    summary = {"scan_name": run_dir.name, "validated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "candidates_checked": int(len(df)), "sensitivity_pass": int((df.sensitivity_status == "sensitivity_pass").sum()) if not df.empty else 0, "sensitivity_watchlist": int((df.sensitivity_status == "sensitivity_watchlist").sum()) if not df.empty else 0, "sensitivity_fail": int((df.sensitivity_status == "sensitivity_fail").sum()) if not df.empty else 0, "ea_ready": 0, "stage": "Stage 6 parameter sensitivity", "warning": "A single winning parameter is not enough. This gate checks whether nearby parameters still work using exact setup_id handoffs.", "top": df.head(25).to_dict("records") if not df.empty else []}
    (run_dir / "SENSITIVITY_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    SENSITIVITY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def read_sensitivity(scan_name: str | None = None):
    if scan_name:
        p = OUTPUTS_DIR / scan_name / "SENSITIVITY_SUMMARY.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    if SENSITIVITY_PATH.exists():
        return json.loads(SENSITIVITY_PATH.read_text(encoding="utf-8"))
    return {"candidates_checked": 0, "sensitivity_pass": 0, "sensitivity_watchlist": 0, "sensitivity_fail": 0, "ea_ready": 0, "top": [], "warning": "No sensitivity run yet."}
