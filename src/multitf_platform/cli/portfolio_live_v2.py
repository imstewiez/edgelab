"""Portfolio LIVE Trading v2 — UNIFIED MULTI-ALPHA SYSTEM.

Runs FOUR independent alpha generators simultaneously:
1. MultiTF Momentum (frozen v1.0.0) — expanded to 11 assets
2. Statistical Arbitrage — 3 cointegrated FX pairs
3. Session Open Momentum — London/NY breakout scalper
4. Weekend Gap Fade — Sunday mean-reversion

All strategies share:
- One MT5 connection
- One RiskWrapper (persisted state across iterations)
- One portfolio heat cap (5% max)
- One audit logger

Assets traded:
- FX: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD
- Metals: XAUUSD, XAGUSD
- Crypto: BTCUST, ETHUST
- Energy: XNGUSD, XBRUSD
- Indices: NAS100, US30, GER40

Total: up to 15+ independent positions across 4 strategy types.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import json
from datetime import datetime
from typing import Dict, Optional

from multitf_platform.config.loader import load_config
from multitf_platform.config.models import BrokerConfig, CircuitBreakerConfig, RiskWrapperConfig
from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig
from multitf_platform.strategy.edges.stat_arb import StatArbEngine
from multitf_platform.strategy.edges.session_momentum import SessionMomentumEngine
from multitf_platform.strategy.edges.gap_fade import GapFadeEngine
from multitf_platform.risk.v1_1 import RiskWrapper
from multitf_platform.risk.v1_1.risk_parity import RiskParityWeights
from multitf_platform.brokers.mt5.executor import MT5Executor
from multitf_platform.audit.logger import AuditLogger


# =============================================================================
# EXPANDED ASSET UNIVERSE
# =============================================================================

MULTITF_ASSETS = [
    "XAUUSD",   # Gold
    "EURUSD",   # Euro
    "NAS100",   # Nasdaq
    "BTCUST",   # Bitcoin
    "ETHUST",   # Ethereum
    "XNGUSD",   # Natural Gas
    "XBRUSD",   # Brent Crude
    "GBPUSD",   # Pound
    "USDJPY",   # Yen
    "US30",     # Dow Jones
    "GER40",    # DAX
]

# Inverse-volatility fallback weights (will be overridden by risk-parity)
INV_VOL_WEIGHTS = {
    "XAUUSD": 0.10, "EURUSD": 0.12, "NAS100": 0.08,
    "BTCUST": 0.05, "ETHUST": 0.05, "XNGUSD": 0.06,
    "XBRUSD": 0.06, "GBPUSD": 0.12, "USDJPY": 0.12,
    "US30": 0.08, "GER40": 0.08,
}

# Normalize weights
total_w = sum(INV_VOL_WEIGHTS.values())
INV_VOL_WEIGHTS = {k: v/total_w for k, v in INV_VOL_WEIGHTS.items()}

# StatArb pairs
STATARB_PAIRS = [
    ("EURUSD", "GBPUSD"),
    ("AUDUSD", "NZDUSD"),
    ("EURUSD", "USDCHF"),
]

# Session momentum symbols
SESSION_SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]

# Gap fade symbols
GAP_FADE_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]

# All unique symbols we need data for
ALL_SYMBOLS = list(set(
    MULTITF_ASSETS
    + [leg for pair in STATARB_PAIRS for leg in pair]
    + SESSION_SYMBOLS
    + GAP_FADE_SYMBOLS
))


# =============================================================================
# STATE MANAGEMENT
# =============================================================================

STATE_FILE = Path("state") / "portfolio_state_v2.json"


def load_portfolio_state() -> dict:
    if STATE_FILE.exists():
        return json.load(open(STATE_FILE))
    return {
        "positions": {},
        "risk_state": {},
        "expectancy_history": [],
        "equity_history": [],
    }


def save_portfolio_state(data: dict):
    STATE_FILE.parent.mkdir(exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def get_weights(risk_parity: RiskParityWeights, h1_data: dict) -> dict:
    if risk_parity is not None and h1_data:
        for symbol, bars in h1_data.items():
            risk_parity.update_prices(symbol, bars)
        weights = risk_parity.calculate_weights(list(h1_data.keys()))
        return weights
    return INV_VOL_WEIGHTS.copy()


# =============================================================================
# RISK WRAPPER STATE PERSISTENCE
# =============================================================================

def save_risk_state(risk: RiskWrapper) -> dict:
    """Extract serializable state from RiskWrapper."""
    s = risk.state
    return {
        "consecutive_losses": s.consecutive_losses,
        "daily_pnl": s.daily_pnl,
        "weekly_pnl": s.weekly_pnl,
        "monthly_pnl": s.monthly_pnl,
        "trades_today": s.trades_today,
        "trades_this_week": s.trades_this_week,
        "peak_equity": s.peak_equity,
        "current_equity": s.current_equity,
        "kill_switch_active": s.kill_switch_active,
        "kill_reason": s.kill_reason,
        "cooldown_bars_remaining": s.cooldown_bars_remaining,
        "last_trade_day": s.last_trade_day.isoformat() if s.last_trade_day else None,
        "last_flip_bar": s.last_flip_bar.isoformat() if s.last_flip_bar else None,
    }


def restore_risk_state(risk: RiskWrapper, state: dict):
    """Restore RiskWrapper state from serialized dict."""
    if not state:
        return
    s = risk.state
    s.consecutive_losses = state.get("consecutive_losses", 0)
    s.daily_pnl = state.get("daily_pnl", 0.0)
    s.weekly_pnl = state.get("weekly_pnl", 0.0)
    s.monthly_pnl = state.get("monthly_pnl", 0.0)
    s.trades_today = state.get("trades_today", 0)
    s.trades_this_week = state.get("trades_this_week", 0)
    s.peak_equity = state.get("peak_equity", 0.0)
    s.current_equity = state.get("current_equity", 0.0)
    s.kill_switch_active = state.get("kill_switch_active", False)
    s.kill_reason = state.get("kill_reason")
    s.cooldown_bars_remaining = state.get("cooldown_bars_remaining", 0)
    ltd = state.get("last_trade_day")
    if ltd:
        s.last_trade_day = pd.Timestamp(ltd)
    lfb = state.get("last_flip_bar")
    if lfb:
        s.last_flip_bar = pd.Timestamp(lfb)


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 80)
    print("PORTFOLIO LIVE TRADING v2 — UNIFIED MULTI-ALPHA SYSTEM")
    print("=" * 80)
    print(f"Strategies: MultiTF + StatArb + SessionMomentum + GapFade")
    print(f"Assets: {len(MULTITF_ASSETS)} MultiTF + {len(STATARB_PAIRS)} pairs + "
          f"{len(SESSION_SYMBOLS)} session + {len(GAP_FADE_SYMBOLS)} gap-fade")
    print(f"Total unique symbols: {len(ALL_SYMBOLS)}")
    print("=" * 80)

    cfg = load_config()

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

    executor = MT5Executor(mt5, symbols=ALL_SYMBOLS)

    try:
        account = adapter.get_account_info()
        print(f"\nAccount: #{account['login']} @ {account['server']}")
        print(f"Balance: ${account['balance']:,.2f} | Equity: ${account['equity']:,.2f}")
        print(f"Leverage: 1:{account['leverage']}")
        total_equity = account['equity']

        # Load previous state
        prev_state = load_portfolio_state()

        # =================================================================
        # PHASE 1: Data Collection (all symbols, all timeframes)
        # =================================================================
        print("\n--- Phase 1: Data Collection ---")
        all_h1_data: Dict[str, pd.DataFrame] = {}
        all_h4_data: Dict[str, pd.DataFrame] = {}

        for symbol in ALL_SYMBOLS:
            try:
                h1, h4 = adapter.get_data(symbol, h1_bars=300, h4_bars=100)
                all_h1_data[symbol] = h1
                all_h4_data[symbol] = h4
                print(f"  {symbol}: {len(h1)} H1, {len(h4)} H4 bars")
            except Exception as e:
                print(f"  {symbol}: ERROR — {e}")

        if not all_h1_data:
            print("ERROR: No data available. Exiting.")
            return 1

        # =================================================================
        # PHASE 2: Risk-Parity Weights (MultiTF assets only)
        # =================================================================
        print("\n--- Phase 2: Risk-Parity Weights ---")
        rp = RiskParityWeights(lookback_bars=50)
        multitf_weights = get_weights(rp, {k: v for k, v in all_h1_data.items() if k in MULTITF_ASSETS})

        # =================================================================
        # PHASE 3: Initialize Strategies
        # =================================================================
        print("\n--- Phase 3: Strategy Initialization ---")

        # MultiTF
        multitf_strategy = MultiTFStrategy(FrozenStrategyConfig())
        print(f"  MultiTF v{multitf_strategy.VERSION} — {len(MULTITF_ASSETS)} assets")

        # StatArb
        stat_arb_engines = {}
        for leg1, leg2 in STATARB_PAIRS:
            engine = StatArbEngine((leg1, leg2))
            stat_arb_engines[engine.pair_name] = engine
        print(f"  StatArb v{StatArbEngine.VERSION} — {len(stat_arb_engines)} pairs")

        # Session Momentum
        session_engines = {}
        for sym in SESSION_SYMBOLS:
            if sym in all_h1_data:
                session_engines[sym] = SessionMomentumEngine(sym)
        print(f"  SessionMomentum v{SessionMomentumEngine.VERSION} — {len(session_engines)} symbols")

        # Gap Fade
        gap_engines = {}
        for sym in GAP_FADE_SYMBOLS:
            if sym in all_h1_data:
                gap_engines[sym] = GapFadeEngine(sym)
        print(f"  GapFade v{GapFadeEngine.VERSION} — {len(gap_engines)} symbols")

        # =================================================================
        # PHASE 4: Shared Risk Wrapper (with persisted state)
        # =================================================================
        print("\n--- Phase 4: Risk Wrapper (shared, persisted) ---")
        risk_cfg = cfg.risk_wrapper.model_copy()
        risk_cfg.circuit_breakers = CircuitBreakerConfig(
            daily_loss_stop_pct=5.0,
            weekly_loss_stop_pct=10.0,
            monthly_loss_stop_pct=20.0,
            total_drawdown_warning_pct=10.0,
            total_drawdown_kill_pct=25.0,
        )
        risk = RiskWrapper(risk_cfg)
        restore_risk_state(risk, prev_state.get("risk_state", {}))
        print(f"  RiskWrapper v{RiskWrapper.VERSION} — state restored")

        # Restore expectancy
        prev_expectancy = prev_state.get("expectancy_history", [])
        for trade in prev_expectancy:
            risk.expectancy.add_trade(trade.get("symbol", ""), trade.get("pnl", 0))

        # =================================================================
        # PHASE 5: Execute Strategies
        # =================================================================
        print("\n" + "=" * 80)
        print("PHASE 5: EXECUTION")
        print("=" * 80)

        executions = []
        signals_record = {}

        # -------------------------------------------------------------
        # 5A: MultiTF Momentum
        # -------------------------------------------------------------
        print("\n--- 5A: MultiTF Momentum ---")
        for symbol in MULTITF_ASSETS:
            if symbol not in all_h1_data or symbol not in all_h4_data:
                continue

            h1 = all_h1_data[symbol]
            h4 = all_h4_data[symbol]
            ts = h1.index[-1]

            try:
                sig = multitf_strategy.generate_signal(h1, h4, ts)
                tick = adapter.get_tick(symbol)
                spread = tick['spread']

                alloc_equity = total_equity * multitf_weights.get(symbol, 1.0 / len(MULTITF_ASSETS))
                wrapped = risk.apply(sig, h1, alloc_equity, spread)

                dir_str = "LONG" if sig.is_long else "SHORT" if sig.is_short else "FLAT"
                final_str = "LONG" if wrapped.final_direction == 1 else "SHORT" if wrapped.final_direction == -1 else "FLAT"

                print(f"\n  {symbol}: Signal={dir_str} -> Risk={wrapped.action.name} -> {final_str} (scale={wrapped.position_scale:.2f})")

                current_pos = executor.get_position(symbol)
                current_dir = 1 if current_pos and current_pos["type"] == 0 else -1 if current_pos else 0

                if wrapped.final_direction != current_dir:
                    result = executor.execute(
                        symbol, wrapped.final_direction, 0.0,
                        h4_bars=h4, h1_bars=h1,
                        equity=alloc_equity, scale=wrapped.position_scale
                    )
                    _log_execution(symbol, "MultiTF", result, executions)
                else:
                    if current_dir != 0:
                        executor.trail_stop(symbol)
                    print(f"    HOLD {final_str}")

                signals_record[f"multitf_{symbol}"] = {
                    "strategy": "MultiTF",
                    "symbol": symbol,
                    "direction": sig.direction,
                    "final_direction": wrapped.final_direction,
                    "scale": wrapped.position_scale,
                }
            except Exception as e:
                print(f"  {symbol}: ERROR — {e}")

        # -------------------------------------------------------------
        # 5B: Statistical Arbitrage
        # -------------------------------------------------------------
        print("\n--- 5B: Statistical Arbitrage ---")
        for pair_name, engine in stat_arb_engines.items():
            leg1, leg2 = engine.leg1, engine.leg2
            if leg1 not in all_h1_data or leg2 not in all_h1_data:
                continue

            h1_leg1 = all_h1_data[leg1]
            h1_leg2 = all_h1_data[leg2]
            ts = h1_leg1.index[-1]

            try:
                sig = engine.generate_signal(h1_leg1, h1_leg2, total_equity, ts)
                print(f"\n  {pair_name}: Z={sig.z_score:+.2f} hedge={sig.hedge_ratio:.3f} -> "
                      f"L1={sig.leg1_direction:+d}@{sig.leg1_size:.2f} "
                      f"L2={sig.leg2_direction:+d}@{sig.leg2_size:.2f}")

                if sig.blocked_reason:
                    print(f"    BLOCKED: {sig.blocked_reason}")
                    continue

                if not sig.is_active:
                    # Check if we need to close existing positions
                    for leg, leg_dir in [(leg1, sig.leg1_direction), (leg2, sig.leg2_direction)]:
                        pos = executor.get_position(leg)
                        if pos:
                            print(f"    Closing {leg} (pair flat)")
                            executor.close_position(leg)
                            executions.append({"strategy": "StatArb", "symbol": leg, "action": "CLOSE", "reason": "pair_flat"})
                    continue

                # Execute each leg
                for leg, leg_dir, leg_size in [
                    (leg1, sig.leg1_direction, sig.leg1_size),
                    (leg2, sig.leg2_direction, sig.leg2_size),
                ]:
                    pos = executor.get_position(leg)
                    current_leg_dir = 1 if pos and pos["type"] == 0 else -1 if pos else 0

                    if leg_dir != current_leg_dir:
                        if pos:
                            executor.close_position(leg)
                            executions.append({"strategy": "StatArb", "symbol": leg, "action": "CLOSE"})
                        if leg_dir != 0:
                            h4 = all_h4_data.get(leg)
                            result = executor.open_position(
                                leg, leg_dir, leg_size, h4_bars=h4,
                                comment=f"StatArb {pair_name}"
                            )
                            print(f"    OPEN {leg}: {'LONG' if leg_dir==1 else 'SHORT'} {leg_size:.2f} lots")
                            executions.append({
                                "strategy": "StatArb", "symbol": leg, "action": "OPEN",
                                "direction": leg_dir, "size": leg_size, "success": result.get("success")
                            })

                signals_record[f"stat_arb_{pair_name}"] = {
                    "strategy": "StatArb",
                    "pair": pair_name,
                    "z_score": sig.z_score,
                    "hedge_ratio": sig.hedge_ratio,
                    "leg1_dir": sig.leg1_direction,
                    "leg2_dir": sig.leg2_direction,
                }
            except Exception as e:
                print(f"  {pair_name}: ERROR — {e}")

        # -------------------------------------------------------------
        # 5C: Session Momentum
        # -------------------------------------------------------------
        print("\n--- 5C: Session Momentum ---")
        for symbol, engine in session_engines.items():
            if symbol not in all_h1_data:
                continue

            h1 = all_h1_data[symbol]
            ts = h1.index[-1]

            try:
                sig = engine.generate_signal(h1, total_equity, ts)

                if sig.blocked_reason:
                    if "Outside session" not in sig.blocked_reason:
                        print(f"  {symbol}: {sig.blocked_reason}")
                    continue

                if not sig.is_active:
                    pos = executor.get_position(symbol)
                    if pos:
                        print(f"  {symbol}: Closing session position")
                        executor.close_position(symbol)
                        executions.append({"strategy": "Session", "symbol": symbol, "action": "CLOSE"})
                    continue

                session_name = "London" if sig.session.value == 1 else "NY"
                print(f"\n  {symbol}: {session_name} open BREAKOUT "
                      f"range={sig.range_ratio:.1f}x -> {'LONG' if sig.direction==1 else 'SHORT'}")

                pos = executor.get_position(symbol)
                current_dir = 1 if pos and pos["type"] == 0 else -1 if pos else 0

                if sig.direction != current_dir:
                    if pos:
                        executor.close_position(symbol)
                        executions.append({"strategy": "Session", "symbol": symbol, "action": "CLOSE"})

                    h4 = all_h4_data.get(symbol)
                    result = executor.open_position(
                        symbol, sig.direction, sig.size_lots, h4_bars=h4,
                        sl=sig.sl_price, tp=sig.tp_price,
                        comment=f"Session {session_name}"
                    )
                    print(f"    OPEN: {sig.size_lots:.2f} lots @ SL={sig.sl_price:.5f} TP={sig.tp_price:.5f}")
                    executions.append({
                        "strategy": "Session", "symbol": symbol, "action": "OPEN",
                        "direction": sig.direction, "size": sig.size_lots,
                        "sl": sig.sl_price, "tp": sig.tp_price,
                        "success": result.get("success")
                    })

                signals_record[f"session_{symbol}"] = {
                    "strategy": "Session",
                    "symbol": symbol,
                    "session": session_name,
                    "direction": sig.direction,
                    "range_ratio": sig.range_ratio,
                }
            except Exception as e:
                print(f"  {symbol}: ERROR — {e}")

        # -------------------------------------------------------------
        # 5D: Weekend Gap Fade
        # -------------------------------------------------------------
        print("\n--- 5D: Weekend Gap Fade ---")
        for symbol, engine in gap_engines.items():
            if symbol not in all_h1_data:
                continue

            h1 = all_h1_data[symbol]
            ts = h1.index[-1]

            try:
                sig = engine.generate_signal(h1, total_equity, ts)

                if sig.blocked_reason:
                    if "Not Sunday" not in sig.blocked_reason:
                        print(f"  {symbol}: {sig.blocked_reason}")
                    continue

                if not sig.is_active:
                    pos = executor.get_position(symbol)
                    if pos:
                        print(f"  {symbol}: Closing gap-fade position")
                        executor.close_position(symbol)
                        executions.append({"strategy": "GapFade", "symbol": symbol, "action": "CLOSE"})
                    continue

                print(f"\n  {symbol}: GAP {sig.gap_size:+.5f} ({sig.gap_atr_ratio:.1f}x ATR) -> "
                      f"{'LONG' if sig.direction==1 else 'SHORT'} fade")

                pos = executor.get_position(symbol)
                current_dir = 1 if pos and pos["type"] == 0 else -1 if pos else 0

                if sig.direction != current_dir:
                    if pos:
                        executor.close_position(symbol)
                        executions.append({"strategy": "GapFade", "symbol": symbol, "action": "CLOSE"})

                    h4 = all_h4_data.get(symbol)
                    result = executor.open_position(
                        symbol, sig.direction, sig.size_lots, h4_bars=h4,
                        sl=sig.sl_price, tp=sig.tp_price,
                        comment="GapFade"
                    )
                    print(f"    OPEN: {sig.size_lots:.2f} lots @ SL={sig.sl_price:.5f} TP={sig.tp_price:.5f}")
                    executions.append({
                        "strategy": "GapFade", "symbol": symbol, "action": "OPEN",
                        "direction": sig.direction, "size": sig.size_lots,
                        "sl": sig.sl_price, "tp": sig.tp_price,
                        "success": result.get("success")
                    })

                signals_record[f"gap_{symbol}"] = {
                    "strategy": "GapFade",
                    "symbol": symbol,
                    "gap_size": sig.gap_size,
                    "gap_atr_ratio": sig.gap_atr_ratio,
                    "direction": sig.direction,
                }
            except Exception as e:
                print(f"  {symbol}: ERROR — {e}")

        # =================================================================
        # PHASE 6: Portfolio Summary
        # =================================================================
        print(f"\n{'='*80}")
        print("PORTFOLIO SUMMARY")
        print(f"{'='*80}")

        all_positions = mt5.positions_get()
        total_floating = sum(p.profit for p in all_positions) if all_positions else 0.0
        total_margin = sum(p.margin for p in all_positions) if all_positions else 0.0

        print(f"Total positions: {len(all_positions) if all_positions else 0}")
        print(f"Floating P&L: ${total_floating:+.2f}")
        print(f"Margin used: ${total_margin:,.2f}")
        print(f"Free margin: ${account['free_margin']:,.2f}")

        if all_positions:
            print("\nOpen positions:")
            for p in all_positions:
                dir_str = "LONG" if p.type == 0 else "SHORT"
                print(f"  {p.symbol:10s} | {dir_str:5s} | {p.volume:.2f} lots | "
                      f"Open: {p.price_open:.5f} | Current: {p.price_current:.5f} | "
                      f"P&L: ${p.profit:+.2f} | Comment: {p.comment}")

        # Portfolio heat
        heat = executor.get_portfolio_heat(total_equity)
        print(f"\nPortfolio heat: {heat['heat_pct']:.2f}% (max: {heat['max_allowed_pct']:.0f}%)")

        # =================================================================
        # PHASE 7: Save State
        # =================================================================
        equity_history = prev_state.get("equity_history", [])
        equity_history.append({
            "time": datetime.utcnow().isoformat(),
            "equity": float(total_equity),
            "floating": float(total_floating),
        })
        equity_history = equity_history[-500:]

        # Build regime map
        regimes = {}
        for symbol in MULTITF_ASSETS:
            h1 = all_h1_data.get(symbol)
            if h1 is not None and len(h1) > 50:
                from multitf_platform.risk.v1_1.regime import RegimeDetector
                det = RegimeDetector()
                r = det.detect(h1)
                regimes[symbol] = r.value

        # Build correlation matrix
        correlations = {}
        try:
            from multitf_platform.risk.v1_1.correlation import CorrelationRiskChecker
            cc = CorrelationRiskChecker()
            for symbol in MULTITF_ASSETS:
                h1 = all_h1_data.get(symbol)
                if h1 is not None and len(h1) > 0:
                    cc.update_price(symbol, h1["close"].iloc[-1], h1.index[-1])
            for i, s1 in enumerate(MULTITF_ASSETS):
                for s2 in MULTITF_ASSETS[i+1:]:
                    r1 = cc._get_returns(s1)
                    r2 = cc._get_returns(s2)
                    if len(r1) > 10 and len(r2) > 10:
                        combined = pd.DataFrame({"a": r1, "b": r2}).dropna()
                        if len(combined) > 10:
                            corr = combined["a"].corr(combined["b"])
                            correlations[f"{s1}-{s2}"] = round(float(corr), 3)
        except Exception:
            pass

        portfolio_state = {
            "timestamp": datetime.utcnow().isoformat(),
            "account": account,
            "signals": signals_record,
            "executions": executions,
            "equity_history": equity_history,
            "regimes": regimes,
            "correlations": correlations,
            "risk_state": save_risk_state(risk),
        }
        save_portfolio_state(portfolio_state)

        # Audit log
        audit = AuditLogger()
        for key, sig in signals_record.items():
            audit.log("signal", {"key": key, **sig})

        print(f"\nState saved to {STATE_FILE}. Audit logged.")
        print(f"Risk state: peak_equity=${risk.state.peak_equity:.2f}, "
              f"daily_pnl={risk.state.daily_pnl:.4f}, "
              f"trades_today={risk.state.trades_today}")

    finally:
        adapter.disconnect()
        print("MT5 disconnected.")

    return 0


def _log_execution(symbol: str, strategy: str, result: dict, executions: list):
    """Log execution results from executor."""
    for r in result.get("results", []):
        if r.get("action") == "close":
            print(f"    CLOSED: P&L ${r.get('total_profit', 0):+.2f}")
            executions.append({"strategy": strategy, "symbol": symbol, "action": "CLOSE",
                              "profit": r.get("total_profit", 0)})
        elif r.get("action") == "open":
            if r.get("partial_tp"):
                print(f"    OPENED (Partial TP)")
            else:
                print(f"    OPENED: {r.get('volume', 0):.2f} lots @ {r.get('price', 0):.5f}")
            executions.append({"strategy": strategy, "symbol": symbol, "action": "OPEN",
                              "size": r.get("volume", 0), "price": r.get("price", 0)})
        elif r.get("action") == "block":
            print(f"    BLOCKED: {r.get('reason', '')}")


if __name__ == "__main__":
    sys.exit(main())
