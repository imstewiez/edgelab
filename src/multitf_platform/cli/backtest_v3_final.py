"""FINAL UNIFIED v3 -- Edges Only (No MultiTF).

Proven edges integrated into ONE engine:
- StatArb EURUSD/GBPUSD: cointegration + Z-score mean reversion
- SessionMomentum EURUSD/XAUUSD: London/NY open breakout
- GapFade EURUSD/GBPUSD: Sunday gap fill

Risk Management:
- Portfolio heat cap: 5%
- Max 5 open positions
- 6-bar cooldown between trades on same symbol
- Anti-correlation: EURUSD/GBPUSD cannot both be long or both short
- Vol-adjusted sizing: 0.10 lots base, reduced in high vol
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict, List

from multitf_platform.strategy.edges.stat_arb import StatArbEngine
from multitf_platform.strategy.edges.session_momentum import SessionMomentumEngine
from multitf_platform.strategy.edges.gap_fade import GapFadeEngine
from multitf_platform.brokers.mt5 import MT5Adapter

# =============================================================================
# CONFIG
# =============================================================================
INITIAL = 10300.0
COMM = 7.0
SLIP_PIPS = 0.5
MAX_POS = 5
HEAT_CAP = 5.0
COOLDOWN = 6
BASE_SIZE = 0.10

# =============================================================================
# HELPERS
# =============================================================================
def point_size(sym):
    if any(x in sym for x in ["XAU","JPY","NAS","GER","US30"]):
        return 0.01
    return 0.0001

def pip_val(sym):
    if "XAU" in sym or "NAS" in sym or "GER" in sym or "US30" in sym:
        return 1.0
    elif "JPY" in sym:
        return 1000.0
    return 10.0

def calc_pnl(entry, exit_, direction, size, sym):
    pips = ((exit_ - entry) * direction) / point_size(sym)
    return pips * (pip_val(sym) / 100.0) * size

# =============================================================================
# MAIN BACKTEST
# =============================================================================
def main():
    print("=" * 70)
    print("FINAL UNIFIED v3 -- Edges Only (StatArb + Session + GapFade)")
    print("=" * 70)
    print(f"Initial: ${INITIAL:,.2f} | Comm: ${COMM}/lot | Slip: {SLIP_PIPS}p")
    print(f"Max pos: {MAX_POS} | Heat cap: {HEAT_CAP}% | Cooldown: {COOLDOWN} bars")
    print("=" * 70)

    adapter = MT5Adapter()
    adapter.connect()
    print("MT5 connected.\n")

    symbols = ["EURUSD","GBPUSD","XAUUSD","USDJPY","AUDUSD","NZDUSD","USDCHF"]
    h1_data = {}
    for sym in symbols:
        try:
            h1, _ = adapter.get_data(sym, h1_bars=3000, h4_bars=500)
            h1_data[sym] = h1
            print(f"  {sym}: {len(h1)} H1 bars")
        except Exception as e:
            print(f"  {sym}: ERROR {e}")

    MIN_LEN = min(len(h1_data[s]) for s in h1_data)

    # Engines
    sa = StatArbEngine(("EURUSD","GBPUSD"), entry_z=1.8, exit_z=0.5)
    se = {"EURUSD": SessionMomentumEngine("EURUSD", range_mult=1.3),
          "XAUUSD": SessionMomentumEngine("XAUUSD", range_mult=1.3)}
    gf = {"EURUSD": GapFadeEngine("EURUSD"),
          "GBPUSD": GapFadeEngine("GBPUSD")}

    cash = INITIAL
    positions = {}  # sym -> {dir, entry, size, sl, tp, bar, strat}
    trades = []
    equity_curve = []
    last_trade = {}

    for i in range(100, MIN_LEN):
        ts = h1_data["EURUSD"].index[i]
        prices = {s: h1_data[s]["close"].iloc[i] for s in h1_data}

        # 1. SL/TP check
        to_close = []
        for sym, pos in list(positions.items()):
            p = prices[sym]
            if pos["dir"] == 1:
                if p <= pos["sl"] or p >= pos["tp"]:
                    to_close.append(sym)
            else:
                if p >= pos["sl"] or p <= pos["tp"]:
                    to_close.append(sym)
        for sym in to_close:
            pos = positions.pop(sym)
            p = prices[sym]
            slip = SLIP_PIPS * point_size(sym)
            fill = p - (slip * pos["dir"])
            pnl = calc_pnl(pos["entry"], fill, pos["dir"], pos["size"], sym)
            cash += pnl - COMM * pos["size"]
            trades.append({"pnl": pnl - COMM * pos["size"], "strat": pos["strat"], "sym": sym})

        # 2. Generate signals
        signals = []

        # StatArb
        sig = sa.generate_signal(h1_data["EURUSD"].iloc[:i+1], h1_data["GBPUSD"].iloc[:i+1], INITIAL, ts)
        if sig.is_active:
            for leg, d, s in [("EURUSD", sig.leg1_direction, BASE_SIZE), ("GBPUSD", sig.leg2_direction, BASE_SIZE)]:
                p = prices[leg]
                sl = p * (0.995 if d == 1 else 1.005)
                tp = p * (1.01 if d == 1 else 0.99)
                signals.append({"sym": leg, "dir": d, "size": s, "sl": sl, "tp": tp, "strat": "StatArb"})

        # Session
        for sym, engine in se.items():
            sig = engine.generate_signal(h1_data[sym].iloc[:i+1], INITIAL, ts)
            if sig.is_active:
                signals.append({"sym": sym, "dir": sig.direction, "size": BASE_SIZE,
                               "sl": sig.sl_price, "tp": sig.tp_price, "strat": "Session"})

        # GapFade
        for sym, engine in gf.items():
            sig = engine.generate_signal(h1_data[sym].iloc[:i+1], INITIAL, ts)
            if sig.is_active:
                signals.append({"sym": sym, "dir": sig.direction, "size": BASE_SIZE,
                               "sl": sig.sl_price, "tp": sig.tp_price, "strat": "GapFade"})

        # 3. Portfolio filters
        # Heat check
        total_risk = 0.0
        for sym, pos in positions.items():
            r = abs(pos["entry"] - pos["sl"]) / point_size(sym) * (pip_val(sym)/100.0) * pos["size"]
            total_risk += r

        # Anti-correlation
        blocked = set()
        for sym, pos in positions.items():
            if pos["dir"] == 1 and "EURUSD" in sym:
                blocked.add("GBPUSD")
            if pos["dir"] == 1 and "GBPUSD" in sym:
                blocked.add("EURUSD")
            if pos["dir"] == -1 and "EURUSD" in sym:
                blocked.add("GBPUSD")
            if pos["dir"] == -1 and "GBPUSD" in sym:
                blocked.add("EURUSD")

        # 4. Execute
        for sig in signals:
            sym = sig["sym"]
            if sym in positions:
                continue
            if sym in blocked:
                continue
            if sym in last_trade and (i - last_trade[sym]) < COOLDOWN:
                continue
            if len(positions) >= MAX_POS:
                continue

            # Heat check
            r = abs(prices[sym] - sig["sl"]) / point_size(sym) * (pip_val(sym)/100.0) * sig["size"]
            if (total_risk + r) / INITIAL * 100 > HEAT_CAP:
                # Try half size
                sig["size"] = max(0.01, round(sig["size"] / 2, 2))
                r = r / 2
                if (total_risk + r) / INITIAL * 100 > HEAT_CAP:
                    continue

            # Open
            p = prices[sym]
            slip = SLIP_PIPS * point_size(sym)
            fill = p + (slip * sig["dir"])
            cash -= COMM * sig["size"]
            positions[sym] = {"dir": sig["dir"], "entry": fill, "size": sig["size"],
                             "sl": sig["sl"], "tp": sig["tp"], "bar": i, "strat": sig["strat"]}
            last_trade[sym] = i
            total_risk += r

        # Mark to market
        unrealized = 0.0
        for sym, pos in positions.items():
            if sym in prices:
                pnl = calc_pnl(pos["entry"], prices[sym], pos["dir"], pos["size"], sym)
                unrealized += pnl
        equity = cash + unrealized
        equity_curve.append({"time": ts, "equity": equity})

    # Close all
    for sym, pos in list(positions.items()):
        if sym in prices:
            slip = SLIP_PIPS * point_size(sym)
            fill = prices[sym] - (slip * pos["dir"])
            pnl = calc_pnl(pos["entry"], fill, pos["dir"], pos["size"], sym)
            cash += pnl - COMM * pos["size"]
            trades.append({"pnl": pnl - COMM * pos["size"], "strat": pos["strat"], "sym": sym})

    # Metrics
    eq = pd.DataFrame(equity_curve)
    eq.set_index("time", inplace=True)
    returns = eq["equity"].pct_change().dropna()
    ann_ret = returns.mean() * 252 * 24 * 100 if len(returns) > 0 else 0
    ann_vol = returns.std() * np.sqrt(252 * 24) * 100 if len(returns) > 0 else 0
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    peak = eq["equity"].expanding().max()
    max_dd = ((eq["equity"] - peak) / peak).min() * 100

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    strat_pnl = {}
    for t in trades:
        strat_pnl[t["strat"]] = strat_pnl.get(t["strat"], 0) + t["pnl"]

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"  Initial Equity:    ${INITIAL:,.2f}")
    print(f"  Final Equity:      ${eq['equity'].iloc[-1]:,.2f}")
    print(f"  Total Return:      {(eq['equity'].iloc[-1]/INITIAL-1)*100:+.2f}%")
    print(f"  Ann. Return:       {ann_ret:+.2f}%")
    print(f"  Ann. Volatility:   {ann_vol:.2f}%")
    print(f"  Sharpe Ratio:      {sharpe:.3f}")
    print(f"  Max Drawdown:      {max_dd:.2f}%")
    print(f"\n  Total Trades:      {len(pnls)}")
    print(f"  Win Rate:          {len(wins)/len(pnls)*100 if pnls else 0:.1f}%")
    print(f"  Avg Win:           ${np.mean(wins) if wins else 0:+.2f}")
    print(f"  Avg Loss:          ${np.mean([abs(p) for p in losses]) if losses else 0:-.2f}")
    pf = sum(wins) / sum(abs(p) for p in losses) if losses else 0
    print(f"  Profit Factor:     {pf:.2f}")
    print(f"  Total P&L:         ${sum(pnls):+.2f}")

    print(f"\n--- Per-Strategy ---")
    for s, pnl in sorted(strat_pnl.items(), key=lambda x: -x[1]):
        print(f"  {s:12s}: ${pnl:+.2f}")

    eq.to_csv("state/backtest_v3_final_equity.csv")
    print(f"\nEquity curve: state/backtest_v3_final_equity.csv")

    adapter.disconnect()
    return 0

if __name__ == "__main__":
    sys.exit(main())
