from __future__ import annotations

import os
from pathlib import Path

import pandas as pd


def env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except Exception:
        return default


LIMITS = {
    "validation": env_int("EDGELAB_VALIDATION_LIMIT", 250),
    "walkforward": env_int("EDGELAB_WALKFORWARD_LIMIT", 50),
    "stress": env_int("EDGELAB_STRESS_LIMIT", 35),
    "monte_carlo": env_int("EDGELAB_MC_LIMIT", 30),
    "sensitivity": env_int("EDGELAB_SENSITIVITY_LIMIT", 20),
    "portfolio": env_int("EDGELAB_PORTFOLIO_LIMIT", 25),
    "permutation": env_int("EDGELAB_PERMUTATION_LIMIT", 15),
}

SCORE_COLUMNS = [
    "permutation_score", "portfolio_score", "sensitivity_score", "mc_score", "stress_pass_rate",
    "wf_score", "robustness_score", "score", "test_pf", "pf", "expR", "positive_month_pct",
]


def sort_candidates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    sort_cols = []
    ascending = []
    for col in SCORE_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
            sort_cols.append(col)
            ascending.append(False)
    if sort_cols:
        out = out.sort_values(sort_cols, ascending=ascending, na_position="last")
    return out


def limit_candidates(df: pd.DataFrame, stage: str, logger=None) -> pd.DataFrame:
    if df.empty:
        return df
    limit = LIMITS.get(stage, len(df))
    sorted_df = sort_candidates(df)
    if len(sorted_df) > limit and logger:
        logger(f"Stage gate: keeping top {limit}/{len(sorted_df)} candidates for {stage}. Set EDGELAB_{stage.upper()}_LIMIT to override.")
    return sorted_df.head(limit).copy()


def read_run_meta(run_dir: Path) -> dict:
    meta = {}
    p = run_dir / "run_meta.json"
    if p.exists():
        try:
            import json
            meta = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    return meta
