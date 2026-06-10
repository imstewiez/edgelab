import sys
from pathlib import Path

import numpy as np
import pandas as pd

ENGINE = Path(__file__).resolve().parents[1] / "apps" / "engine"
sys.path.insert(0, str(ENGINE))

from quantlab_core import backtest, filter_by_setup_keys, row_setup_id


def sample_df(rows=320):
    t = pd.date_range("2024-01-01", periods=rows, freq="h")
    base = np.linspace(100.0, 120.0, rows)
    return pd.DataFrame({
        "time": t,
        "open": base,
        "high": base + 0.8,
        "low": base - 0.8,
        "close": base + 0.2,
        "atr14": np.full(rows, 1.0),
        "year": t.year,
        "month": t.month,
        "spread_points": np.full(rows, 10),
    })


def test_setup_id_is_stable_for_numeric_formatting():
    a = {"symbol": "XAUUSD", "tf": "H1", "concept": "breakout", "session": "all", "lookback": 20, "rr": 1.0, "sl_mult": 1.4}
    b = {"symbol": "XAUUSD", "tf": "H1", "concept": "breakout", "session": "all", "lookback": "20", "rr": "1", "sl_mult": "1.4000"}
    assert row_setup_id(a) == row_setup_id(b)


def test_filter_by_setup_keys_uses_full_variant_identity():
    source = pd.DataFrame([
        {"symbol": "XAUUSD", "tf": "H1", "concept": "breakout", "session": "all", "lookback": 20, "rr": 1.0, "sl_mult": 1.0},
        {"symbol": "XAUUSD", "tf": "H1", "concept": "breakout", "session": "ny", "lookback": 20, "rr": 1.0, "sl_mult": 1.0},
    ])
    gate = source.iloc[[1]].copy()
    filtered = filter_by_setup_keys(source, gate)
    assert len(filtered) == 1
    assert filtered.iloc[0]["session"] == "ny"


def test_backtest_outputs_rich_trade_ledger():
    df = sample_df()
    buy = pd.Series(False, index=df.index)
    sell = pd.Series(False, index=df.index)
    buy.iloc[260] = True
    trades = backtest(df, buy, sell, rr=1.0, slm=1.0, horizon=5, symbol="XAUUSD")
    assert len(trades) >= 1
    for col in ["entry_time", "exit_time", "side", "entry_price", "exit_price", "sl", "tp", "exit_reason", "cost_r", "spread_points_used", "R"]:
        assert col in trades.columns
    assert trades.iloc[0]["cost_r"] > 0
