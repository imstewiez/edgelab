from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from quantlab_core import OUTPUTS_DIR

STRESS_PATH = OUTPUTS_DIR / "latest_execution_stress.json"

SCENARIOS = [
    {"name": "base", "pf_mult": 1.00, "exp_mult": 1.00, "dd_mult": 1.00, "note": "Original discovery result"},
    {"name": "spread_x2", "pf_mult": 0.92, "exp_mult": 0.86, "dd_mult": 1.08, "note": "Spread roughly doubled"},
    {"name": "spread_x3", "pf_mult": 0.84, "exp_mult": 0.74, "dd_mult": 1.18, "note": "Spread roughly tripled"},
    {"name": "slippage_light", "pf_mult": 0.90, "exp_mult": 0.82, "dd_mult": 1.12, "note": "Light adverse slippage"},
    {"name": "slippage_heavy", "pf_mult": 0.78, "exp_mult": 0.62, "dd_mult": 1.32, "note": "Heavy adverse slippage"},
    {"name": "entry_delay", "pf_mult": 0.88, "exp_mult": 0.78, "dd_mult": 1.15, "note": "Entry delayed / missed ideal fill"},
    {"name": "combined_bad_fill", "pf_mult": 0.70, "exp_mult": 0.52, "dd_mult": 1.55, "note": "Worse spread + slippage + delayed fill"},
]


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


def _stress_row(row: dict) -> dict:
    pf = _num(row.get("pf"), 0)
    test_pf = _num(row.get("test_pf"), pf)
    exp_r = _num(row.get("expR"), 0)
    dd = _num(row.get("maxDD_R"), 999)
    trades = int(_num(row.get("n"), row.get("trades", 0)))

    scenario_rows = []
    failures = []
    pass_count = 0

    for s in SCENARIOS:
        spf = round(pf * s["pf_mult"], 3)
        stpf = round(test_pf * s["pf_mult"], 3)
        sexp = round(exp_r * s["exp_mult"], 4)
        sdd = round(dd * s["dd_mult"], 3)
        passed = spf >= 1.10 and stpf >= 1.00 and sexp > 0 and sdd <= 18
        if passed:
            pass_count += 1
        else:
            failures.append(s["name"])
        scenario_rows.append({
            "scenario": s["name"],
            "pf": spf,
            "test_pf": stpf,
            "expR": sexp,
            "maxDD_R": sdd,
            "passed": passed,
            "note": s["note"],
        })

    pass_rate = pass_count / len(SCENARIOS)
    worst = min(scenario_rows, key=lambda x: x["test_pf"])
    worst_dd = max(x["maxDD_R"] for x in scenario_rows)

    if pass_rate >= 0.86 and worst["test_pf"] >= 1.05:
        status = "stress_pass"
    elif pass_rate >= 0.58:
        status = "stress_watchlist"
    else:
        status = "stress_fail"

    verdict = "Survives first execution stress gate" if status == "stress_pass" else f"Fails or weak under: {', '.join(failures[:4])}"

    return {
        "symbol": row.get("symbol", ""),
        "tf": row.get("tf", ""),
        "concept": row.get("concept", ""),
        "session": row.get("session", ""),
        "rr": row.get("rr", ""),
        "sl_mult": row.get("sl_mult", ""),
        "trades": trades,
        "base_pf": pf,
        "base_test_pf": test_pf,
        "base_expR": exp_r,
        "base_maxDD_R": dd,
        "stress_status": status,
        "stress_pass_rate": round(pass_rate, 3),
        "stress_passed_scenarios": pass_count,
        "stress_total_scenarios": len(SCENARIOS),
        "worst_test_pf": worst["test_pf"],
        "worst_maxDD_R": worst_dd,
        "verdict": verdict,
        "scenarios": scenario_rows,
        "ea_ready": False,
        "ea_reason": "Not EA-ready yet: needs Monte Carlo, portfolio heat and forward paper tracking after execution stress.",
    }


def run_execution_stress(scan_name: str | None = None, logger: Callable[[str], None] = print):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = OUTPUTS_DIR / scan_name if scan_name else _latest_output_dir()
    if not run_dir or not run_dir.exists():
        raise RuntimeError("No discovery run found. Run Discover Edges first.")

    source = run_dir / "stage3_walkforward.csv"
    if not source.exists():
        source = run_dir / "stage2_validation.csv"
    if not source.exists():
        source = run_dir / "candidate_edges.csv"
    if not source.exists():
        raise RuntimeError("No candidates found. Run Discover Edges first.")

    df = pd.read_csv(source).replace([np.inf, -np.inf], np.nan).fillna("")
    if "wf_status" in df.columns:
        preferred = df[df.wf_status.isin(["wf_pass", "wf_watchlist"])]
        if len(preferred):
            df = preferred
    elif "robustness_status" in df.columns:
        preferred = df[df.robustness_status.isin(["robust_candidate", "watchlist"])]
        if len(preferred):
            df = preferred

    df = df.head(100)
    logger(f"Execution-stress testing {len(df)} candidates from {run_dir.name}")

    rows = []
    for i, row in enumerate(df.to_dict("records"), 1):
        logger(f"[{i}/{len(df)}] Stress {row.get('symbol','')} {row.get('tf','')} {row.get('concept','')}")
        rows.append(_stress_row(row))

    summary_df = pd.DataFrame([{k: v for k, v in r.items() if k != "scenarios"} for r in rows])
    if not summary_df.empty:
        summary_df = summary_df.sort_values(["stress_status", "stress_pass_rate", "worst_test_pf"], ascending=[True, False, False])
    summary_df.to_csv(run_dir / "stage4_execution_stress.csv", index=False)

    passed = int((summary_df.stress_status == "stress_pass").sum()) if not summary_df.empty else 0
    watch = int((summary_df.stress_status == "stress_watchlist").sum()) if not summary_df.empty else 0
    failed = int((summary_df.stress_status == "stress_fail").sum()) if not summary_df.empty else 0

    summary = {
        "scan_name": run_dir.name,
        "validated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "candidates_checked": int(len(summary_df)),
        "stress_pass": passed,
        "stress_watchlist": watch,
        "stress_fail": failed,
        "ea_ready": 0,
        "stage": "Stage 4 execution stress",
        "warning": "This uses conservative scenario approximations from available backtest stats. True broker-level realism needs tick/spread history and live-forward tracking.",
        "top": summary_df.head(25).to_dict("records") if not summary_df.empty else [],
        "details": rows,
        "scenarios": SCENARIOS,
    }

    (run_dir / "EXECUTION_STRESS_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    STRESS_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def read_execution_stress(scan_name: str | None = None):
    if scan_name:
        p = OUTPUTS_DIR / scan_name / "EXECUTION_STRESS_SUMMARY.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    if STRESS_PATH.exists():
        return json.loads(STRESS_PATH.read_text(encoding="utf-8"))
    return {
        "candidates_checked": 0,
        "stress_pass": 0,
        "stress_watchlist": 0,
        "stress_fail": 0,
        "ea_ready": 0,
        "top": [],
        "warning": "No execution stress run yet.",
    }
