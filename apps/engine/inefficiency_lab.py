from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from pipeline_io import safe_to_csv
from quantlab_core import FEATURE_CATALOG_PATH, OUTPUTS_DIR, HORIZON, feature_path, signals, session_mask

INEFFICIENCY_PATH = OUTPUTS_DIR / "latest_inefficiency_lab.json"

INEFFICIENCY_COLUMNS = [
    "symbol", "tf", "family", "pattern", "side", "lookback", "session", "events", "mean_forward_R",
    "median_forward_R", "mean_mfe_R", "mean_mae_R", "hit_1R_pct", "adverse_1R_pct", "directional_asymmetry",
    "inefficiency_score", "interpretation", "buyers_sellers_proxy", "where_liquidity_sits", "caveat",
]

PRIORITY_PATTERNS = [
    "sweep_reclaim",
    "prev_day_sweep",
    "equal_high_low_sweep",
    "compression_breakout",
    "fvg_rebalance",
    "order_block_retest",
    "bos_breakout",
    "choch_reversal",
    "pullback_ema21",
]

PATTERN_FAMILY = {
    "sweep_reclaim": "liquidity_sweep_reversal",
    "prev_day_sweep": "daily_liquidity_sweep",
    "equal_high_low_sweep": "equal_high_low_liquidity_pool",
    "compression_breakout": "volatility_compression_expansion",
    "fvg_rebalance": "fair_value_gap_rebalance",
    "order_block_retest": "order_block_retest_proxy",
    "bos_breakout": "break_of_structure_continuation",
    "choch_reversal": "change_of_character_reversal",
    "pullback_ema21": "trend_pullback_continuation",
    "asian_breakout": "session_range_breakout",
}


def _safe_num(v, default=0.0) -> float:
    try:
        if v is None or pd.isna(v):
            return default
        x = float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _future_metrics(df: pd.DataFrame, idx: np.ndarray, side: int, horizon: int) -> pd.DataFrame:
    if len(idx) == 0:
        return pd.DataFrame()
    close = df.close.to_numpy(dtype=float)
    high = df.high.to_numpy(dtype=float)
    low = df.low.to_numpy(dtype=float)
    atr = df.atr14.to_numpy(dtype=float)
    rows = []
    n = len(df)
    for i in idx:
        if i < 250 or i >= n - 2:
            continue
        risk = float(atr[i])
        if not np.isfinite(risk) or risk <= 0:
            continue
        end = min(int(i) + int(horizon), n - 1)
        entry = float(close[i])
        if side == 1:
            forward = (float(close[end]) - entry) / risk
            mfe = (float(np.max(high[i + 1:end + 1])) - entry) / risk if end > i else 0
            mae = (entry - float(np.min(low[i + 1:end + 1]))) / risk if end > i else 0
        else:
            forward = (entry - float(close[end])) / risk
            mfe = (entry - float(np.min(low[i + 1:end + 1]))) / risk if end > i else 0
            mae = (float(np.max(high[i + 1:end + 1])) - entry) / risk if end > i else 0
        rows.append({"forward_R": forward, "mfe_R": mfe, "mae_R": mae, "hit_1R": mfe >= 1.0, "adverse_1R": mae >= 1.0})
    return pd.DataFrame(rows)


def _describe(pattern: str, side: str) -> tuple[str, str, str]:
    if pattern in {"sweep_reclaim", "prev_day_sweep", "equal_high_low_sweep"}:
        liq = "Stops/resting liquidity beyond prior highs/lows; reclaim suggests trapped breakout traders."
        proxy = "Long side = sellers got swept below lows then buyers reclaimed. Short side = buyers got swept above highs then sellers reclaimed."
    elif pattern == "compression_breakout":
        liq = "Liquidity accumulates around a compressed range; expansion tests whether range break has continuation."
        proxy = "Breakout direction is treated as the side gaining control after volatility contraction."
    elif pattern == "fvg_rebalance":
        liq = "Imbalance/FVG mid acts as a rebalance area; reaction tests whether the imbalance still has directional value."
        proxy = "Buyers/sellers proxy comes from whether price rejects the rebalance area in trend direction."
    elif pattern == "order_block_retest":
        liq = "Last opposite candle before impulse is used as an order-block proxy; retest response is measured."
        proxy = "Buyers/sellers proxy comes from impulse origin retest holding or failing."
    elif pattern in {"bos_breakout", "choch_reversal"}:
        liq = "Structure break identifies where stops and breakout orders likely cluster around swing boundaries."
        proxy = "BOS = continuation control; CHOCH = possible control shift after prior trend."
    else:
        liq = "Generic price-action event; liquidity is inferred from recent range and session boundaries."
        proxy = "Buyers/sellers are inferred from candle direction, wick pressure, trend and follow-through."
    interp = f"{side.title()} edge proxy around {pattern.replace('_', ' ')}."
    return interp, proxy, liq


