"""Quick backtest of unconventional edge strategies on MT5 historical data.

Pulls last N bars from MT5 and runs each edge strategy through them,
reporting signal frequency, entry/exit quality, and estimated P&L.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime

from multitf_platform.strategy.edges.stat_arb import StatArbEngine
from multitf_platform.strategy.edges.session_momentum import SessionMomentumEngine
from multitf_platform.strategy.edges.gap_fade import GapFadeEngine


def backtest_stat_arb(pair: tuple, h1_data: dict, equity: float = 10000.0):
    """Backtest StatArb on historical H1 bars."""
    leg1, leg2 = pair
    engine = StatArbEngine(pair)
    
    h1_leg1 = h1_data[leg1]
    h1_leg2 = h1_data[leg2]
    min_len = min(len(h1_leg1), len(h1_leg2))
    
    signals = []
    trades = []
    in_position = False
    entry_z = 0.0
    
    for i in range(101, min_len):
        sig = engine.generate_signal(
            h1_leg1.iloc[:i], h1_leg2.iloc[:i], equity,
            h1_leg1.index[i-1]
        )
        signals.append({
            "time": h1_leg1.index[i-1],
            "z": sig.z_score,
            "status": sig.status.value,
            "spread": sig.spread,
        })
        
        # Track trade entries/exits
        if sig.is_active and not in_position:
            in_position = True
            entry_z = sig.z_score
            trades.append({
                "type": "entry",
                "time": sig.timestamp,
                "z": sig.z_score,
                "spread": sig.spread,
                "leg1_dir": sig.leg1_direction,
                "leg2_dir": sig.leg2_direction,
            })
        elif not sig.is_active and in_position:
            in_position = False
            trades.append({
                "type": "exit",
                "time": sig.timestamp,
                "z": sig.z_score,
                "spread": sig.spread,
            })
    
    # Calculate estimated P&L per trade (simplified: spread convergence)
    pnl = []
    for i in range(0, len(trades), 2):
        if i+1 < len(trades):
            entry = trades[i]
            exit_ = trades[i+1]
            spread_change = abs(entry["spread"] - exit_["spread"])
            # Estimate $0.10 per pip per 0.01 lot, roughly $1 per trade
            est_pnl = spread_change * 10000 * 0.5  # rough estimate
            pnl.append(est_pnl)
    
    wins = sum(1 for p in pnl if p > 0)
    
    return {
        "pair": f"{leg1}/{leg2}",
        "total_signals": len(signals),
        "trades": len(pnl),
        "wins": wins,
        "losses": len(pnl) - wins,
        "win_rate": (wins / len(pnl) * 100) if pnl else 0,
        "avg_pnl": np.mean(pnl) if pnl else 0,
        "total_est_pnl": sum(pnl),
        "z_range": (min(s["z"] for s in signals), max(s["z"] for s in signals)) if signals else (0, 0),
    }


def backtest_session_momentum(symbol: str, h1_data: pd.DataFrame, equity: float = 10000.0):
    """Backtest Session Momentum on historical H1 bars."""
    engine = SessionMomentumEngine(symbol)
    
    signals = []
    entries = []
    
    for i in range(21, len(h1_data)):
        sig = engine.generate_signal(h1_data.iloc[:i], equity, h1_data.index[i-1])
        signals.append({
            "time": sig.timestamp,
            "direction": sig.direction,
            "range_ratio": sig.range_ratio,
            "session": str(sig.session),
        })
        if sig.is_active:
            entries.append(sig)
    
    # Count by session
    london = sum(1 for s in signals if "LONDON" in s["session"] and s["direction"] != 0)
    ny = sum(1 for s in signals if "NEW_YORK" in s["session"] and s["direction"] != 0)
    
    return {
        "symbol": symbol,
        "total_bars": len(h1_data),
        "session_signals": len(entries),
        "london_signals": london,
        "ny_signals": ny,
        "avg_range_ratio": np.mean([s["range_ratio"] for s in signals if s["direction"] != 0]) if signals else 0,
    }


def backtest_gap_fade(symbol: str, h1_data: pd.DataFrame, equity: float = 10000.0):
    """Backtest Gap Fade on historical H1 bars."""
    engine = GapFadeEngine(symbol)
    
    signals = []
    
    for i in range(21, len(h1_data)):
        sig = engine.generate_signal(h1_data.iloc[:i], equity, h1_data.index[i-1])
        signals.append({
            "time": sig.timestamp,
            "gap": sig.gap_size,
            "gap_atr": sig.gap_atr_ratio,
            "direction": sig.direction,
            "active": sig.is_active,
        })
    
    active_signals = [s for s in signals if s["active"]]
    
    return {
        "symbol": symbol,
        "total_bars": len(h1_data),
        "sunday_bars_checked": len(signals),
        "gap_signals": len(active_signals),
        "avg_gap_atr": np.mean([s["gap_atr"] for s in active_signals]) if active_signals else 0,
        "max_gap": max([abs(s["gap"]) for s in active_signals]) if active_signals else 0,
    }


def main():
    print("=" * 70)
    print("UNCONVENTIONAL EDGES — MT5 Historical Backtest")
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
    
    try:
        print("\n--- Pulling historical data ---")
        all_h1 = {}
        
        symbols_needed = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCHF", "XAUUSD", "USDJPY"]
        for sym in symbols_needed:
            try:
                h1, _ = adapter.get_data(sym, h1_bars=500, h4_bars=100)
                all_h1[sym] = h1
                print(f"  {sym}: {len(h1)} H1 bars")
            except Exception as e:
                print(f"  {sym}: ERROR — {e}")
        
        # --- StatArb ---
        print("\n" + "=" * 70)
        print("STATISTICAL ARBITRAGE")
        print("=" * 70)
        
        pairs = [("EURUSD", "GBPUSD"), ("AUDUSD", "NZDUSD"), ("EURUSD", "USDCHF")]
        for pair in pairs:
            if pair[0] in all_h1 and pair[1] in all_h1:
                result = backtest_stat_arb(pair, all_h1)
                print(f"\n  {result['pair']}:")
                print(f"    Trades: {result['trades']} | Wins: {result['wins']} | Losses: {result['losses']}")
                print(f"    Win Rate: {result['win_rate']:.1f}%")
                print(f"    Est. Total P&L: ${result['total_est_pnl']:+.2f}")
                print(f"    Z-Range: [{result['z_range'][0]:.2f}, {result['z_range'][1]:.2f}]")
        
        # --- Session Momentum ---
        print("\n" + "=" * 70)
        print("SESSION MOMENTUM")
        print("=" * 70)
        
        for sym in ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]:
            if sym in all_h1:
                result = backtest_session_momentum(sym, all_h1[sym])
                print(f"\n  {sym}:")
                print(f"    Session signals: {result['session_signals']}")
                print(f"    London: {result['london_signals']} | NY: {result['ny_signals']}")
        
        # --- Gap Fade ---
        print("\n" + "=" * 70)
        print("WEEKEND GAP FADE")
        print("=" * 70)
        
        for sym in ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]:
            if sym in all_h1:
                result = backtest_gap_fade(sym, all_h1[sym])
                print(f"\n  {sym}:")
                print(f"    Gap signals: {result['gap_signals']}")
                print(f"    Avg gap/ATR: {result['avg_gap_atr']:.2f}x")
        
        print("\n" + "=" * 70)
        print("Backtest complete.")
        print("=" * 70)
        
    finally:
        adapter.disconnect()
        print("MT5 disconnected.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
