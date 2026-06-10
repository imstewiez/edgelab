from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from quantlab_core import OUTPUTS_DIR, feature_path, signals, session_mask, HORIZON, row_setup_id


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


def _candidate_source(out: Path) -> pd.DataFrame:
    for fn in ["candidate_edges.csv", "all_edges.csv"]:
        p = out / fn
        if p.exists():
            df = pd.read_csv(p).replace([np.inf, -np.inf], np.nan).fillna("")
            if not df.empty:
                if "score" in df.columns:
                    df = df.sort_values("score", ascending=False)
                return df.head(80).copy()
    return pd.DataFrame()


def _barrier_outcome(df: pd.DataFrame, entry_idx: int, side: int, rr: float, sl_mult: float, horizon: int):
    entry = float(df.open.iloc[entry_idx])
    atr = float(df.atr14.iloc[max(0, entry_idx - 1)])
    if not np.isfinite(atr) or atr <= 0:
        return None
    risk = atr * sl_mult
    end = min(entry_idx + horizon, len(df) - 1)
    tp = entry + side * risk * rr
    sl = entry - side * risk
    label = "timeout"
    hit_idx = end
    for j in range(entry_idx, end + 1):
        hi, lo = float(df.high.iloc[j]), float(df.low.iloc[j])
        hit_tp = hi >= tp if side == 1 else lo <= tp
        hit_sl = lo <= sl if side == 1 else hi >= sl
        if hit_tp and hit_sl:
            label = "ambiguous_sl_first"
            hit_idx = j
            break
        if hit_tp:
            label = "tp_first"
            hit_idx = j
            break
        if hit_sl:
            label = "sl_first"
            hit_idx = j
            break
    window = df.iloc[entry_idx:end + 1]
    if side == 1:
        mfe = (float(window.high.max()) - entry) / risk
        mae = (entry - float(window.low.min())) / risk
    else:
        mfe = (entry - float(window.low.min())) / risk
        mae = (float(window.high.max()) - entry) / risk
    fwd = side * (float(df.close.iloc[end]) - entry) / risk
    return {"outcome": label, "outcome_index": int(hit_idx), "forward_R": round(float(fwd), 5), "mfe_R": round(float(mfe), 5), "mae_R": round(float(mae), 5)}