def _score(events: int, mean_forward: float, median_forward: float, mfe: float, mae: float, hit: float, adverse: float) -> int:
    if events <= 0:
        return 0
    sample = min(30, events) / 30 * 20
    edge = max(-20, min(45, mean_forward * 22 + median_forward * 12))
    excursion = max(-15, min(25, (mfe - mae) * 8))
    hit_adv = (hit - adverse) * 30
    score = sample + edge + excursion + hit_adv
    return int(max(0, min(100, round(score))))


def _eval_pattern(df: pd.DataFrame, symbol: str, tf: str, pattern: str, lookback: int, session: str) -> list[dict]:
    try:
        buy, sell = signals(df, pattern, lookback)
        sm = session_mask(df, session)
    except Exception:
        return []
    rows = []
    for side_name, sig, side in [("long", buy & sm, 1), ("short", sell & sm, -1)]:
        idx = np.flatnonzero(np.asarray(sig.fillna(False), dtype=bool))
        metrics = _future_metrics(df, idx, side, HORIZON.get(tf, 48))
        if metrics.empty or len(metrics) < (18 if tf != "D1" else 10):
            continue
        events = int(len(metrics))
        mean_forward = float(metrics.forward_R.mean())
        median_forward = float(metrics.forward_R.median())
        mean_mfe = float(metrics.mfe_R.mean())
        mean_mae = float(metrics.mae_R.mean())
        hit = float(metrics.hit_1R.mean())
        adverse = float(metrics.adverse_1R.mean())
        score = _score(events, mean_forward, median_forward, mean_mfe, mean_mae, hit, adverse)
        interp, proxy, liq = _describe(pattern, side_name)
        if score < 35 and mean_forward <= 0 and hit <= adverse:
            interp += " No clear positive inefficiency yet."
        elif score >= 70:
            interp += " Strong candidate inefficiency; route to strategy validation."
        elif score >= 50:
            interp += " Watchlist inefficiency; needs stricter validation."
        rows.append({
            "symbol": symbol, "tf": tf, "family": PATTERN_FAMILY.get(pattern, pattern), "pattern": pattern,
            "side": side_name, "lookback": lookback, "session": session, "events": events,
            "mean_forward_R": round(mean_forward, 5), "median_forward_R": round(median_forward, 5),
            "mean_mfe_R": round(mean_mfe, 5), "mean_mae_R": round(mean_mae, 5),
            "hit_1R_pct": round(hit, 4), "adverse_1R_pct": round(adverse, 4),
            "directional_asymmetry": round(hit - adverse, 4), "inefficiency_score": score,
            "interpretation": interp, "buyers_sellers_proxy": proxy, "where_liquidity_sits": liq,
            "caveat": "OHLC price-action proxy only; real order-book buyers/sellers require depth/order-flow data.",
        })
    return rows


