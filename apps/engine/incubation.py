from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from pipeline_io import INCUBATION_COLUMNS, MC_COLUMNS, PERMUTATION_COLUMNS, PORTFOLIO_COLUMNS, SENSITIVITY_COLUMNS, safe_read_csv, safe_to_csv
from quantlab_core import STORE, OUTPUTS_DIR

INCUBATION_DIR = STORE / "incubation"
INCUBATION_PATH = INCUBATION_DIR / "incubation_candidates.csv"


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


def _load_existing() -> pd.DataFrame:
    INCUBATION_DIR.mkdir(parents=True, exist_ok=True)
    return safe_read_csv(INCUBATION_PATH, INCUBATION_COLUMNS)


def _source(out: Path) -> pd.DataFrame:
    for fn, status_col, ok, cols in [
        ("stage8_permutation_test.csv", "permutation_status", "perm_pass|perm_watchlist", PERMUTATION_COLUMNS),
        ("stage7_portfolio_risk.csv", "portfolio_status", "portfolio_pass|portfolio_watchlist", PORTFOLIO_COLUMNS),
        ("stage6_sensitivity.csv", "sensitivity_status", "sensitivity_pass|sensitivity_watchlist", SENSITIVITY_COLUMNS),
        ("stage5_monte_carlo.csv", "mc_status", "mc_pass|mc_watchlist", MC_COLUMNS),
    ]:
        p = out / fn
        if not p.exists():
            continue
        df = safe_read_csv(p, cols)
        if df.empty:
            continue
        if status_col in df.columns:
            df = df[df[status_col].astype(str).str.contains(ok, case=False, regex=True)]
        if not df.empty:
            return df.head(40).copy()
    return pd.DataFrame()


def seed_incubation(scan_name: str | None = None, logger: Callable[[str], None] = print):
    out = _run_dir(scan_name)
    src = _source(out)
    existing = _load_existing()
    if src.empty:
        safe_to_csv(existing, INCUBATION_PATH, INCUBATION_COLUMNS)
        logger("Incubation skipped: no passing/watchlist setups found after validation gates.")
        return read_incubation(scan_name)
    existing_ids = set(existing.setup_id.astype(str)) if not existing.empty and "setup_id" in existing.columns else set()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for _, r in src.iterrows():
        sid = str(r.get("setup_id", ""))
        if not sid or sid in existing_ids:
            continue
        rows.append({
            "setup_id": sid,
            "scan_name": out.name,
            "symbol": r.get("symbol", ""),
            "tf": r.get("tf", ""),
            "concept": r.get("concept", ""),
            "session": r.get("session", ""),
            "lookback": r.get("lookback", ""),
            "rr": r.get("rr", ""),
            "sl_mult": r.get("sl_mult", ""),
            "incubation_status": "paper_incubation",
            "created_at": now,
            "updated_at": now,
            "paper_days": 0,
            "paper_trades": 0,
            "paper_sumR": 0,
            "paper_maxDD_R": 0,
            "paper_notes": "Seeded from research pipeline. Requires forward/paper evidence before EA-ready.",
            "promotion_rule": "Minimum 30 paper days, 30+ trades, positive R, controlled DD, no broker execution issues.",
        })
    combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True) if not existing.empty else pd.DataFrame(rows)
    combined = safe_to_csv(combined, INCUBATION_PATH, INCUBATION_COLUMNS)
    logger(f"Incubation seeded: {len(rows)} new setups, {len(combined)} total tracked")
    return read_incubation(scan_name)


def read_incubation(scan_name: str | None = None):
    df = _load_existing()
    if scan_name and not df.empty and "scan_name" in df.columns:
        df = df[df.scan_name.astype(str) == scan_name]
    summary = {
        "tracked": int(len(df)),
        "paper_incubation": int((df.incubation_status == "paper_incubation").sum()) if not df.empty and "incubation_status" in df.columns else 0,
        "small_live": int((df.incubation_status == "small_live").sum()) if not df.empty and "incubation_status" in df.columns else 0,
        "production": int((df.incubation_status == "production").sum()) if not df.empty and "incubation_status" in df.columns else 0,
        "demoted": int((df.incubation_status == "demoted").sum()) if not df.empty and "incubation_status" in df.columns else 0,
        "top": df.head(60).replace([np.inf, -np.inf], np.nan).fillna("").to_dict("records") if not df.empty else [],
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    return summary


def export_ea_candidates(scan_name: str | None = None):
    df = _load_existing()
    if df.empty:
        return {"exported": 0, "message": "No incubation rows available."}
    eligible = df[df.incubation_status.astype(str).isin(["small_live", "production"])] if "incubation_status" in df.columns else df.iloc[0:0]
    if scan_name and not eligible.empty:
        eligible = eligible[eligible.scan_name.astype(str) == scan_name]
    out = _run_dir(scan_name) if scan_name else OUTPUTS_DIR
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "warning": "EA export only includes small_live/production incubation statuses. Paper-only strategies are excluded.",
        "candidates": eligible.replace([np.inf, -np.inf], np.nan).fillna("").to_dict("records"),
    }
    target = out / "EA_CANDIDATES.json" if out.is_dir() else OUTPUTS_DIR / "EA_CANDIDATES.json"
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"exported": int(len(eligible)), "path": str(target), "message": "Export complete."}
