from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from pipeline_io import EDGE_COLUMNS, STRESS_COLUMNS, VALIDATION_COLUMNS, WF_COLUMNS, safe_read_csv, safe_to_csv
from quantlab_core import OUTPUTS_DIR, HORIZON, backtest, feature_path, row_setup_id, session_mask, signals, st
from stage_limits import limit_candidates

STRESS_PATH = OUTPUTS_DIR / "latest_execution_stress.json"

SCENARIOS = [
    {"name": "base", "spread_mult": 1.00, "slippage_mult": 1.00, "entry_delay": 0, "note": "Broker/profile cost model using available spread data"},
    {"name": "spread_x2", "spread_mult": 2.00, "slippage_mult": 1.00, "entry_delay": 0, "note": "Spread doubled"},
    {"name": "spread_x3", "spread_mult": 3.00, "slippage_mult": 1.00, "entry_delay": 0, "note": "Spread tripled"},
    {"name": "slippage_light", "spread_mult": 1.00, "slippage_mult": 2.00, "entry_delay": 0, "note": "Light adverse slippage"},
    {"name": "slippage_heavy", "spread_mult": 1.25, "slippage_mult": 4.00, "entry_delay": 0, "note": "Heavy adverse slippage"},
    {"name": "entry_delay", "spread_mult": 1.00, "slippage_mult": 1.50, "entry_delay": 1, "note": "Entry delayed by one bar"},
    {"name": "combined_bad_fill", "spread_mult": 2.00, "slippage_mult": 4.00, "entry_delay": 1, "note": "Worse spread + slippage + delayed fill"},
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


def _load_source(run_dir: Path, logger: Callable[[str], None]) -> pd.DataFrame:
    for file_name, status_col, allowed, cols in [
        ("stage3_walkforward.csv", "wf_status", {"wf_pass", "wf_watchlist"}, WF_COLUMNS),
        ("stage2_validation.csv", "robustness_status", {"robust_candidate", "watchlist"}, VALIDATION_COLUMNS),
        ("candidate_edges.csv", "status", {"candidate"}, EDGE_COLUMNS),
    ]:
        p = run_dir / file_name
        if not p.exists():
            continue
        df = safe_read_csv(p, cols)
        if df.empty:
            continue
        if status_col in df.columns:
            preferred = df[df[status_col].isin(allowed)]
            if len(preferred):
                df = preferred
        return limit_candidates(df, "stress", logger)
    return pd.DataFrame(columns=EDGE_COLUMNS)


def _delayed_signals(buy: pd.Series, sell: pd.Series, bars: int) -> tuple[pd.Series, pd.Series]:
    if bars <= 0:
        return buy, sell
    return buy.shift(bars).fillna(False), sell.shift(bars).fillna(False)


def _scenario_backtest(row: dict, scenario: dict) -> dict:
    symbol = str(row.get("symbol")); tf = str(row.get("tf")); concept = str(row.get("concept"))
    lookback = int(_num(row.get("lookback"), 20)); session = str(row.get("session", "all")); rr = _num(row.get("rr"), 1.0); sl_mult = _num(row.get("sl_mult"), 1.0)
    fp = feature_path(symbol, tf)
    if not fp.exists():
        return {"scenario": scenario["name"], "pf": 0, "test_pf": 0, "expR": 0, "maxDD_R": 999, "trades": 0, "avg_cost_R": 0, "passed": False, "note": "Feature cache missing"}
    df = pd.read_pickle(fp)
    b0, s0 = signals(df, concept, lookback)
    b0, s0 = _delayed_signals(b0, s0, int(scenario.get("entry_delay", 0)))
    sm = session_mask(df, session)
    trades = backtest(df, b0 & sm, s0 & sm, rr, sl_mult, HORIZON.get(tf, 48), symbol=symbol, spread_mult=float(scenario.get("spread_mult", 1.0)), slippage_mult=float(scenario.get("slippage_mult", 1.0)))
    base = st(trades)
    if not base:
        return {"scenario": scenario["name"], "pf": 0, "test_pf": 0, "expR": 0, "maxDD_R": 999, "trades": 0, "avg_cost_R": 0, "passed": False, "note": scenario["note"]}
    split = max(1, int(len(trades) * 0.7))
    test = st(trades.iloc[split:]) or {}
    passed = base["pf"] >= 1.10 and _num(test.get("pf"), base["pf"]) >= 1.00 and base["expR"] > 0 and base["maxDD_R"] <= 18
    return {"scenario": scenario["name"], "pf": base["pf"], "test_pf": test.get("pf", base["pf"]), "expR": base["expR"], "maxDD_R": base["maxDD_R"], "trades": base["n"], "avg_cost_R": round(float(trades.cost_r.mean()), 5) if not trades.empty and "cost_r" in trades else 0, "passed": bool(passed), "note": scenario["note"]}


def _stress_row(row: dict) -> dict:
    scenario_rows = [_scenario_backtest(row, s) for s in SCENARIOS]
    pass_count = sum(1 for x in scenario_rows if x["passed"])
    failures = [x["scenario"] for x in scenario_rows if not x["passed"]]
    pass_rate = pass_count / len(SCENARIOS)
    worst = min(scenario_rows, key=lambda x: _num(x.get("test_pf"), 0))
    worst_dd = max(_num(x.get("maxDD_R"), 999) for x in scenario_rows)
    base = scenario_rows[0]
    status = "stress_pass" if pass_rate >= 0.86 and _num(worst.get("test_pf"), 0) >= 1.05 else ("stress_watchlist" if pass_rate >= 0.58 else "stress_fail")
    verdict = "Survives broker-aware execution stress gate" if status == "stress_pass" else f"Fails or weak under: {', '.join(failures[:4])}"
    return {"setup_id": row.get("setup_id") or row_setup_id(row), "symbol": row.get("symbol", ""), "tf": row.get("tf", ""), "concept": row.get("concept", ""), "lookback": row.get("lookback", ""), "session": row.get("session", ""), "rr": row.get("rr", ""), "sl_mult": row.get("sl_mult", ""), "trades": int(_num(base.get("trades"), _num(row.get("n"), row.get("trades", 0)))), "base_pf": base.get("pf", row.get("pf", 0)), "base_test_pf": base.get("test_pf", row.get("test_pf", 0)), "base_expR": base.get("expR", row.get("expR", 0)), "base_maxDD_R": base.get("maxDD_R", row.get("maxDD_R", 999)), "base_avg_cost_R": base.get("avg_cost_R", row.get("avg_cost_R", 0)), "pf": base.get("pf", row.get("pf", 0)), "test_pf": base.get("test_pf", row.get("test_pf", 0)), "expR": base.get("expR", row.get("expR", 0)), "maxDD_R": base.get("maxDD_R", row.get("maxDD_R", 999)), "stress_status": status, "stress_pass_rate": round(pass_rate, 3), "stress_passed_scenarios": pass_count, "stress_total_scenarios": len(SCENARIOS), "worst_test_pf": worst["test_pf"], "worst_maxDD_R": worst_dd, "verdict": verdict, "scenarios": scenario_rows, "ea_ready": False, "ea_reason": "Not EA-ready yet: needs Monte Carlo, portfolio heat and forward paper tracking after execution stress."}


def run_execution_stress(scan_name: str | None = None, logger: Callable[[str], None] = print):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = OUTPUTS_DIR / scan_name if scan_name else _latest_output_dir()
    if not run_dir or not run_dir.exists():
        raise RuntimeError("No discovery run found. Run Discover Edges first.")
    df = _load_source(run_dir, logger)
    logger(f"Execution-stress testing {len(df)} ranked candidates from {run_dir.name}")
    rows = []
    for i, row in enumerate(df.to_dict("records"), 1):
        logger(f"[{i}/{len(df)}] Stress {row.get('symbol','')} {row.get('tf','')} {row.get('concept','')}")
        rows.append(_stress_row(row))
    summary_df = pd.DataFrame([{k: v for k, v in r.items() if k != "scenarios"} for r in rows]) if rows else pd.DataFrame(columns=STRESS_COLUMNS)
    if not summary_df.empty:
        status_order = {"stress_pass": 0, "stress_watchlist": 1, "stress_fail": 2}
        summary_df["_status_order"] = summary_df.stress_status.map(status_order).fillna(9)
        summary_df = summary_df.sort_values(["_status_order", "stress_pass_rate", "worst_test_pf"], ascending=[True, False, False]).drop(columns=["_status_order"])
    summary_df = safe_to_csv(summary_df, run_dir / "stage4_execution_stress.csv", STRESS_COLUMNS)
    passed = int((summary_df.stress_status == "stress_pass").sum()) if not summary_df.empty else 0
    watch = int((summary_df.stress_status == "stress_watchlist").sum()) if not summary_df.empty else 0
    failed = int((summary_df.stress_status == "stress_fail").sum()) if not summary_df.empty else 0
    summary = {"scan_name": run_dir.name, "validated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "candidates_checked": int(len(summary_df)), "stress_pass": passed, "stress_watchlist": watch, "stress_fail": failed, "ea_ready": 0, "stage": "Stage 4 ranked broker-aware execution stress", "warning": "Execution stress is gated to the best ranked candidates. Uses spread_points when present; tick-level validation is still required before EA export.", "top": summary_df.head(25).replace([np.inf, -np.inf], np.nan).fillna("").to_dict("records") if not summary_df.empty else [], "details": rows, "scenarios": SCENARIOS}
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
    return {"candidates_checked": 0, "stress_pass": 0, "stress_watchlist": 0, "stress_fail": 0, "ea_ready": 0, "top": [], "warning": "No execution stress run yet."}
