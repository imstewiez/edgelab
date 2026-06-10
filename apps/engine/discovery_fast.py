from __future__ import annotations

import json
import time
from typing import Callable

import numpy as np
import pandas as pd

import quantlab_core as qc

EFFICIENT_MAX_BARS = {"M1": 60000, "M5": 90000, "M15": 120000, "M30": 140000, "H1": 160000}


def _concepts(tf: str, mode: str) -> list[str]:
    if mode == "broad":
        return qc.concepts_for_tf(tf)
    core = ["breakout_trend", "compression_breakout", "sweep_reclaim", "prev_day_sweep", "pullback_ema21"]
    if tf in ["M5", "M15", "M30", "H1"]:
        core.append("asian_breakout")
    return core


def _profile(tf: str, mode: str):
    if mode == "broad":
        sessions = ["all", "london_ny", "ny", "overlap"]
        lbs = [20, 50] if tf in ["H1", "H4", "D1"] else [12, 20, 48]
        rrs = [1.0, 1.4, 2.0]
        slms = [1.0, 1.4]
    else:
        sessions = ["all", "london_ny"] if tf in ["H4", "D1"] else ["all", "london_ny", "ny"]
        lbs = [20] if tf in ["H1", "H4", "D1"] else [12, 20]
        rrs = [1.0, 1.4, 2.0]
        slms = [1.0, 1.4]
    return sessions, lbs, rrs, slms


def _prepare_df(df: pd.DataFrame, tf: str, mode: str, logger: Callable[[str], None]) -> pd.DataFrame:
    if mode in {"exhaustive", "broad"}:
        return df
    max_bars = EFFICIENT_MAX_BARS.get(tf)
    if max_bars and len(df) > max_bars:
        logger(f"  using recent {max_bars:,} bars from {len(df):,} available for efficient discovery")
        return df.tail(max_bars).reset_index(drop=True)
    return df


