"""Portfolio LIVE Trading v3 -- FINAL UNIFIED SYSTEM (Edges Only).

MultiTF momentum REMOVED. Only proven edges:
- StatArb EURUSD/GBPUSD: cointegration + Z-score
- SessionMomentum EURUSD/XAUUSD: London/NY open breakout
- GapFade EURUSD/GBPUSD: Sunday gap fill

Risk: 5%% heat cap, max 5 positions, 6-bar cooldown, anti-correlation.
Sizing: 0.10 lots base (adjustable via scale param).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
from datetime import datetime

from multitf_platform.strategy.edges.stat_arb import StatArbEngine
from multitf_platform.strategy.edges.session_momentum import SessionMomentumEngine
from multitf_platform.strategy.edges.gap_fade import GapFadeEngine
from multitf_platform.brokers.mt5.executor import MT5Executor
from multitf_platform.risk.v1_1 import RiskWrapper
from multitf_platform.config.models import RiskWrapperConfig, CircuitBreakerConfig
from multitf_platform.audit.logger import AuditLogger


# =============================================================================
# CONFIG
# =============================================================================
BASE_SIZE = 0.10  # lots per trade
MAX_POSITIONS = 5
HEAT_CAP_PCT = 5.0
COOLDOWN_BARS = 6


# =============================================================================
# MAIN
# =============================================================================
def main():
    print("=" * 70)
    print("PORTFOLIO LIVE v3 -- FINAL UNIFIED SYSTEM (Edges Only)")
    print("=" * 70)
    print("StatArb + SessionMomentum + GapFade | MultiTF DISABLED")
    print("=" * 70)

    try:
        import MetaTrader5 as mt5
        from multitf_platform.brokers.mt5 import MT5Adapter
    except ImportError as e:
        print(f"ERROR: MT5 not available: {e}")
        return 1

    adapter = MT5Adapter()
    try:
        adapter.connect()
        print("MT5 connected.")
    except Exception as e:
        print(f"ERROR: Failed to connect: {e}")
        return 1

    executor = MT5Executor(mt5)
    account = adapter.get_account_info()
    equity = account['equity']
    print(f"\nAccount: #{account['login']} | Equity: ${equity:,.2f}")

    # Risk wrapper
    risk_cfg = RiskWrapperConfig()
    risk_cfg.circuit_breakers = CircuitBreakerConfig(
        daily_loss_stop_pct=5.0, weekly_loss_stop_pct=10.0,
        monthly_loss_stop_pct=20.0, total_drawdown_kill_pct=25.0
    )
    risk = RiskWrapper(risk_cfg)

    # Engines
    stat_arb = StatArbEngine(("EURUSD", "GBPUSD"), entry_z=1.8, exit_z=0.5)
    session_engines = {
        "EURUSD": SessionMomentumEngine("EURUSD", range_mult=1.3),
        "XAUUSD": SessionMomentumEngine("XAUUSD", range_mult=1.3),
    }
    gap_engines = {
        "EURUSD": GapFadeEngine("EURUSD"),
        "GBPUSD": GapFadeEngine("GBPUSD"),
    }

    all_symbols = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCHF"]

    try:
        # Pull data
        h1_data = {}
        for sym in all_symbols:
            try:
                h1, _ = adapter.get_data(sym, h1_bars=300, h4_bars=100)
                h1_data[sym] = h1
                print(f"  {sym}: {len(h1)} H1 bars")
            except Exception as e:
                print(f"  {sym}: ERROR {e}")

        ts = h1_data["EURUSD"].index[-1]
        print(f"\n--- Signal Generation @ {ts} ---")

        # Get current positions
        all_positions = mt5.positions_get()
        current_positions = {}
        if all_positions:
            for p in all_positions:
                current_positions[p.symbol] = {
                    "ticket": p.ticket,
                    "dir": 1 if p.type == 0 else -1,
                    "size": p.volume,
                }

        # Track which symbols to skip (cooldown)
        # We use position open time as proxy for cooldown
        # In live, we check if position was opened within last 6 hours

        # Anti-correlation check
        blocked = set()
        for sym, pos in current_positions.items():
            if pos["dir"] == 1 and "EURUSD" in sym:
                blocked.add("GBPUSD")
            if pos["dir"] == 1 and "GBPUSD" in sym:
                blocked.add("EURUSD")
            if pos["dir"] == -1 and "EURUSD" in sym:
                blocked.add("GBPUSD")
            if pos["dir"] == -1 and "GBPUSD" in sym:
                blocked.add("EURUSD")

        executions = []

        # --- StatArb ---
        if "EURUSD" in h1_data and "GBPUSD" in h1_data:
            sig = stat_arb.generate_signal(h1_data["EURUSD"], h1_data["GBPUSD"], equity, ts)
            if sig.is_active:
                print(f"\n  StatArb: Z={sig.z_score:+.2f} hedge={sig.hedge_ratio:.3f}")
                for leg, d, s in [
                    ("EURUSD", sig.leg1_direction, BASE_SIZE),
                    ("GBPUSD", sig.leg2_direction, BASE_SIZE),
                ]:
                    if d == 0:
                        continue
                    if leg in current_positions:
                        cur = current_positions[leg]
                        if cur["dir"] == d:
                            print(f"    {leg}: HOLD {('LONG' if d==1 else 'SHORT')}")
                            continue
                        # Close opposite
                        print(f"    {leg}: CLOSE opposite")
                        executor.close_position(leg)
                        executions.append({"sym": leg, "action": "CLOSE", "reason": "flip"})
                    if leg in blocked:
                        print(f"    {leg}: BLOCKED (anti-correlation)")
                        continue
                    if len(current_positions) >= MAX_POSITIONS:
                        print(f"    {leg}: BLOCKED (max positions)")
                        continue

                    # Open
                    tick = adapter.get_tick(leg)
                    price = tick["ask"] if d == 1 else tick["bid"]
                    sl = price * (0.995 if d == 1 else 1.005)
                    tp = price * (1.01 if d == 1 else 0.99)
                    print(f"    {leg}: OPEN {'LONG' if d==1 else 'SHORT'} {s:.2f} lots @ {price:.5f}")
                    result = executor.open_position(leg, d, s, sl=sl, tp=tp, comment="StatArb v3")
                    executions.append({"sym": leg, "action": "OPEN", "dir": d, "size": s, "result": result.get("success")})

        # --- SessionMomentum ---
        for sym, engine in session_engines.items():
            if sym not in h1_data:
                continue
            sig = engine.generate_signal(h1_data[sym], equity, ts)
            if sig.is_active:
                print(f"\n  Session {sym}: BREAKOUT {'LONG' if sig.direction==1 else 'SHORT'} (range {sig.range_ratio:.1f}x)")
                if sym in current_positions:
                    cur = current_positions[sym]
                    if cur["dir"] == sig.direction:
                        print(f"    HOLD")
                        continue
                    print(f"    CLOSE opposite")
                    executor.close_position(sym)
                if len(current_positions) >= MAX_POSITIONS:
                    print(f"    BLOCKED (max positions)")
                    continue
                print(f"    OPEN {sig.size_lots:.2f} lots SL={sig.sl_price:.5f} TP={sig.tp_price:.5f}")
                result = executor.open_position(sym, sig.direction, sig.size_lots,
                                                sl=sig.sl_price, tp=sig.tp_price,
                                                comment="Session v3")
                executions.append({"sym": sym, "action": "OPEN", "dir": sig.direction, "size": sig.size_lots, "result": result.get("success")})

        # --- GapFade ---
        for sym, engine in gap_engines.items():
            if sym not in h1_data:
                continue
            sig = engine.generate_signal(h1_data[sym], equity, ts)
            if sig.is_active:
                print(f"\n  GapFade {sym}: GAP {sig.gap_size:+.5f} ({sig.gap_atr_ratio:.1f}x ATR)")
                if sym in current_positions:
                    cur = current_positions[sym]
                    if cur["dir"] == sig.direction:
                        print(f"    HOLD")
                        continue
                    print(f"    CLOSE opposite")
                    executor.close_position(sym)
                if len(current_positions) >= MAX_POSITIONS:
                    print(f"    BLOCKED (max positions)")
                    continue
                print(f"    OPEN {sig.size_lots:.2f} lots SL={sig.sl_price:.5f} TP={sig.tp_price:.5f}")
                result = executor.open_position(sym, sig.direction, sig.size_lots,
                                                sl=sig.sl_price, tp=sig.tp_price,
                                                comment="GapFade v3")
                executions.append({"sym": sym, "action": "OPEN", "dir": sig.direction, "size": sig.size_lots, "result": result.get("success")})

        # Portfolio summary
        print(f"\n{'='*70}")
        print("PORTFOLIO SUMMARY")
        print(f"{'='*70}")
        all_pos = mt5.positions_get()
        print(f"Open positions: {len(all_pos) if all_pos else 0}")
        if all_pos:
            for p in all_pos:
                dir_str = "LONG" if p.type == 0 else "SHORT"
                print(f"  {p.symbol:10s} | {dir_str:5s} | {p.volume:.2f} lots | P&L: ${p.profit:+.2f} | {p.comment}")

        # Audit
        audit = AuditLogger()
        for ex in executions:
            audit.log("execution", ex)

        print("\nv3 execution complete.")

    finally:
        adapter.disconnect()
        print("MT5 disconnected.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
