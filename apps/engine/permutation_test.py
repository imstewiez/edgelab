from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from pipeline_io import EDGE_COLUMNS, MC_COLUMNS, PERMUTATION_COLUMNS, PORTFOLIO_COLUMNS, SENSITIVITY_COLUMNS, STRESS_COLUMNS, VALIDATION_COLUMNS, WF_COLUMNS, safe_read_csv, safe_to_csv
from quantlab_core import OUTPUTS_DIR, feature_path, signals, session_mask, HORIZON, backtest, st, row_setup_id

RNG_SEED = 42


def _latest_run() -> str | None:
    runs = sorted([p for p in OUTPUTS_DIR.iterdir() if p.is_dir()], reverse=True) if OUTPUTS_DIR.exists() else []
    return runs[0].name if runs else None


def _run_dir(scan_name: str | None) -> Path:
    name = scan_name or _latest_run()
    if not name:
        raise RuntimeError("No output run found. Run discovery first.")
    out = OUTPUTS_DIR / name
    if not out.exists():
        raise RuntimeError(f"Run not found: {name}")
    return out


def _source(out: Path) -> pd.DataFrame:
    sources = [
        ("stage7_portfolio_risk.csv", "portfolio_status", "pass|watchlist", PORTFOLIO_COLUMNS),
        ("stage6_sensitivity.csv", "sensitivity_status", "pass|watchlist", SENSITIVITY_COLUMNS),
        ("stage5_monte_carlo.csv", "mc_status", "pass|watchlist", MC_COLUMNS),
        ("stage4_execution_stress.csv", "stress_status", "pass|watchlist", STRESS_COLUMNS),
        ("stage3_walkforward.csv", "wf_status", "pass|watchlist", WF_COLUMNS),
        ("stage2_validation.csv", "robustness_status", "robust_candidate|watchlist", VALIDATION_COLUMNS),
        ("candidate_edges.csv", "status", "candidate", EDGE_COLUMNS),
    ]
    for fn, status_col, ok, cols in sources:
        p = out / fn
        if not p.exists():
            continue
        df = safe_read_csv(p, cols)
        if df.empty:
            continue
        if status_col in df.columns:
            preferred = df[df[status_col].astype(str).str.contains(ok, case=False, regex=True)]
            if not preferred.empty:
                df = preferred
        if "score" in df.columns:
            df = df.sort_values("score", ascending=False)
        return df.head(60).copy()
    return pd.DataFrame(columns=EDGE_COLUMNS)


def _shuffle_signals_like(rng, buy: pd.Series, sell: pd.Series, allowed: pd.Series) -> tuple[pd.Series, pd.Series]:
    idx = np.where(allowed.values)[0]
    n_buy = int(buy.sum())
    n_sell = int(sell.sum())
    total = min(len(idx), n_buy + n_sell)
    if total <= 0:
        return pd.Series(False, index=buy.index), pd.Series(False, index=sell.index)
    chosen = rng.choice(idx, size=total, replace=False)
    b_idx = chosen[:min(n_buy, total)]
    s_idx = chosen[min(n_buy, total):]
    rb = pd.Series(False, index=buy.index)
    rs = pd.Series(False, index=sell.index)
    rb.iloc[b_idx] = True
    rs.iloc[s_idx] = True
    return rb, rs