def run_event_lab(scan_name: str | None = None, logger: Callable[[str], None] = print):
    out = _run_dir(scan_name)
    candidates = _candidate_source(out)
    if candidates.empty:
        raise RuntimeError("No discovery rows found. Run discovery first.")

    logger(f"Event Lab started for {out.name}: {len(candidates)} setup rows")
    events: list[dict] = []
    summaries: list[dict] = []

    for _, r in candidates.iterrows():
        sym, tf, concept = str(r.symbol), str(r.tf), str(r.concept)
        fp = feature_path(sym, tf)
        if not fp.exists():
            continue
        df = pd.read_pickle(fp).reset_index(drop=True)
        lb = int(float(r.get("lookback", 20)))
        rr = float(r.get("rr", 1.4))
        slm = float(r.get("sl_mult", 1.4))
        sess = str(r.get("session", "all"))
        setup_id = str(r.get("setup_id") or row_setup_id(r))
        b, s = signals(df, concept, lb)
        mask = session_mask(df, sess)
        b = (b & mask).fillna(False)
        s = (s & mask).fillna(False)
        idxs = list(np.where((b | s).values)[0])
        idxs = [i for i in idxs if i >= 250 and i + 2 < len(df)]
        if len(idxs) > 500:
            step = max(1, len(idxs) // 500)
            idxs = idxs[::step][:500]
        setup_events = []
        for i in idxs:
            side = 1 if bool(b.iloc[i]) else -1
            entry_idx = i + 1
            outcome = _barrier_outcome(df, entry_idx, side, rr, slm, HORIZON.get(tf, 48))
            if not outcome:
                continue
            row = {
                "setup_id": setup_id,
                "symbol": sym,
                "tf": tf,
                "concept": concept,
                "session": sess,
                "lookback": lb,
                "rr": rr,
                "sl_mult": slm,
                "event_time": str(pd.to_datetime(df.time.iloc[i])),
                "entry_time": str(pd.to_datetime(df.time.iloc[entry_idx])),
                "side": "long" if side == 1 else "short",
                "hour": int(df.hour.iloc[i]) if "hour" in df.columns else "",
                "weekday": int(df.weekday.iloc[i]) if "weekday" in df.columns else "",
                "atr_rank_500": round(float(df.atr_rank_500.iloc[i]), 5) if "atr_rank_500" in df.columns and pd.notna(df.atr_rank_500.iloc[i]) else "",
                "range_rank_200": round(float(df.range_rank_200.iloc[i]), 5) if "range_rank_200" in df.columns and pd.notna(df.range_rank_200.iloc[i]) else "",
                "ema21_slope_atr": round(float(df.ema21_slope_atr.iloc[i]), 5) if "ema21_slope_atr" in df.columns and pd.notna(df.ema21_slope_atr.iloc[i]) else "",
                "wick_pressure": round(float(df.wick_pressure.iloc[i]), 5) if "wick_pressure" in df.columns and pd.notna(df.wick_pressure.iloc[i]) else "",
                "rsi14": round(float(df.rsi14.iloc[i]), 5) if "rsi14" in df.columns and pd.notna(df.rsi14.iloc[i]) else "",
                "compression": bool(df.compression.iloc[i]) if "compression" in df.columns else False,
                **outcome,
            }
            events.append(row)
            setup_events.append(row)
        if setup_events:
            edf = pd.DataFrame(setup_events)
            n = len(edf)
            summaries.append({
                "setup_id": setup_id,
                "symbol": sym,
                "tf": tf,
                "concept": concept,
                "session": sess,
                "lookback": lb,
                "rr": rr,
                "sl_mult": slm,
                "events": int(n),
                "long_events": int((edf.side == "long").sum()),
                "short_events": int((edf.side == "short").sum()),
                "tp_first_pct": round(float((edf.outcome == "tp_first").mean()), 4),
                "sl_first_pct": round(float((edf.outcome.isin(["sl_first", "ambiguous_sl_first"])).mean()), 4),
                "timeout_pct": round(float((edf.outcome == "timeout").mean()), 4),
                "mean_forward_R": round(float(edf.forward_R.mean()), 5),
                "median_forward_R": round(float(edf.forward_R.median()), 5),
                "mean_mfe_R": round(float(edf.mfe_R.mean()), 5),
                "mean_mae_R": round(float(edf.mae_R.mean()), 5),
                "event_status": "event_ready" if n >= 50 else "low_sample",
                "verdict": "Enough events for contextual analysis" if n >= 50 else "Low event sample; treat cautiously",
            })

    events_df = pd.DataFrame(events)
    summary_df = pd.DataFrame(summaries)
    if not summary_df.empty:
        summary_df = summary_df.sort_values(["event_status", "events", "mean_forward_R"], ascending=[True, False, False])
    events_df.to_csv(out / "events.csv", index=False)
    summary_df.to_csv(out / "event_summary.csv", index=False)
    summary = {
        "scan_name": out.name,
        "setups_analyzed": int(len(summary_df)),
        "events": int(len(events_df)),
        "event_ready": int((summary_df.event_status == "event_ready").sum()) if not summary_df.empty else 0,
        "low_sample": int((summary_df.event_status == "low_sample").sum()) if not summary_df.empty else 0,
        "top": summary_df.head(25).replace([np.inf, -np.inf], np.nan).fillna("").to_dict("records") if not summary_df.empty else [],
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (out / "EVENT_LAB_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger(f"Event Lab complete: {summary['events']} events, {summary['event_ready']} event-ready setups")
    return summary


def read_event_lab(scan_name: str | None = None):
    out = _run_dir(scan_name)
    p = out / "EVENT_LAB_SUMMARY.json"
    if not p.exists():
        return {"scan_name": out.name, "setups_analyzed": 0, "events": 0, "event_ready": 0, "low_sample": 0, "top": []}
    return json.loads(p.read_text(encoding="utf-8"))