def discover_edges(name, mode="priority", symbols="", tfs="", logger: Callable[[str], None] = print):
    if mode == "exhaustive" and hasattr(qc, "discover_edges_exhaustive"):
        logger("Exhaustive mode selected; using original full-grid discovery.")
        return qc.discover_edges_exhaustive(name, mode, symbols, tfs, logger)

    if not qc.FEATURE_CATALOG_PATH.exists():
        raise RuntimeError("No feature catalog found. Run Build Features first.")

    mode = "priority" if mode in {"auto", ""} else str(mode or "priority")
    cat = pd.read_csv(qc.FEATURE_CATALOG_PATH)
    if symbols:
        cat = cat[cat.symbol.isin({x.strip().upper() for x in symbols.split(",") if x.strip()})]
    if tfs:
        cat = cat[cat.tf.isin({x.strip().upper() for x in tfs.split(",") if x.strip()})]
    if mode in {"priority", "efficient", "fast", "broad"}:
        cat = cat[cat.symbol.isin(qc.PRIORITY_SYMBOLS)]
    if mode == "htf":
        cat = cat[cat.tf.isin(["H1", "H4", "D1"])]
    if mode == "intraday":
        cat = cat[cat.tf.isin(["M5", "M15", "M30"])]

    out = qc.OUTPUTS_DIR / name
    out.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    datasets: list[dict] = []
    broker = qc.load_broker_profile()
    started = time.time()
    logger(f"Efficient discovery started. mode={mode}, datasets={len(cat)}")

    for ds_i, (_, r) in enumerate(cat.iterrows(), 1):
        sym, tf = r.symbol, r.tf
        fp = qc.feature_path(sym, tf)
        if not fp.exists():
            continue
        raw_df = pd.read_pickle(fp)
        df = _prepare_df(raw_df, tf, mode, logger)
        datasets.append({"symbol": sym, "tf": tf, "rows": len(df), "source_rows": len(raw_df), "start": str(df.time.min()), "end": str(df.time.max()), "has_spread_points": "spread_points" in df.columns})
        concepts = _concepts(tf, mode)
        sessions, lbs, rrs, slms = _profile(tf, mode)
        min_tr = 25 if tf == "D1" else 35
        total_grid = len(concepts) * len(lbs) * len(sessions) * len(rrs) * len(slms)
        tested_here = 0
        logger(f"[{ds_i}/{len(cat)}] Scanning {sym} {tf}: rows={len(df):,}, grid≈{total_grid}")

        for concept in concepts:
            for lb in lbs:
                b0, s0 = qc.signals(df, concept, lb)
                raw_events = int(b0.sum() + s0.sum())
                if raw_events < min_tr:
                    continue
                logger(f"  {concept} lb={lb}: raw_events={raw_events}")
                for sess in sessions:
                    sm = qc.session_mask(df, sess)
                    for rr in rrs:
                        for slm in slms:
                            tested_here += 1
                            tr = qc.backtest(df, b0 & sm, s0 & sm, rr, slm, qc.HORIZON.get(tf, 48), symbol=sym)
                            base = qc.st(tr)
                            if not base or base["n"] < min_tr:
                                continue
                            split = max(1, int(len(tr) * 0.7))
                            test = qc.st(tr.iloc[split:]) or {}
                            mon = tr.groupby(["year", "month"]).R.sum()
                            pos = float((mon > 0).mean()) if len(mon) else 0
                            rec = {"symbol": sym, "tf": tf, "concept": concept, "lookback": lb, "session": sess, "rr": rr, "sl_mult": slm, **base, "test_pf": test.get("pf", ""), "test_n": test.get("n", 0), "positive_month_pct": round(pos, 3), "avg_cost_R": round(float(tr.cost_r.mean()), 5), "broker_profile": broker.get("name", "generic_mt5_cfd")}
                            rec["setup_id"] = qc.row_setup_id(rec)
                            score = rec["expR"] * 100 + min(rec["pf"], 3) * 20 + (min(float(rec["test_pf"]), 3) * 12 if rec["test_pf"] != "" else 0) + pos * 20 - rec["maxDD_R"] * 0.35 - rec["max_loss_streak"] * 1.5
                            reasons = []
                            if rec["pf"] < 1.22: reasons.append("PF below minimum")
                            if rec["test_n"] >= 10 and rec["test_pf"] < 1.05: reasons.append("Weak out-of-sample PF")
                            if pos < 0.48: reasons.append("Low monthly stability")
                            if rec["max_loss_streak"] > 9: reasons.append("Loss streak too high")
                            if rec["maxDD_R"] > 16: reasons.append("R drawdown too high")
                            rec["score"] = round(score, 3)
                            rec["status"] = "rejected" if reasons else "candidate"
                            rec["grade"] = "A" if not reasons and score >= 105 else ("B" if not reasons and score >= 80 else ("C" if not reasons else "Rejected"))
                            rec["verdict"] = "; ".join(reasons) if reasons else "Passed efficient automated checks"
                            results.append(rec)
        logger(f"[{ds_i}/{len(cat)}] Done {sym} {tf}: tested_grid={tested_here}, total_results={len(results)}, elapsed={time.time() - started:.1f}s")

    res = pd.DataFrame(results).sort_values("score", ascending=False) if results else pd.DataFrame()
    cand = res[res.status == "candidate"] if not res.empty else pd.DataFrame()
    rej = res[res.status == "rejected"] if not res.empty else pd.DataFrame()
    cards = [qc.edge_card(x) for x in cand.head(25).to_dict("records")] if not cand.empty else []
    pd.DataFrame(datasets).to_csv(out / "datasets_scanned.csv", index=False)
    res.to_csv(out / "all_edges.csv", index=False)
    cand.to_csv(out / "candidate_edges.csv", index=False)
    rej.to_csv(out / "rejected_edges.csv", index=False)
    (out / "edge_cards.json").write_text(json.dumps(cards, indent=2), encoding="utf-8")
    qc.LATEST_CARDS_PATH.write_text(json.dumps(cards, indent=2), encoding="utf-8")
    report = qc.make_report(name, datasets, res, cand, rej, cards)
    (out / "DISCOVERY_REPORT.md").write_text(report, encoding="utf-8")
    (out / "QUANTLAB_REPORT.md").write_text(report, encoding="utf-8")
    logger(f"Efficient discovery complete: tested_edges={len(res)}, candidates={len(cand)}, elapsed={time.time() - started:.1f}s")
    return {"scan_name": name, "datasets": len(datasets), "tested_edges": len(res), "candidates": len(cand), "rejected": len(rej), "mode": mode, "elapsed_sec": round(time.time() - started, 1), "active_concepts_tested": sorted(set(res.concept)) if not res.empty else []}
