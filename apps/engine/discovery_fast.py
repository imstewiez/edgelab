from __future__ import annotations

import json
import time
from typing import Callable

import numpy as np
import pandas as pd

import quantlab_core as qc
from pipeline_io import EDGE_COLUMNS, safe_to_csv

QUICK_SYMBOL_ORDER = ["XAUUSD", "NAS100", "US30", "GBPJPY", "EURUSD", "GBPUSD", "USDJPY", "XTIUSD", "USDCAD", "EURJPY", "AUDUSD"]
QUICK_TF_ORDER = ["M15", "M30", "H1", "H4", "D1", "M5"]
QUICK_MAX_DATASETS = 12
QUICK_MAX_RESULTS = 600
EFFICIENT_MAX_DATASETS = 28

QUICK_MAX_BARS = {"M1": 12000, "M5": 20000, "M15": 35000, "M30": 45000, "H1": 70000}
EFFICIENT_MAX_BARS = {"M1": 30000, "M5": 50000, "M15": 75000, "M30": 90000, "H1": 120000}


def _concepts(tf: str, mode: str) -> list[str]:
    if mode == "quick":
        core = ["sweep_reclaim", "compression_breakout", "breakout_trend"]
        if tf in ["H1", "H4", "D1", "M30"]:
            core.append("prev_day_sweep")
        return core
    if mode in {"broad", "exhaustive"}:
        return qc.concepts_for_tf(tf)
    core = ["breakout_trend", "compression_breakout", "sweep_reclaim", "prev_day_sweep", "pullback_ema21"]
    if tf in ["M5", "M15", "M30", "H1"]:
        core.append("asian_breakout")
    return core


def _profile(tf: str, mode: str):
    if mode == "quick":
        sessions = ["all"] if tf in ["H4", "D1"] else ["london_ny", "ny"]
        lbs = [20]
        rrs = [1.0, 1.4]
        slms = [1.0]
    elif mode in {"broad", "exhaustive"}:
        sessions = ["all", "london_ny", "ny", "overlap"]
        lbs = [20, 50] if tf in ["H1", "H4", "D1"] else [12, 20, 48]
        rrs = [1.0, 1.4, 2.0, 2.5]
        slms = [1.0, 1.4, 2.0]
    else:
        sessions = ["all", "london_ny"] if tf in ["H4", "D1"] else ["all", "london_ny", "ny"]
        lbs = [20] if tf in ["H1", "H4", "D1"] else [12, 20]
        rrs = [1.0, 1.4, 2.0]
        slms = [1.0, 1.4]
    return sessions, lbs, rrs, slms


def _rank_and_limit(cat: pd.DataFrame, mode: str, symbols: str, tfs: str) -> pd.DataFrame:
    if cat.empty:
        return cat
    if mode == "quick":
        if not symbols:
            cat = cat[cat.symbol.isin(QUICK_SYMBOL_ORDER)]
        if not tfs:
            cat = cat[cat.tf.isin(QUICK_TF_ORDER)]
        if cat.empty:
            return cat
        sym_rank = {s: i for i, s in enumerate(QUICK_SYMBOL_ORDER)}
        tf_rank = {t: i for i, t in enumerate(QUICK_TF_ORDER)}
        cat = cat.copy()
        cat["_rank"] = cat.symbol.map(sym_rank).fillna(999).astype(int) * 100 + cat.tf.map(tf_rank).fillna(99).astype(int)
        return cat.sort_values(["_rank", "symbol", "tf"]).drop(columns=["_rank"]).head(QUICK_MAX_DATASETS)
    if mode in {"efficient", "fast", "priority"} and len(cat) > EFFICIENT_MAX_DATASETS:
        sym_rank = {s: i for i, s in enumerate(QUICK_SYMBOL_ORDER)}
        tf_rank = {t: i for i, t in enumerate(QUICK_TF_ORDER + ["M1"])}
        cat = cat.copy()
        cat["_rank"] = cat.symbol.map(sym_rank).fillna(999).astype(int) * 100 + cat.tf.map(tf_rank).fillna(99).astype(int)
        return cat.sort_values(["_rank", "symbol", "tf"]).drop(columns=["_rank"]).head(EFFICIENT_MAX_DATASETS)
    return cat


