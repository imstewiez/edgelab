"""UNIFIED SYSTEM v3 -- ONE COHESIVE ENGINE.

Core innovation: Each edge ONLY trades in its FAVORED regime.
- StatArb -> only in RANGING / QUIET markets (spreads mean-revert)
- SessionMomentum -> only in TRENDING markets with ATR expansion
- GapFade -> only Sundays (always)

Adaptive sizing: volatility targeting (bigger when calm, smaller when volatile).
Portfolio heat: max 3% risk. Max 3 open positions. 6-bar cooldown.
Anti-correlation: blocks long EURUSD + long GBPUSD simultaneously.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum

from multitf_platform.strategy.edges.stat_arb import StatArbEngine
from multitf_platform.strategy.edges.session_momentum import SessionMomentumEngine
from multitf_platform.strategy.edges.gap_fade import GapFadeEngine
from multitf_platform.brokers.mt5 import MT5Adapter


# =============================================================================
# CONFIG
# =============================================================================

INITIAL_EQUITY = 10300.0
COMMISSION = 7.0
SLIPPAGE_PIPS = 0.5
MAX_POSITIONS = 3
HEAT_CAP_PCT = 3.0
COOLDOWN_BARS = 6

class Regime(Enum):
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    QUIET = "quiet"


# =============================================================================
# UNIFIED ENGINE
# =============================================================================

@dataclass
class UnifiedSignal:
    symbol: str
    direction: int  # 1=LONG, -1=SHORT, 0=FLAT
    size_lots: float
    sl: float
    tp: float
    confidence: float  # 0.0 - 1.0
    strategy: str
    reason: str = ""


class UnifiedEngine:
    """One engine that routes each edge to its favored regime."""
    
    def __init__(self, equity: float = INITIAL_EQUITY):
        self.equity = equity
        self.stat_arb = StatArbEngine(("EURUSD", "GBPUSD"), entry_z=1.8, exit_z=0.5)
        self.session = {
            "EURUSD": SessionMomentumEngine("EURUSD", range_mult=1.3),
            "XAUUSD": SessionMomentumEngine("XAUUSD", range_mult=1.3),
        }
        self.gap = {
            "EURUSD": GapFadeEngine("EURUSD"),
            "GBPUSD": GapFadeEngine("GBPUSD"),
        }
    
    def detect_regime(self, h1: pd.DataFrame) -> Tuple[Regime, float]:
        """Detect market regime using ADX + ATR percentiles."""
        if len(h1) < 50:
            return Regime.QUIET, 0.5
        
        # ATR percentile
        atr = (h1["high"] - h1["low"]).rolling(20).mean()
        atr_pct = atr / h1["close"]
        current = atr_pct.iloc[-1]
        hist = atr_pct.dropna()
        if len(hist) < 50:
            return Regime.QUIET, 0.5
        
        p = np.percentile(hist, [20, 50, 80])
        atr_score = np.searchsorted(p, current) / 3.0  # 0=low, 1=high
        
        # Simple ADX-like: trend strength via directional movement
        plus_dm = h1["high"].diff()
        minus_dm = -h1["low"].diff()
        plus_dm = plus_dm.clip(lower=0)
        minus_dm = minus_dm.clip(lower=0)
        
        # Trend score: how directional are recent 10 bars
        returns = h1["close"].pct_change().tail(10)
        trend_score = abs(returns.sum()) / (returns.abs().sum() + 1e-9)
        
        if atr_score > 0.8:
            regime = Regime.VOLATILE
        elif atr_score < 0.3 and trend_score < 0.3:
            regime = Regime.QUIET
        elif trend_score > 0.5:
            regime = Regime.TRENDING
        else:
            regime = Regime.RANGING
        
        return regime, atr_score
    
    def calc_adaptive_size(self, base_size: float, atr_score: float, regime: Regime) -> float:
        """Volatility targeting: bigger when calm, smaller when volatile."""
        # ATR multiplier: low vol = 1.5x, high vol = 0.5x
        if atr_score < 0.3:
            vol_mult = 1.5
        elif atr_score > 0.7:
            vol_mult = 0.5
        else:
            vol_mult = 1.0
        
        # Regime multiplier
        if regime == Regime.RANGING:
            regime_mult = 1.2
        elif regime == Regime.TRENDING:
            regime_mult = 1.0
        else:
            regime_mult = 0.8
        
        size = base_size * vol_mult * regime_mult
        return max(0.01, min(1.0, round(size, 2)))
    
    def generate_signals(
        self, i: int, ts: pd.Timestamp, h1_data: dict, h4_data: dict
    ) -> List[UnifiedSignal]:
        """Generate ALL signals for this bar."""
        signals = []
        hour = ts.hour
        weekday = ts.weekday()
        
        # --- StatArb: ONLY in RANGING or QUIET ---
        if "EURUSD" in h1_data and "GBPUSD" in h1_data:
            regime_eur, atr_eur = self.detect_regime(h1_data["EURUSD"])
            if regime_eur in (Regime.RANGING, Regime.QUIET):
                sig = self.stat_arb.generate_signal(
                    h1_data["EURUSD"].iloc[:i+1],
                    h1_data["GBPUSD"].iloc[:i+1],
                    self.equity, ts
                )
                if sig.is_active:
                    for leg, leg_dir, leg_size in [
                        ("EURUSD", sig.leg1_direction, sig.leg1_size),
                        ("GBPUSD", sig.leg2_direction, sig.leg2_size),
                    ]:
                        size = self.calc_adaptive_size(leg_size, atr_eur, regime_eur)
                        conf = min(1.0, abs(sig.z_score) / 3.0)
                        price = h1_data[leg]["close"].iloc[i]
                        sl = price * (0.995 if leg_dir == 1 else 1.005)
                        tp = price * (1.01 if leg_dir == 1 else 0.99)
                        signals.append(UnifiedSignal(leg, leg_dir, size, sl, tp, conf, "StatArb"))
        
        # --- SessionMomentum: ONLY in TRENDING, ONLY at session open ---
        is_session = (8 <= hour < 9) or (13 <= hour < 14)
        if is_session:
            for sym, engine in self.session.items():
                if sym not in h1_data:
                    continue
                regime, atr_score = self.detect_regime(h1_data[sym])
                if regime == Regime.TRENDING:
                    sig = engine.generate_signal(h1_data[sym].iloc[:i+1], self.equity, ts)
                    if sig.is_active:
                        conf = min(1.0, sig.range_ratio / 3.0)
                        size = self.calc_adaptive_size(sig.size_lots, atr_score, regime)
                        signals.append(UnifiedSignal(
                            sym, sig.direction, size,
                            sig.sl_price, sig.tp_price, conf, "Session"
                        ))
        
        # --- GapFade: ONLY Sundays 22-23h ---
        if weekday == 6 and 22 <= hour < 23:
            for sym, engine in self.gap.items():
                if sym not in h1_data:
                    continue
                sig = engine.generate_signal(h1_data[sym].iloc[:i+1], self.equity, ts)
                if sig.is_active:
                    conf = min(1.0, sig.gap_atr_ratio / 2.0)
                    size = self.calc_adaptive_size(sig.size_lots, 0.5, Regime.QUIET)
                    signals.append(UnifiedSignal(
                        sym, sig.direction, size,
                        sig.sl_price, sig.tp_price, conf, "GapFade"
                    ))
        
        # Filter by confidence
        signals = [s for s in signals if s.confidence >= 0.5]
        
        return signals


# =============================================================================
# SIMULATION
# =============================================================================

@dataclass
class SimPos:
    symbol: str
    direction: int
    entry: float
    size: float
    sl: float
    tp: float
    bar: int
    strategy: str


def point_size(sym: str) -> float:
    if "XAU" in sym or "JPY" in sym or "NAS" in sym or "GER" in sym or "US30" in sym:
        return 0.01
    return 0.0001


def pip_value_per_lot(sym: str) -> float:
    """Estimated $ value per pip for 1.0 lot."""
    if "XAU" in sym:
        return 1.0  # $1 per point (0.01) for 1 lot = 100 oz
    elif "NAS" in sym or "GER" in sym or "US30" in sym:
        return 1.0
    elif "JPY" in sym:
        return 1000.0  # approx
    else:
        return 10.0  # FX: $10 per pip for 1.0 lot


def run_simulation(h1_data: dict, h4_data: dict) -> dict:
    engine = UnifiedEngine()
    min_len = min(len(h1_data[s]) for s in h1_data)
    
    cash = INITIAL_EQUITY
    positions: Dict[str, SimPos] = {}
    trades = []
    equity_curve = []
    last_trade_bar = {}  # symbol -> bar index
    
    for i in range(100, min_len):
        ts = h1_data[list(h1_data.keys())[0]].index[i]
        prices = {s: h1_data[s]["close"].iloc[i] for s in h1_data}
        
        # 1. Check SL/TP
        to_close = []
        for sym, pos in list(positions.items()):
            if sym not in prices:
                continue
            p = prices[sym]
            if pos.direction == 1:
                if p <= pos.sl:
                    to_close.append(sym)
                elif p >= pos.tp:
                    to_close.append(sym)
            else:
                if p >= pos.sl:
                    to_close.append(sym)
                elif p <= pos.tp:
                    to_close.append(sym)
        
        for sym in to_close:
            pos = positions.pop(sym)
            p = prices[sym]
            slip = SLIPPAGE_PIPS * point_size(sym)
            fill = p - (slip * pos.direction)
            change = (fill - pos.entry) * pos.direction
            pips = change / point_size(sym)
            pnl = pips * (pip_value_per_lot(sym) / 100.0) * pos.size
            cash += pnl - COMMISSION * pos.size
            trades.append({"pnl": pnl - COMMISSION * pos.size, "strat": pos.strategy, "sym": sym})
        
        # 2. Generate signals
        signals = engine.generate_signals(i, ts, h1_data, h4_data)
        
        # 3. Portfolio management filters
        # Heat check
        total_risk = 0.0
        for sym, pos in positions.items():
            if sym in prices:
                risk_dist = abs(pos.entry - pos.sl)
                pips = risk_dist / point_size(sym)
                risk = pips * (pip_value_per_lot(sym) / 100.0) * pos.size
                total_risk += risk
        
        heat_pct = (total_risk / INITIAL_EQUITY) * 100
        
        # Anti-correlation: if EURUSD long, block GBPUSD long
        blocked_symbols = set()
        for sym, pos in positions.items():
            if pos.direction == 1 and "EURUSD" in sym:
                blocked_symbols.add("GBPUSD")
            if pos.direction == 1 and "GBPUSD" in sym:
                blocked_symbols.add("EURUSD")
        
        # 4. Execute signals
        for sig in signals:
            # Skip if already in position
            if sig.symbol in positions:
                continue
            
            # Skip if blocked by correlation
            if sig.symbol in blocked_symbols:
                continue
            
            # Skip if cooldown active
            if sig.symbol in last_trade_bar and (i - last_trade_bar[sig.symbol]) < COOLDOWN_BARS:
                continue
            
            # Skip if max positions reached
            if len(positions) >= MAX_POSITIONS:
                continue
            
            # Skip if would exceed heat cap
            risk_dist = abs(prices[sig.symbol] - sig.sl)
            pips = risk_dist / point_size(sig.symbol)
            trade_risk = pips * (pip_value_per_lot(sig.symbol) / 100.0) * sig.size_lots
            if (total_risk + trade_risk) / INITIAL_EQUITY * 100 > HEAT_CAP_PCT:
                # Try halving size
                sig.size_lots = max(0.01, round(sig.size_lots / 2, 2))
                trade_risk = trade_risk / 2
                if (total_risk + trade_risk) / INITIAL_EQUITY * 100 > HEAT_CAP_PCT:
                    continue
            
            # Execute
            p = prices[sig.symbol]
            slip = SLIPPAGE_PIPS * point_size(sig.symbol)
            fill = p + (slip * sig.direction)
            cash -= COMMISSION * sig.size_lots
            positions[sig.symbol] = SimPos(
                sig.symbol, sig.direction, fill, sig.size_lots,
                sig.sl, sig.tp, i, sig.strategy
            )
            last_trade_bar[sig.symbol] = i
            total_risk += trade_risk
        
        # 5. Mark to market
        unrealized = 0.0
        for sym, pos in positions.items():
            if sym in prices:
                p = prices[sym]
                change = (p - pos.entry) * pos.direction
                pips = change / point_size(sym)
                upnl = pips * (pip_value_per_lot(sym) / 100.0) * pos.size
                unrealized += upnl
        
        equity = cash + unrealized
        equity_curve.append({"time": ts, "equity": equity})
    
    # Close all at end
    for sym, pos in list(positions.items()):
        if sym in prices:
            p = prices[sym]
            slip = SLIPPAGE_PIPS * point_size(sym)
            fill = p - (slip * pos.direction)
            change = (fill - pos.entry) * pos.direction
            pips = change / point_size(sym)
            pnl = pips * (pip_value_per_lot(sym) / 100.0) * pos.size
            cash += pnl - COMMISSION * pos.size
            trades.append({"pnl": pnl - COMMISSION * pos.size, "strat": pos.strategy, "sym": sym})
    
    return calculate_metrics(trades, equity_curve)


def calculate_metrics(trades, equity_curve):
    if not equity_curve:
        return {}
    
    eq = pd.DataFrame(equity_curve)
    eq.set_index("time", inplace=True)
    returns = eq["equity"].pct_change().dropna()
    
    total_ret = (eq["equity"].iloc[-1] / INITIAL_EQUITY - 1) * 100
    ann_ret = returns.mean() * 252 * 24 * 100 if len(returns) > 0 else 0
    ann_vol = returns.std() * np.sqrt(252 * 24) * 100 if len(returns) > 0 else 0
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    peak = eq["equity"].expanding().max()
    dd = (eq["equity"] - peak) / peak
    max_dd = dd.min() * 100
    
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    strat_pnl = {}
    for t in trades:
        s = t["strat"]
        strat_pnl[s] = strat_pnl.get(s, 0) + t["pnl"]
    
    return {
        "initial": INITIAL_EQUITY,
        "final": eq["equity"].iloc[-1],
        "total_return": total_ret,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "trades": len(pnls),
        "win_rate": len(wins)/len(pnls)*100 if pnls else 0,
        "avg_win": np.mean(wins) if wins else 0,
        "avg_loss": np.mean([abs(p) for p in losses]) if losses else 0,
        "profit_factor": sum(wins)/sum(abs(p) for p in losses) if losses else 0,
        "total_pnl": sum(pnls),
        "strat_breakdown": strat_pnl,
        "equity": eq,
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 80)
    print("UNIFIED SYSTEM v3 -- Regime-Conditional Edges")
    print("=" * 80)
    print("StatArb -> RANGING/QUIET | Session -> TRENDING | GapFade -> Sundays")
    print("Adaptive sizing | Max 3 positions | 3%% heat cap | 6-bar cooldown")
    print("=" * 80)
    
    adapter = MT5Adapter()
    adapter.connect()
    print("MT5 connected.")
    
    try:
        symbols = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCHF"]
        h1_data = {}
        h4_data = {}
        for sym in symbols:
            try:
                h1, h4 = adapter.get_data(sym, h1_bars=3000, h4_bars=500)
                h1_data[sym] = h1
                h4_data[sym] = h4
                print(f"  {sym}: {len(h1)} H1 bars")
            except Exception as e:
                print(f"  {sym}: ERROR {e}")
        
        print("\nRunning simulation...")
        metrics = run_simulation(h1_data, h4_data)
        
        print("\n" + "=" * 80)
        print("RESULTS")
        print("=" * 80)
        print(f"  Initial Equity:    ${metrics['initial']:,.2f}")
        print(f"  Final Equity:      ${metrics['final']:,.2f}")
        print(f"  Total Return:      {metrics['total_return']:+.2f}%")
        print(f"  Ann. Return:       {metrics['ann_return']:+.2f}%")
        print(f"  Ann. Volatility:   {metrics['ann_vol']:.2f}%")
        print(f"  Sharpe Ratio:      {metrics['sharpe']:.3f}")
        print(f"  Max Drawdown:      {metrics['max_dd']:.2f}%")
        print(f"\n  Total Trades:      {metrics['trades']}")
        print(f"  Win Rate:          {metrics['win_rate']:.1f}%")
        print(f"  Avg Win:           ${metrics['avg_win']:+.2f}")
        print(f"  Avg Loss:          ${metrics['avg_loss']:-.2f}")
        print(f"  Profit Factor:     {metrics['profit_factor']:.2f}")
        print(f"  Total P&L:         ${metrics['total_pnl']:+.2f}")
        
        print(f"\n--- Per-Strategy ---")
        for s, pnl in sorted(metrics['strat_breakdown'].items(), key=lambda x: -x[1]):
            print(f"  {s:12s}: ${pnl:+.2f}")
        
        # Save
        metrics["equity"].to_csv("state/backtest_v3_equity.csv")
        print(f"\nEquity curve: state/backtest_v3_equity.csv")
        
    finally:
        adapter.disconnect()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
