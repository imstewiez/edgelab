from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from pipeline_io import EDGE_COLUMNS, VALIDATION_COLUMNS, safe_read_csv, safe_to_csv
from quantlab_core import OUTPUTS_DIR, row_setup_id

VALIDATION_PATH = OUTPUTS_DIR / "latest_validation.json"


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


def _validate_row(row: dict) -> dict:
    n = int(_num(row.get("n"), 0))
    pf = _num(row.get("pf"), 0)
    test_pf = _num(row.get("test_pf"), 0)
    exp_r = _num(row.get("expR"), 0)
    dd = _num(row.get("maxDD_R"), 999)
    loss_streak = int(_num(row.get("max_loss_streak"), 999))
    positive_month_pct = _num(row.get("positive_month_pct"), 0)
    winrate = _num(row.get("winrate"), 0)

    reasons = []
    strengths = []
    score = 0

    if n >= 120:
        score += 20; strengths.append("good trade count")
    elif n >= 70:
        score += 12; strengths.append("acceptable trade count")
    else:
        reasons.append("trade count still low")

    if pf >= 1.6:
        score += 22; strengths.append("strong PF")
    elif pf >= 1.35:
        score += 14; strengths.append("acceptable PF")
    else:
        reasons.append("PF too close to noise")

    if test_pf >= 1.25:
        score += 22; strengths.append("good out-of-sample PF")
    elif test_pf >= 1.10:
        score += 12; strengths.append("acceptable out-of-sample PF")
    else:
        reasons.append("out-of-sample not strong enough")

    if exp_r >= 0.20:
        score += 14; strengths.append("healthy expectancy")
    elif exp_r >= 0.08:
        score += 7
    else:
        reasons.append("expectancy too small")

    if dd <= 6:
        score += 12; strengths.append("low R drawdown")
    elif dd <= 10:
        score += 7
    else:
        reasons.append("drawdown too high")

    if loss_streak <= 5:
        score += 8; strengths.append("manageable loss streak")
    elif loss_streak <= 8:
        score += 4
    else:
        reasons.append("loss streak too high")

    if positive_month_pct >= 0.60:
        score += 10; strengths.append("good monthly stability")
    elif positive_month_pct >= 0.52:
        score += 5
    else:
        reasons.append("monthly stability too weak")

    stress_pf = round(max(0, pf * 0.82), 3)
    stress_test_pf = round(max(0, test_pf * 0.78), 3)
    stress_exp_r = round(exp_r * 0.70, 4)
    stress_dd = round(dd * 1.35, 3)

    if stress_test_pf < 1.0:
        reasons.append("fails conservative stress PF")
    else:
        score += 5

    robustness = "robust_candidate" if score >= 70 and not any("out-of-sample" in r or "stress" in r for r in reasons) else ("watchlist" if score >= 50 else "not_robust")
    ea_ready = False
    ea_reason = "Not EA-ready yet: still needs true walk-forward, slippage/spread stress, Monte Carlo and forward paper tracking."

    return {
        "setup_id": row.get("setup_id") or row_setup_id(row),
        "symbol": row.get("symbol", ""), "tf": row.get("tf", ""), "concept": row.get("concept", ""),
        "lookback": row.get("lookback", ""), "session": row.get("session", ""), "rr": row.get("rr", ""), "sl_mult": row.get("sl_mult", ""),
        "grade": row.get("grade", ""), "trades": n, "n": n, "pf": pf, "test_pf": test_pf, "expR": exp_r,
        "maxDD_R": dd, "winrate": winrate, "positive_month_pct": positive_month_pct, "loss_streak": loss_streak,
        "max_loss_streak": loss_streak, "avg_cost_R": _num(row.get("avg_cost_R"), 0),
        "stress_pf": stress_pf, "stress_test_pf": stress_test_pf, "stress_expR": stress_exp_r, "stress_maxDD_R": stress_dd,
        "robustness_score": int(score), "robustness_status": robustness, "ea_ready": ea_ready,
        "verdict": "; ".join(reasons) if reasons else "Passed Stage 2 first-pass robustness gate",
        "strengths": "; ".join(strengths), "ea_reason": ea_reason,
    }


def run_validation(scan_name: str | None = None, logger: Callable[[str], None] = print):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = OUTPUTS_DIR / scan_name if scan_name else _latest_output_dir()
    if not run_dir or not run_dir.exists():
        raise RuntimeError("No discovery run found. Run Discover Edges first.")

    cand_path = run_dir / "candidate_edges.csv"
    candidates = safe_read_csv(cand_path, EDGE_COLUMNS)
    logger(f"Validating {len(candidates)} candidate edges from {run_dir.name}")

    rows = [_validate_row(r) for r in candidates.to_dict("records")]
    df = pd.DataFrame(rows).sort_values("robustness_score", ascending=False) if rows else pd.DataFrame(columns=VALIDATION_COLUMNS)
    robust = df[df.robustness_status == "robust_candidate"] if not df.empty else pd.DataFrame()
    watch = df[df.robustness_status == "watchlist"] if not df.empty else pd.DataFrame()
    not_robust = df[df.robustness_status == "not_robust"] if not df.empty else pd.DataFrame()

    df = safe_to_csv(df, run_dir / "stage2_validation.csv", VALIDATION_COLUMNS)

    summary = {
        "scan_name": run_dir.name,
        "validated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "candidates_checked": int(len(df)),
        "robust_candidates": int(len(robust)),
        "watchlist": int(len(watch)),
        "not_robust": int(len(not_robust)),
        "ea_ready": 0,
        "stage": "Stage 2 first-pass robustness gate",
        "warning": "EA-ready remains 0 until true walk-forward, slippage/spread stress, Monte Carlo and forward paper tracking pass.",
        "top": df.head(20).replace([np.inf, -np.inf], np.nan).fillna("").to_dict("records") if not df.empty else [],
    }

    (run_dir / "VALIDATION_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    VALIDATION_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def read_validation(scan_name: str | None = None):
    if scan_name:
        p = OUTPUTS_DIR / scan_name / "VALIDATION_SUMMARY.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    if VALIDATION_PATH.exists():
        return json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
    return {"candidates_checked": 0, "robust_candidates": 0, "watchlist": 0, "not_robust": 0, "ea_ready": 0, "top": [], "warning": "No validation run yet."}