def run_inefficiency_lab(scan_name: str | None = None, mode: str = "balanced", logger: Callable[[str], None] = print):
    if not FEATURE_CATALOG_PATH.exists():
        raise RuntimeError("No feature catalog found. Run Build Features first.")
    cat = pd.read_csv(FEATURE_CATALOG_PATH).replace([np.inf, -np.inf], np.nan).fillna("")
    if cat.empty:
        raise RuntimeError("Feature catalog is empty.")
    # Keep the profiler interactive: prioritize liquid symbols and meaningful timeframes.
    priority = {"XAUUSD", "NAS100", "US30", "GBPJPY", "EURUSD", "GBPUSD", "USDJPY", "XTIUSD", "USDCAD", "EURJPY", "AUDUSD"}
    cat = cat[cat.symbol.astype(str).str.upper().isin(priority)]
    if mode != "deep":
        cat = cat[cat.tf.astype(str).isin(["M15", "M30", "H1", "H4", "D1", "M5"])]
        cat = cat.head(36)
    rows: list[dict] = []
    datasets = []
    logger(f"Inefficiency lab started. datasets={len(cat)}, mode={mode}")
    for i, r in enumerate(cat.to_dict("records"), 1):
        symbol, tf = str(r.get("symbol", "")), str(r.get("tf", ""))
        fp = feature_path(symbol, tf)
        if not fp.exists():
            continue
        df = pd.read_pickle(fp).reset_index(drop=True)
        if mode != "deep" and tf in {"M1", "M5", "M15"} and len(df) > 90000:
            df = df.tail(90000).reset_index(drop=True)
        sessions = ["all"] if tf in {"H4", "D1"} else ["all", "london_ny", "ny"]
        lookbacks = [20, 50] if tf in {"H1", "H4", "D1"} else [12, 20, 48]
        patterns = PRIORITY_PATTERNS + (["asian_breakout"] if tf in {"M5", "M15", "M30", "H1"} else [])
        logger(f"[{i}/{len(cat)}] Profiling {symbol} {tf}: rows={len(df):,}")
        datasets.append({"symbol": symbol, "tf": tf, "rows": int(len(df)), "start": str(df.time.min()), "end": str(df.time.max())})
        for pattern in patterns:
            for lb in lookbacks:
                for sess in sessions:
                    rows.extend(_eval_pattern(df, symbol, tf, pattern, lb, sess))
    result_df = pd.DataFrame(rows)
    if not result_df.empty:
        result_df = result_df.sort_values(["inefficiency_score", "events"], ascending=[False, False])
    out_dir = OUTPUTS_DIR / (scan_name or "inefficiency_lab")
    out_dir.mkdir(parents=True, exist_ok=True)
    result_df = safe_to_csv(result_df, out_dir / "inefficiency_lab.csv", INEFFICIENCY_COLUMNS)
    top = result_df.head(50).replace([np.inf, -np.inf], np.nan).fillna("").to_dict("records") if not result_df.empty else []
    by_symbol = result_df.groupby("symbol").agg(best_score=("inefficiency_score", "max"), signals=("pattern", "count")).reset_index().sort_values("best_score", ascending=False).to_dict("records") if not result_df.empty else []
    by_family = result_df.groupby("family").agg(best_score=("inefficiency_score", "max"), signals=("pattern", "count")).reset_index().sort_values("best_score", ascending=False).to_dict("records") if not result_df.empty else []
    summary = {
        "scan_name": out_dir.name,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "datasets_profiled": len(datasets),
        "patterns_profiled": int(len(result_df)),
        "strong_inefficiencies": int((result_df.inefficiency_score >= 70).sum()) if not result_df.empty else 0,
        "watchlist_inefficiencies": int(((result_df.inefficiency_score >= 50) & (result_df.inefficiency_score < 70)).sum()) if not result_df.empty else 0,
        "datasets": datasets,
        "by_symbol": by_symbol,
        "by_family": by_family,
        "top": top,
        "warning": "This is a price-action/liquidity proxy from OHLC features. It infers likely liquidity pools and control shifts; it does not see real order book buyers/sellers.",
    }
    (out_dir / "INEFFICIENCY_LAB_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    INEFFICIENCY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger(f"Inefficiency lab complete: {summary['strong_inefficiencies']} strong, {summary['watchlist_inefficiencies']} watchlist")
    return summary


def read_inefficiency_lab(scan_name: str | None = None):
    if scan_name:
        p = OUTPUTS_DIR / scan_name / "INEFFICIENCY_LAB_SUMMARY.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    if INEFFICIENCY_PATH.exists():
        return json.loads(INEFFICIENCY_PATH.read_text(encoding="utf-8"))
    return {"datasets_profiled": 0, "patterns_profiled": 0, "strong_inefficiencies": 0, "watchlist_inefficiencies": 0, "top": [], "by_symbol": [], "by_family": [], "warning": "No inefficiency lab run yet."}