def _prepare_df(df: pd.DataFrame, tf: str, mode: str, logger: Callable[[str], None]) -> pd.DataFrame:
    if mode in {"exhaustive", "broad"}:
        return df.reset_index(drop=True)
    limits = QUICK_MAX_BARS if mode == "quick" else EFFICIENT_MAX_BARS
    max_bars = limits.get(tf)
    if max_bars and len(df) > max_bars:
        logger(f"  using recent {max_bars:,} bars from {len(df):,} available for {mode} discovery")
        return df.tail(max_bars).reset_index(drop=True)
    return df.reset_index(drop=True)


def _empty_result(name: str, out, datasets: list[dict], logger: Callable[[str], None], reason: str):
    safe_to_csv(pd.DataFrame(datasets), out / "datasets_scanned.csv")
    safe_to_csv([], out / "all_edges.csv", EDGE_COLUMNS)
    safe_to_csv([], out / "candidate_edges.csv", EDGE_COLUMNS)
    safe_to_csv([], out / "rejected_edges.csv", EDGE_COLUMNS)
    (out / "edge_cards.json").write_text("[]", encoding="utf-8")
    qc.LATEST_CARDS_PATH.write_text("[]", encoding="utf-8")
    report = f"# EdgeLab Auto Discovery Report — {name}\n\nDatasets scanned: {len(datasets)}\n\nEdges screened: 0\n\nFirst-pass candidates: 0\n\nReason: {reason}\n"
    (out / "DISCOVERY_REPORT.md").write_text(report, encoding="utf-8")
    (out / "QUANTLAB_REPORT.md").write_text(report, encoding="utf-8")
    logger(reason)
    return {"scan_name": name, "datasets": len(datasets), "tested_edges": 0, "candidates": 0, "rejected": 0, "mode": "empty", "active_concepts_tested": [], "warning": reason}


