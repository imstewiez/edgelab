from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from quantlab_core import OUTPUTS_DIR, HORIZON, backtest, feature_path, filter_by_setup_keys, row_setup_id, session_mask, signals

PORTFOLIO_PATH = OUTPUTS_DIR / "latest_portfolio_risk.json"


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
    df = pd.read_csv(cand).replace([np.inf, -np.inf], np.nan).fillna("")
    for file_name, status_col, allowed in [
        ("stage6_sensitivity.csv", "sensitivity_status", {"sensitivity_pass", "sensitivity_watchlist"}),
        ("stage5_monte_carlo.csv", "mc_status", {"mc_pass", "mc_watchlist"}),
        ("stage4_execution_stress.csv", "stress_status", {"stress_pass", "stress_watchlist"}),
        ("stage3_walkforward.csv", "wf_status", {"wf_pass", "wf_watchlist"}),
        ("stage2_validation.csv", "robustness_status", {"robust_candidate", "watchlist"}),
    ]:
        p = run_dir / file_name
        if not p.exists():
            continue
        f = pd.read_csv(p).replace([np.inf, -np.inf], np.nan).fillna("")
        if status_col in f.columns:
            f = f[f[status_col].isin(allowed)]
        filtered = filter_by_setup_keys(df, f)
        if len(filtered):
            return filtered.head(50)
    return df.head(50)


def _monthly_returns(row: dict):
    symbol = str(row.get("symbol"))
    tf = str(row.get("tf"))
    concept = str(row.get("concept"))
    lookback = int(_num(row.get("lookback"), 20))
    session = str(row.get("session", "all"))
    rr = _num(row.get("rr"), 1.0)
    sl_mult = _num(row.get("sl_mult"), 1.0)
    setup_id = row.get("setup_id") or row_setup_id(row)
    fp = feature_path(symbol, tf)
    if not fp.exists():
        return None, None, None
    df = pd.read_pickle(fp)
    buy, sell = signals(df, concept, lookback)
    sm = session_mask(df, session)
    trades = backtest(df, buy & sm, sell & sm, rr, sl_mult, HORIZON.get(tf, 48), symbol=symbol)
    if trades.empty or len(trades) < 20:
        return None, None, None
    ser = trades.groupby(["year", "month"]).R.sum()
    ser.index = [f"{int(y):04d}-{int(m):02d}" for y, m in ser.index]
    meta = {"id": setup_id, "setup_id": setup_id, "symbol": symbol, "tf": tf, "concept": concept, "session": session, "lookback": lookback, "rr": rr, "sl_mult": sl_mult, "trades": int(len(trades)), "sumR": round(float(trades.R.sum()), 3), "avg_cost_R": round(float(trades.cost_r.mean()), 5) if "cost_r" in trades else 0}
    return setup_id, ser, meta


def _max_dd(series: pd.Series) -> float:
    eq = series.cumsum()
    return round(float((eq.cummax() - eq).max()), 3) if len(eq) else 0.0


def run_portfolio_risk(scan_name: str | None = None, logger: Callable[[str], None] = print):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = OUTPUTS_DIR / scan_name if scan_name else _latest_output_dir()
    if not run_dir or not run_dir.exists():
        raise RuntimeError("No discovery run found. Run Discover first.")
    candidates = _candidate_source(run_dir)
    logger(f"Portfolio/risk testing {len(candidates)} candidates from {run_dir.name}")
    series = {}
    metas = []
    for i, row in enumerate(candidates.to_dict("records"), 1):
        logger(f"[{i}/{len(candidates)}] Portfolio {row.get('symbol','')} {row.get('tf','')} {row.get('concept','')}")
        key, ser, meta = _monthly_returns(row)
        if key is None:
            continue
        series[key] = ser
        metas.append(meta)
    if not series:
        summary = {"scan_name": run_dir.name, "candidates_checked": 0, "portfolio_pass": 0, "ea_ready": 0, "top": [], "warning": "No valid strategy return streams for portfolio analysis."}
        PORTFOLIO_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary
    mat = pd.DataFrame(series).fillna(0).sort_index()
    corr = mat.corr().fillna(0)
    combined = mat.sum(axis=1) / max(1, mat.shape[1])
    high_corr_pairs = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c = float(corr.iloc[i, j])
            if abs(c) >= 0.65:
                high_corr_pairs.append({"a": cols[i], "b": cols[j], "corr": round(c, 3)})
    rows = []
    for meta in metas:
        key = meta["id"]
        avg_corr = float(corr[key].drop(index=key, errors="ignore").abs().mean()) if len(cols) > 1 else 0.0
        contribution_dd = _max_dd(mat[key])
        score = 100
        reasons = []
        if avg_corr > 0.60:
            score -= 35; reasons.append("high average correlation")
        elif avg_corr > 0.40:
            score -= 18; reasons.append("moderate correlation")
        if contribution_dd > 16:
            score -= 25; reasons.append("large standalone monthly DD")
        elif contribution_dd > 10:
            score -= 12; reasons.append("moderate standalone monthly DD")
        if meta["sumR"] <= 0:
            score -= 25; reasons.append("non-positive total R")
        status = "portfolio_pass" if score >= 75 else ("portfolio_watchlist" if score >= 55 else "portfolio_fail")
        rows.append({**meta, "avg_abs_corr": round(avg_corr, 3), "standalone_monthly_dd_R": contribution_dd, "portfolio_score": int(score), "portfolio_status": status, "verdict": "; ".join(reasons) if reasons else "Adds acceptable diversified risk"})
    out = pd.DataFrame(rows).sort_values("portfolio_score", ascending=False)
    out.to_csv(run_dir / "stage7_portfolio_risk.csv", index=False)
    corr.to_csv(run_dir / "stage7_strategy_correlation.csv")
    summary = {"scan_name": run_dir.name, "validated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "candidates_checked": int(len(out)), "portfolio_pass": int((out.portfolio_status == "portfolio_pass").sum()), "portfolio_watchlist": int((out.portfolio_status == "portfolio_watchlist").sum()), "portfolio_fail": int((out.portfolio_status == "portfolio_fail").sum()), "portfolio_monthly_sumR": round(float(combined.sum()), 3), "portfolio_monthly_dd_R": _max_dd(combined), "avg_pair_corr": round(float(corr.where(~np.eye(len(corr), dtype=bool)).stack().abs().mean()), 3) if len(corr) > 1 else 0, "high_corr_pairs": high_corr_pairs[:30], "ea_ready": 0, "stage": "Stage 7 portfolio/risk heat", "warning": "Portfolio risk uses exact setup_id monthly R streams as a first approximation. Final live sizing needs trade-time overlap, broker margin and forward tracking.", "top": out.head(25).to_dict("records")}
    (run_dir / "PORTFOLIO_RISK_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    PORTFOLIO_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def read_portfolio_risk(scan_name: str | None = None):
    if scan_name:
        p = OUTPUTS_DIR / scan_name / "PORTFOLIO_RISK_SUMMARY.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    if PORTFOLIO_PATH.exists():
        return json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
    return {"candidates_checked": 0, "portfolio_pass": 0, "portfolio_watchlist": 0, "portfolio_fail": 0, "ea_ready": 0, "top": [], "warning": "No portfolio risk run yet."}
