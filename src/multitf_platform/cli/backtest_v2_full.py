"""FULL V2 SYSTEM BACKTEST — MultiTF + StatArb + SessionMomentum + GapFade.

Event-driven backtest using MT5 historical data.
Simulates all 4 strategy types bar-by-bar with realistic execution costs.

Outputs:
- Per-strategy metrics
- Portfolio-level metrics (return, drawdown, Sharpe, etc.)
- Equity curve
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig
from multitf_platform.strategy.edges.stat_arb import StatArbEngine
from multitf_platform.strategy.edges.session_momentum import SessionMomentumEngine, SessionType
from multitf_platform.strategy.edges.gap_fade import GapFadeEngine
from multitf_platform.risk.v1_1 import RiskWrapper
from multitf_platform.config.models import RiskWrapperConfig, CircuitBreakerConfig


# =============================================================================
# CONFIG
# =============================================================================

INITIAL_EQUITY = 10300.0
COMMISSION_PER_LOT = 7.0
SLIPPAGE_PIPS = 0.5
LEVERAGE = 1000

MULTITF_ASSETS = ["XAUUSD", "EURUSD", "NAS100", "BTCUST", "ETHUST",
                  "XNGUSD", "XBRUSD", "GBPUSD", "USDJPY", "US30", "GER40"]

STATARB_PAIRS = [("EURUSD", "GBPUSD"), ("AUDUSD", "NZDUSD"), ("EURUSD", "USDCHF")]
SESSION_SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]
GAP_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]

ALL_SYMBOLS = list(set(MULTITF_ASSETS +
    [leg for pair in STATARB_PAIRS for leg in pair] +
    SESSION_SYMBOLS + GAP_SYMBOLS))


# =============================================================================
# SIMULATION STATE
# =============================================================================

@dataclass
class SimPosition:
    symbol: str
    direction: int  # 1=LONG, -1=SHORT
    entry_price: float
    size_lots: float
    sl: float
    tp: float
    entry_time: pd.Timestamp
    entry_bar: int = 0
    comment: str = ""


@dataclass
class SimTrade:
    symbol: str
    direction: int
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    size_lots: float
    pnl: float
    comment: str = ""


@dataclass
class PortfolioState:
    equity: float = INITIAL_EQUITY
    cash: float = INITIAL_EQUITY
    positions: Dict[str, SimPosition] = field(default_factory=dict)
    trades: List[SimTrade] = field(default_factory=list)
    equity_curve: List[dict] = field(default_factory=list)


# =============================================================================
# EXECUTION SIMULATION
# =============================================================================

def get_point_value(symbol: str) -> float:
    """Estimated $ value per pip/point for 0.01 lot."""
    if "XAU" in symbol or "XAG" in symbol:
        return 0.01  # $0.01 per point for 0.01 lot
    elif "NAS" in symbol or "US30" in symbol or "GER" in symbol:
        return 0.01
    elif "BTC" in symbol or "ETH" in symbol:
        return 0.01
    elif "JPY" in symbol:
        return 0.01  # roughly
    else:
        return 0.01  # FX standard


def calc_pip_size(symbol: str) -> float:
    if "XAU" in symbol or "XAG" in symbol or "NAS" in symbol or "US30" in symbol or "GER" in symbol:
        return 0.01
    elif "JPY" in symbol:
        return 0.001
    else:
        return 0.0001


def sim_open_position(state: PortfolioState, symbol: str, direction: int,
                      size_lots: float, price: float, sl: float, tp: float,
                      timestamp: pd.Timestamp, bar_idx: int = 0, comment: str = "") -> dict:
    """Simulate opening a position with slippage and commission."""
    if symbol in state.positions:
        return {"success": False, "error": "Already have position"}
    
    # Slippage
    pip = calc_pip_size(symbol)
    slip = SLIPPAGE_PIPS * pip
    fill_price = price + (slip * direction)
    
    # Commission
    comm = COMMISSION_PER_LOT * size_lots
    state.cash -= comm
    
    pos = SimPosition(
        symbol=symbol, direction=direction,
        entry_price=fill_price, size_lots=size_lots,
        sl=sl, tp=tp, entry_time=timestamp, entry_bar=bar_idx, comment=comment
    )
    state.positions[symbol] = pos
    
    return {"success": True, "price": fill_price, "commission": comm}


def sim_close_position(state: PortfolioState, symbol: str, price: float,
                       timestamp: pd.Timestamp) -> dict:
    """Simulate closing a position with slippage and commission."""
    if symbol not in state.positions:
        return {"success": False, "error": "No position"}
    
    pos = state.positions.pop(symbol)
    
    # Slippage
    pip = calc_pip_size(symbol)
    slip = SLIPPAGE_PIPS * pip
    fill_price = price - (slip * pos.direction)
    
    # P&L
    pip_value = get_point_value(symbol) * 100  # per 1.0 lot
    price_change = (fill_price - pos.entry_price) * pos.direction
    pips = price_change / pip
    pnl = pips * pip_value * pos.size_lots
    
    # Commission
    comm = COMMISSION_PER_LOT * pos.size_lots
    state.cash += pnl - comm
    
    trade = SimTrade(
        symbol=symbol, direction=pos.direction,
        entry_time=pos.entry_time, exit_time=timestamp,
        entry_price=pos.entry_price, exit_price=fill_price,
        size_lots=pos.size_lots, pnl=pnl - comm,
        comment=pos.comment
    )
    state.trades.append(trade)
    
    return {"success": True, "pnl": pnl - comm, "commission": comm}


def update_equity(state: PortfolioState, prices: dict, timestamp: pd.Timestamp):
    """Update equity based on open positions mark-to-market."""
    unrealized = 0.0
    for sym, pos in state.positions.items():
        if sym in prices:
            price = prices[sym]
            pip = calc_pip_size(sym)
            pip_value = get_point_value(sym) * 100
            price_change = (price - pos.entry_price) * pos.direction
            pips = price_change / pip
            upnl = pips * pip_value * pos.size_lots
            unrealized += upnl
    
    state.equity = state.cash + unrealized
    state.equity_curve.append({"time": timestamp, "equity": state.equity})


# =============================================================================
# BACKTEST ENGINE
# =============================================================================

def run_backtest(h1_data: dict, h4_data: dict) -> dict:
    """Run full v2 backtest."""
    
    # Initialize strategies
    multitf = MultiTFStrategy(FrozenStrategyConfig())
    statarb_engines = {f"{a}_{b}": StatArbEngine((a, b)) for a, b in STATARB_PAIRS}
    session_engines = {s: SessionMomentumEngine(s) for s in SESSION_SYMBOLS}
    gap_engines = {s: GapFadeEngine(s) for s in GAP_SYMBOLS}
    
    # Risk wrapper
    risk_cfg = RiskWrapperConfig()
    risk_cfg.circuit_breakers = CircuitBreakerConfig(
        daily_loss_stop_pct=5.0, weekly_loss_stop_pct=10.0,
        monthly_loss_stop_pct=20.0, total_drawdown_kill_pct=25.0
    )
    risk = RiskWrapper(risk_cfg)
    
    state = PortfolioState()
    
    # Find common bar range
    min_len = min(len(h1_data[s]) for s in h1_data if s in ALL_SYMBOLS)
    
    print(f"Backtesting {min_len} bars ({min_len/24:.0f} days)...")
    
    for i in range(200, min_len):
        ts = h1_data[list(h1_data.keys())[0]].index[i]
        
        # Current prices
        prices = {s: h1_data[s]["close"].iloc[i] for s in h1_data if s in ALL_SYMBOLS}
        
        # Check SL/TP hits on open positions
        to_close = []
        for sym, pos in list(state.positions.items()):
            if sym not in prices:
                continue
            price = prices[sym]
            # For long: hit SL if price <= sl, hit TP if price >= tp
            # For short: hit SL if price >= sl, hit TP if price <= tp
            if pos.direction == 1:
                if price <= pos.sl:
                    to_close.append((sym, price, "SL"))
                elif price >= pos.tp:
                    to_close.append((sym, price, "TP"))
            else:
                if price >= pos.sl:
                    to_close.append((sym, price, "SL"))
                elif price <= pos.tp:
                    to_close.append((sym, price, "TP"))
        
        for sym, price, reason in to_close:
            sim_close_position(state, sym, price, ts)
        
        # Minimum hold time: 4 bars (don't close by signal change before 4 bars)
        MIN_HOLD_BARS = 4
        hold_blocked = {sym for sym, pos in state.positions.items() if (i - pos.entry_bar) < MIN_HOLD_BARS}
        
        # --- MultiTF Signals ---
        for sym in MULTITF_ASSETS:
            if sym not in h1_data or sym not in h4_data:
                continue
            h1 = h1_data[sym].iloc[:i+1]
            h4 = h4_data[sym][h4_data[sym].index <= h1.index[-1]]
            if len(h4) < 50:
                continue
            
            sig = multitf.generate_signal(h1, h4, ts)
            spread = (h1["high"].iloc[-1] - h1["low"].iloc[-1]) * 0.1
            alloc = state.equity * (1.0 / len(MULTITF_ASSETS))
            wrapped = risk.apply(sig, h1, alloc, spread)
            
            target_dir = wrapped.final_direction
            current_pos = state.positions.get(sym)
            current_dir = current_pos.direction if current_pos else 0
            
            if target_dir != current_dir and sym not in hold_blocked:
                if current_pos:
                    sim_close_position(state, sym, prices[sym], ts)
                if target_dir != 0:
                    # Calculate SL/TP from recent H4 structure
                    recent = h4.tail(5)
                    if target_dir == 1:
                        sl = recent["low"].min()
                        risk_dist = prices[sym] - sl
                        tp = prices[sym] + risk_dist * 3.0
                    else:
                        sl = recent["high"].max()
                        risk_dist = sl - prices[sym]
                        tp = prices[sym] - risk_dist * 3.0
                    
                    size = max(0.01, round((alloc / 50000.0) * wrapped.position_scale, 2))
                    sim_open_position(state, sym, target_dir, size, prices[sym],
                                     sl, tp, ts, bar_idx=i, comment="MultiTF")
        
        # --- StatArb Signals ---
        for pair_name, engine in statarb_engines.items():
            leg1, leg2 = engine.leg1, engine.leg2
            if leg1 not in h1_data or leg2 not in h1_data:
                continue
            
            sig = engine.generate_signal(
                h1_data[leg1].iloc[:i+1], h1_data[leg2].iloc[:i+1],
                state.equity, ts
            )
            
            for leg, leg_dir, leg_size in [
                (leg1, sig.leg1_direction, sig.leg1_size),
                (leg2, sig.leg2_direction, sig.leg2_size),
            ]:
                current_pos = state.positions.get(leg)
                current_dir = current_pos.direction if current_pos else 0
                
                if leg_dir != current_dir and leg not in hold_blocked:
                    if current_pos:
                        sim_close_position(state, leg, prices[leg], ts)
                    if leg_dir != 0:
                        # Simple SL/TP for stat arb: 1% of price
                        price = prices[leg]
                        sl = price * (0.99 if leg_dir == 1 else 1.01)
                        tp = price * (1.01 if leg_dir == 1 else 0.99)
                        sim_open_position(state, leg, leg_dir, leg_size, price,
                                         sl, tp, ts, bar_idx=i, comment=f"StatArb_{pair_name}")
        
        # --- Session Momentum ---
        for sym, engine in session_engines.items():
            if sym not in h1_data:
                continue
            sig = engine.generate_signal(h1_data[sym].iloc[:i+1], state.equity, ts)
            
            current_pos = state.positions.get(sym)
            current_dir = current_pos.direction if current_pos else 0
            
            if sig.is_active and sig.direction != current_dir and sym not in hold_blocked:
                if current_pos:
                    sim_close_position(state, sym, prices[sym], ts)
                sim_open_position(state, sym, sig.direction, sig.size_lots, prices[sym],
                                 sig.sl_price, sig.tp_price, ts, bar_idx=i, comment="Session")
            elif not sig.is_active and current_dir != 0 and current_pos and current_pos.comment == "Session":
                sim_close_position(state, sym, prices[sym], ts)
        
        # --- Gap Fade ---
        for sym, engine in gap_engines.items():
            if sym not in h1_data:
                continue
            sig = engine.generate_signal(h1_data[sym].iloc[:i+1], state.equity, ts)
            
            current_pos = state.positions.get(sym)
            current_dir = current_pos.direction if current_pos else 0
            
            if sig.is_active and sig.direction != current_dir and sym not in hold_blocked:
                if current_pos:
                    sim_close_position(state, sym, prices[sym], ts)
                sim_open_position(state, sym, sig.direction, sig.size_lots, prices[sym],
                                 sig.sl_price, sig.tp_price, ts, bar_idx=i, comment="GapFade")
            elif not sig.is_active and current_dir != 0 and current_pos and current_pos.comment == "GapFade":
                sim_close_position(state, sym, prices[sym], ts)
        
        # Update equity
        update_equity(state, prices, ts)
    
    # Close all positions at end
    for sym, pos in list(state.positions.items()):
        if sym in prices:
            sim_close_position(state, sym, prices[sym], ts)
    
    return calculate_metrics(state)


def calculate_metrics(state: PortfolioState) -> dict:
    """Calculate performance metrics."""
    if not state.equity_curve:
        return {}
    
    eq = pd.DataFrame(state.equity_curve)
    eq.set_index("time", inplace=True)
    
    returns = eq["equity"].pct_change().dropna()
    
    total_return = (eq["equity"].iloc[-1] / INITIAL_EQUITY - 1) * 100
    
    if len(returns) > 0 and returns.std() > 0:
        ann_ret = returns.mean() * 252 * 24 * 100
        ann_vol = returns.std() * np.sqrt(252 * 24) * 100
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    else:
        ann_ret = ann_vol = sharpe = 0
    
    peak = eq["equity"].expanding().max()
    dd = (eq["equity"] - peak) / peak
    max_dd = dd.min() * 100
    
    trades = state.trades
    if trades:
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        win_rate = len(wins) / len(trades) * 100
        avg_win = np.mean([t.pnl for t in wins]) if wins else 0
        avg_loss = np.mean([abs(t.pnl) for t in losses]) if losses else 0
        profit_factor = sum(t.pnl for t in wins) / sum(abs(t.pnl) for t in losses) if losses else float('inf')
        total_pnl = sum(t.pnl for t in trades)
    else:
        win_rate = avg_win = avg_loss = profit_factor = total_pnl = 0
    
    # Per-strategy breakdown
    strat_pnl = {}
    for t in trades:
        strat = t.comment.split("_")[0] if "_" in t.comment else t.comment
        strat_pnl[strat] = strat_pnl.get(strat, 0) + t.pnl
    
    return {
        "initial_equity": INITIAL_EQUITY,
        "final_equity": eq["equity"].iloc[-1],
        "total_return_pct": total_return,
        "ann_return_pct": ann_ret,
        "ann_volatility_pct": ann_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": max_dd,
        "total_trades": len(trades),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "total_pnl": total_pnl,
        "strat_breakdown": strat_pnl,
        "equity_curve": eq,
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 80)
    print("FULL V2 SYSTEM BACKTEST")
    print("=" * 80)
    print(f"Initial Equity: ${INITIAL_EQUITY:,.2f}")
    print(f"Commission: ${COMMISSION_PER_LOT}/lot | Slippage: {SLIPPAGE_PIPS} pips")
    print(f"Assets: {len(MULTITF_ASSETS)} MultiTF + {len(STATARB_PAIRS)} StatArb pairs")
    print(f"        {len(SESSION_SYMBOLS)} Session + {len(GAP_SYMBOLS)} GapFade")
    print("=" * 80)
    
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
        h1_data = {}
        h4_data = {}
        
        for sym in ALL_SYMBOLS:
            try:
                h1, h4 = adapter.get_data(sym, h1_bars=2000, h4_bars=500)
                h1_data[sym] = h1
                h4_data[sym] = h4
                print(f"  {sym}: {len(h1)} H1, {len(h4)} H4 bars")
            except Exception as e:
                print(f"  {sym}: ERROR — {e}")
        
        if not h1_data:
            print("No data available.")
            return 1
        
        print("\n--- Running backtest ---")
        metrics = run_backtest(h1_data, h4_data)
        
        print("\n" + "=" * 80)
        print("PORTFOLIO METRICS")
        print("=" * 80)
        print(f"  Initial Equity:      ${metrics['initial_equity']:,.2f}")
        print(f"  Final Equity:        ${metrics['final_equity']:,.2f}")
        print(f"  Total Return:        {metrics['total_return_pct']:+.2f}%")
        print(f"  Annualized Return:   {metrics['ann_return_pct']:+.2f}%")
        print(f"  Annualized Vol:      {metrics['ann_volatility_pct']:.2f}%")
        print(f"  Sharpe Ratio:        {metrics['sharpe_ratio']:.3f}")
        print(f"  Max Drawdown:        {metrics['max_drawdown_pct']:.2f}%")
        print(f"\n  Total Trades:        {metrics['total_trades']}")
        print(f"  Win Rate:            {metrics['win_rate']:.1f}%")
        print(f"  Avg Win:             ${metrics['avg_win']:+.2f}")
        print(f"  Avg Loss:            ${metrics['avg_loss']:-.2f}")
        print(f"  Profit Factor:       {metrics['profit_factor']:.2f}")
        print(f"  Total P&L:           ${metrics['total_pnl']:+.2f}")
        
        print(f"\n--- Per-Strategy Breakdown ---")
        for strat, pnl in sorted(metrics['strat_breakdown'].items(), key=lambda x: -x[1]):
            print(f"  {strat:15s}: ${pnl:+.2f}")
        
        # Save equity curve
        eq = metrics['equity_curve']
        eq.to_csv("state/backtest_v2_equity.csv")
        print(f"\nEquity curve saved to: state/backtest_v2_equity.csv")
        
    finally:
        adapter.disconnect()
        print("MT5 disconnected.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
