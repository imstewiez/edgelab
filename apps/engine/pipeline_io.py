from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

EDGE_COLUMNS = [
    "setup_id", "symbol", "tf", "concept", "lookback", "session", "rr", "sl_mult",
    "n", "sumR", "expR", "pf", "winrate", "maxDD_R", "max_loss_streak",
    "test_pf", "test_n", "positive_month_pct", "avg_cost_R", "broker_profile",
    "score", "status", "grade", "verdict",
]

VALIDATION_COLUMNS = [
    "setup_id", "symbol", "tf", "concept", "lookback", "session", "rr", "sl_mult",
    "n", "pf", "test_pf", "expR", "maxDD_R", "winrate", "positive_month_pct",
    "max_loss_streak", "avg_cost_R", "robustness_score", "robustness_status", "verdict", "ea_ready",
]

WF_COLUMNS = [
    "setup_id", "symbol", "tf", "concept", "lookback", "session", "rr", "sl_mult",
    "n", "pf", "test_pf", "expR", "maxDD_R", "positive_month_pct", "avg_cost_R",
    "wf_status", "wf_score", "wf_windows", "wf_pass_rate", "wf_median_pf", "wf_min_pf", "wf_verdict",
]

STRESS_COLUMNS = [
    "setup_id", "symbol", "tf", "concept", "lookback", "session", "rr", "sl_mult",
    "trades", "base_pf", "base_test_pf", "base_expR", "base_maxDD_R",
    "pf", "test_pf", "expR", "maxDD_R", "stress_status", "stress_pass_rate", "worst_test_pf", "verdict",
]

MC_COLUMNS = [
    "setup_id", "symbol", "tf", "concept", "session", "lookback", "rr", "sl_mult",
    "trades", "mc_status", "mc_score", "profit_probability", "p05_totalR", "p95_dd_R", "ruin_probability", "verdict",
]

SENSITIVITY_COLUMNS = [
    "setup_id", "symbol", "tf", "concept", "session", "lookback", "rr", "sl_mult",
    "variants_tested", "variants_passed", "pass_rate", "median_pf", "min_pf", "median_expR", "maxDD_R",
    "sensitivity_score", "sensitivity_status", "verdict",
]

PORTFOLIO_COLUMNS = [
    "setup_id", "symbol", "tf", "concept", "session", "lookback", "rr", "sl_mult",
    "trades", "sumR", "avg_abs_corr", "standalone_monthly_dd_R", "portfolio_score", "portfolio_status", "verdict",
]

PERMUTATION_COLUMNS = [
    "setup_id", "symbol", "tf", "concept", "session", "lookback", "rr", "sl_mult",
    "real_trades", "real_sumR", "real_pf", "random_median_sumR", "random_p95_sumR",
    "sumR_percentile", "pf_percentile", "p_value_approx", "iterations", "permutation_score", "permutation_status", "verdict",
]

EVENT_COLUMNS = [
    "setup_id", "symbol", "tf", "concept", "session", "lookback", "rr", "sl_mult",
    "event_time", "entry_time", "side", "hour", "weekday", "atr_rank_500", "range_rank_200",
    "ema21_slope_atr", "wick_pressure", "rsi14", "compression", "outcome", "forward_R", "mfe_R", "mae_R",
]

EVENT_SUMMARY_COLUMNS = [
    "setup_id", "symbol", "tf", "concept", "session", "lookback", "rr", "sl_mult",
    "events", "long_events", "short_events", "tp_first_pct", "sl_first_pct", "timeout_pct",
    "mean_forward_R", "median_forward_R", "mean_mfe_R", "mean_mae_R", "event_status", "verdict",
]

INCUBATION_COLUMNS = [
    "setup_id", "scan_name", "symbol", "tf", "concept", "session", "lookback", "rr", "sl_mult",
    "incubation_status", "created_at", "updated_at", "paper_days", "paper_trades", "paper_sumR",
    "paper_maxDD_R", "paper_notes", "promotion_rule",
]


def safe_read_csv(path: Path, columns: Iterable[str] | None = None) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=list(columns or []))
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=list(columns or []))
    return df.replace([np.inf, -np.inf], np.nan).fillna("")


def safe_to_csv(df: pd.DataFrame | list[dict], path: Path, columns: Iterable[str] | None = None) -> pd.DataFrame:
    cols = list(columns or [])
    if isinstance(df, list):
        out = pd.DataFrame(df)
    else:
        out = df.copy()
    if out.empty and cols:
        out = pd.DataFrame(columns=cols)
    elif cols:
        for c in cols:
            if c not in out.columns:
                out[c] = ""
        extras = [c for c in out.columns if c not in cols]
        out = out[cols + extras]
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    return out