def discover_edges(name, mode="quick", symbols="", tfs="", logger: Callable[[str], None] = print):
    if not qc.FEATURE_CATALOG_PATH.exists():
        raise RuntimeError("No feature catalog found. Run Build Features first.")

    mode = "quick" if mode in {"auto", "priority", "efficient", "fast", ""} else str(mode or "quick")
    cat = pd.read_csv(qc.FEATURE_CATALOG_PATH).replace([np.inf, -np.inf], np.nan).fillna("")
    if symbols:
        cat = cat[cat.symbol.isin({x.strip().upper() for x in symbols.split(",") if x.strip()})]
    if tfs:
        cat = cat[cat.tf.isin({x.strip().upper() for x in tfs.split(",") if x.strip()})]
    if mode in {"priority", "efficient", "fast", "quick", "broad"}:
        cat = cat[cat.symbol.isin(qc.PRIORITY_SYMBOLS)]
    if mode == "htf":
        cat = cat[cat.tf.isin(["H1", "H4", "D1"])]
    if mode == "intraday":
        cat = cat[cat.tf.isin(["M5", "M15", "M30"])]
    cat = _rank_and_limit(cat, mode, symbols, tfs)

    out = qc.OUTPUTS_DIR / name
    out.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    datasets: list[dict] = []
    broker = qc.load_broker_profile()
    started = time.time()
    logger(f"{mode.title()} discovery started. datasets={len(cat)}")

    if cat.empty:
        return _empty_result(name, out, datasets, logger, "No datasets matched selected mode/symbol/timeframe filters.")

    stop_scan = False
    for ds_i, (_, r) in enumerate(cat.iterrows(), 1):
        sym, tf = str(r.symbol), str(r.tf)
        fp = qc.feature_path(sym, tf)
        if not fp.exists():
            logger(f"[{ds_i}/{len(cat)}] Missing feature cache for {sym} {tf}; skipping")
            continue
        try:
            raw_df = pd.read_pickle(fp)
            df = _prepare_df(raw_df, tf, mode, logger)
        except Exception as e:
            logger(f"[{ds_i}/{len(cat)}] Could not read feature cache for {sym} {tf}: {e}")
            continue
        datasets.append({"symbol": sym, "tf": tf, "rows": len(df), "source_rows": len(raw_df), "start": str(df.time.min()), "end": str(df.time.max()), "has_spread_points": "spread_points" in df.columns})
        concepts = _concepts(tf, mode)
        sessions, lbs, rrs, slms = _profile(tf, mode)
        min_tr = 25 if tf == "D1" else 35
        total_grid = len(concepts) * len(lbs) * len(sessions) * len(rrs) * len(slms)
        tested_here = 0
        logger(f"[{ds_i}/{len(cat)}] Scanning {sym} {tf}: rows={len(df):,}, grid≈{total_grid}")

        for concept in concepts:
            for lb in lbs:
                try:
                    b0, s0 = qc.signals(df, concept, lb)
                    raw_events = int(b0.sum() + s0.sum())
                except Exception as e:
                    logger(f"  signal error {concept} lb={lb}: {e}")
                    continue
                if raw_events < min_tr:
                    continue
                logger(f"  {concept} lb={lb}: raw_events={raw_events}")
                for sess in sessions:
                    sm = qc.session_mask(df, sess)
                    for rr in rrs:
                        for slm in slms:
                            tested_here += 1
                            try:
                                tr = qc.backtest(df, b0 & sm, s0 & sm, rr, slm, qc.HORIZON.get(tf, 48), symbol=sym)
                                base = qc.st(tr)
                            except Exception as e:
                                logger(f"    backtest error {concept} {sess} lb={lb} rr={rr} sl={slm}: {e}")
                                continue
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
                            rec["verdict"] = "; ".join(reasons) if reasons else "Passed quick automated checks"
                            results.append(rec)
                            if mode == "quick" and len(results) >= QUICK_MAX_RESULTS:
                                stop_scan = True
                                break
                        if stop_scan: break
                    if stop_scan: break
                if stop_scan: break
            if stop_scan: break
        logger(f"[{ds_i}/{len(cat)}] Done {sym} {tf}: tested_grid={tested_here}, total_results={len(results)}, elapsed={time.time() - started:.1f}s")
        if stop_scan:
            logger(f"Quick result cap reached ({QUICK_MAX_RESULTS}); stopping discovery early.")
            break

    if not results:
        return _empty_result(name, out, datasets, logger, "Discovery completed but no setup passed the minimum trade/sample filters.")

    res = pd.DataFrame(results).sort_values("score", ascending=False)
    cand = res[res.status == "candidate"]
    rej = res[res.status == "rejected"]
    cards = [qc.edge_card(x) for x in cand.head(25).to_dict("records")] if not cand.empty else []
    safe_to_csv(pd.DataFrame(datasets), out / "datasets_scanned.csv")
    safe_to_csv(res, out / "all_edges.csv", EDGE_COLUMNS)
    safe_to_csv(cand, out / "candidate_edges.csv", EDGE_COLUMNS)
    safe_to_csv(rej, out / "rejected_edges.csv", EDGE_COLUMNS)
    (out / "edge_cards.json").write_text(json.dumps(cards, indent=2), encoding="utf-8")
    qc.LATEST_CARDS_PATH.write_text(json.dumps(cards, indent=2), encoding="utf-8")
    report = qc.make_report(name, datasets, res, cand, rej, cards)
    (out / "DISCOVERY_REPORT.md").write_text(report, encoding="utf-8")
    (out / "QUANTLAB_REPORT.md").write_text(report, encoding="utf-8")
    logger(f"{mode.title()} discovery complete: tested_edges={len(res)}, candidates={len(cand)}, elapsed={time.time() - started:.1f}s")
    return {"scan_name": name, "datasets": len(datasets), "tested_edges": len(res), "candidates": len(cand), "rejected": len(rej), "mode": mode, "elapsed_sec": round(time.time() - started, 1), "active_concepts_tested": sorted(set(res.concept)) if not res.empty else []}
