from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "data"
BROKER_PROFILE_PATH = STORE / "broker_profile.json"

DEFAULT_PROFILE: dict[str, Any] = {
    "name": "generic_mt5_cfd",
    "description": "Conservative local defaults. Override in data/broker_profile.json with broker-specific values.",
    "default_cost_r": 0.04,
    "default_spread_points": 20,
    "default_slippage_points": 2,
    "commission_r": 0.0,
    "symbols": {
        "XAUUSD": {"point_size": 0.01, "default_spread_points": 25, "default_slippage_points": 8},
        "NAS100": {"point_size": 0.1, "default_spread_points": 20, "default_slippage_points": 5},
        "US30": {"point_size": 1.0, "default_spread_points": 5, "default_slippage_points": 2},
        "XTIUSD": {"point_size": 0.01, "default_spread_points": 6, "default_slippage_points": 2},
        "EURUSD": {"point_size": 0.00001, "default_spread_points": 12, "default_slippage_points": 2},
        "GBPUSD": {"point_size": 0.00001, "default_spread_points": 16, "default_slippage_points": 2},
        "USDJPY": {"point_size": 0.001, "default_spread_points": 14, "default_slippage_points": 2},
        "GBPJPY": {"point_size": 0.001, "default_spread_points": 28, "default_slippage_points": 3},
        "EURJPY": {"point_size": 0.001, "default_spread_points": 18, "default_slippage_points": 2},
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_broker_profile() -> dict[str, Any]:
    if not BROKER_PROFILE_PATH.exists():
        return DEFAULT_PROFILE
    try:
        user_profile = json.loads(BROKER_PROFILE_PATH.read_text(encoding="utf-8"))
        if not isinstance(user_profile, dict):
            return DEFAULT_PROFILE
        return deep_merge(DEFAULT_PROFILE, user_profile)
    except Exception:
        return DEFAULT_PROFILE


def symbol_profile(symbol: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or load_broker_profile()
    sym = str(symbol or "").upper()
    symbols = profile.get("symbols", {}) if isinstance(profile.get("symbols"), dict) else {}
    merged = {
        "point_size": infer_point_size(sym),
        "default_spread_points": profile.get("default_spread_points", 20),
        "default_slippage_points": profile.get("default_slippage_points", 2),
        "default_cost_r": profile.get("default_cost_r", 0.04),
        "commission_r": profile.get("commission_r", 0.0),
    }
    if sym in symbols and isinstance(symbols[sym], dict):
        merged = deep_merge(merged, symbols[sym])
    return merged


def infer_point_size(symbol: str) -> float:
    sym = str(symbol or "").upper()
    if "JPY" in sym:
        return 0.001
    if sym.startswith("XAU") or sym.startswith("XAG") or sym.startswith("XTI"):
        return 0.01
    if sym in {"US30", "DJ30"}:
        return 1.0
    if any(x in sym for x in ["NAS", "SPX", "US500", "GER", "DAX"]):
        return 0.1
    return 0.00001