def _empty(out: Path, reason: str):
    dfres = safe_to_csv([], out / "stage8_permutation_test.csv", PERMUTATION_COLUMNS)
    summary = {"scan_name": out.name, "permutation_pass": 0, "permutation_watchlist": 0, "permutation_fail": 0, "low_sample": 0, "top": [], "warning": reason, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (out / "PERMUTATION_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def run_permutation_test(scan_name: str | None = None, logger: Callable[[str], None] = print, iterations: int = 80):
    out = _run_dir(scan_name)
    rows = _source(out)
    if rows.empty:
        logger("Permutation test skipped: no candidate rows available.")
        return _empty(out, "No candidate rows available for permutation test.")
    logger(f"Permutation test started for {out.name}: {len(rows)} setups, {iterations} shuffles each")
    rng = np.random.default_rng(RNG_SEED)
    results: list[dict] = []

    for _, r in rows.iterrows():
        sym, tf, concept = str(r.get("symbol", "")), str(r.get("tf", "")), str(r.get("concept", ""))
        fp = feature_path(sym, tf)
        if not fp.exists():
            continue
        df = pd.read_pickle(fp).reset_index(drop=True)
        lb = int(float(r.get("lookback", 20)))
        rr = float(r.get("rr", 1.4))
        slm = float(r.get("sl_mult", 1.4))
        sess = str(r.get("session", "all"))
        setup_id = str(r.get("setup_id") or row_setup_id(r))
        try:
            b0, s0 = signals(df, concept, lb)
            allowed = session_mask(df, sess).fillna(False)
        except Exception as e:
            logger(f"Permutation signal error {setup_id}: {e}")
            continue
        buy = (b0 & allowed).fillna(False)
        sell = (s0 & allowed).fillna(False)
        real_tr = backtest(df, buy, sell, rr, slm, HORIZON.get(tf, 48), symbol=sym)
        real_stats = st(real_tr)
        if not real_stats or real_stats.get("n", 0) < 25:
            results.append({"setup_id": setup_id, "symbol": sym, "tf": tf, "concept": concept, "permutation_status": "low_sample", "permutation_score": 0, "real_sumR": real_stats.get("sumR", 0) if real_stats else 0, "real_pf": real_stats.get("pf", 0) if real_stats else 0, "iterations": 0, "verdict": "Not enough trades for randomization test"})
            continue
        rnd_sum = []
        rnd_pf = []
        for _ in range(iterations):
            rb, rs = _shuffle_signals_like(rng, buy, sell, allowed)
            rt = backtest(df, rb, rs, rr, slm, HORIZON.get(tf, 48), symbol=sym)
            rsx = st(rt)
            if rsx:
                rnd_sum.append(float(rsx["sumR"]))
                rnd_pf.append(float(rsx["pf"]))
        if not rnd_sum:
            continue
        real_sum = float(real_stats["sumR"])
        real_pf = float(real_stats["pf"])
        percentile = float((np.array(rnd_sum) < real_sum).mean())
        pf_percentile = float((np.array(rnd_pf) < real_pf).mean())
        p_value = 1.0 - percentile
        score = round((percentile * 70 + pf_percentile * 30), 3)
        if percentile >= 0.90 and real_pf >= 1.15:
            status = "perm_pass"; verdict = "Real event timing beats randomized timing"
        elif percentile >= 0.75:
            status = "perm_watchlist"; verdict = "Some evidence vs random timing, needs forward confirmation"
        else:
            status = "perm_fail"; verdict = "Edge may be mostly timing noise"
        results.append({"setup_id": setup_id, "symbol": sym, "tf": tf, "concept": concept, "session": sess, "lookback": lb, "rr": rr, "sl_mult": slm, "real_trades": int(real_stats["n"]), "real_sumR": round(real_sum, 4), "real_pf": real_pf, "random_median_sumR": round(float(np.median(rnd_sum)), 4), "random_p95_sumR": round(float(np.percentile(rnd_sum, 95)), 4), "random_median_pf": round(float(np.median(rnd_pf)), 4), "sumR_percentile": round(percentile, 4), "pf_percentile": round(pf_percentile, 4), "p_value_approx": round(p_value, 4), "iterations": len(rnd_sum), "permutation_score": score, "permutation_status": status, "verdict": verdict})

    dfres = pd.DataFrame(results)
    if not dfres.empty:
        dfres = dfres.sort_values(["permutation_status", "permutation_score"], ascending=[True, False])
    dfres = safe_to_csv(dfres, out / "stage8_permutation_test.csv", PERMUTATION_COLUMNS)
    summary = {"scan_name": out.name, "permutation_pass": int((dfres.permutation_status == "perm_pass").sum()) if not dfres.empty else 0, "permutation_watchlist": int((dfres.permutation_status == "perm_watchlist").sum()) if not dfres.empty else 0, "permutation_fail": int((dfres.permutation_status == "perm_fail").sum()) if not dfres.empty else 0, "low_sample": int((dfres.permutation_status == "low_sample").sum()) if not dfres.empty else 0, "top": dfres.head(25).replace([np.inf, -np.inf], np.nan).fillna("").to_dict("records") if not dfres.empty else [], "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (out / "PERMUTATION_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger(f"Permutation test complete: {summary['permutation_pass']} pass, {summary['permutation_watchlist']} watchlist")
    return summary


def read_permutation_test(scan_name: str | None = None):
    out = _run_dir(scan_name)
    p = out / "PERMUTATION_SUMMARY.json"
    if not p.exists():
        return {"scan_name": out.name, "permutation_pass": 0, "permutation_watchlist": 0, "permutation_fail": 0, "low_sample": 0, "top": []}
    return json.loads(p.read_text(encoding="utf-8"))
