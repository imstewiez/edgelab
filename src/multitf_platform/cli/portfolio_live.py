"""Portfolio live trading: XAUUSD + EURUSD + NAS100.

Connects to MT5, pulls data for all assets, generates signals,
applies risk wrapper, and executes REAL trades via MT5.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import json
from datetime import datetime

from multitf_platform.config.loader import load_config
from multitf_platform.config.models import BrokerConfig, CircuitBreakerConfig
from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig
from multitf_platform.risk.v1_1 import RiskWrapper
from multitf_platform.risk.v1_1.risk_parity import RiskParityWeights
from multitf_platform.brokers.mt5.executor import MT5Executor
from multitf_platform.audit.logger import AuditLogger


ASSETS = ["XAUUSD", "EURUSD", "NAS100"]
INV_VOL_WEIGHTS = {"XAUUSD": 0.246, "EURUSD": 0.562, "NAS100": 0.191}


def get_weights(risk_parity: RiskParityWeights = None, h1_data: dict = None):
    """Get portfolio weights.
    
    If risk_parity and h1_data are provided, uses dynamic risk-parity weights.
    Otherwise falls back to fixed inverse-vol weights.
    """
    if risk_parity is not None and h1_data is not None:
        # Update prices and calculate
        for symbol, bars in h1_data.items():
            risk_parity.update_prices(symbol, bars)
        weights = risk_parity.calculate_weights(ASSETS)
        diag = risk_parity.get_diagnostics(ASSETS)
        print(f"  Risk-Parity weights: {weights}")
        print(f"  Method: {diag.get('method', 'unknown')}")
        return weights
    return INV_VOL_WEIGHTS.copy()


def load_portfolio_state():
    f = Path("state") / "portfolio_state.json"
    if f.exists():
        return json.load(open(f))
    return {"positions": {}}


def save_portfolio_state(data):
    Path("state").mkdir(exist_ok=True)
    with open(Path("state") / "portfolio_state.json", "w") as f:
        json.dump(data, f, indent=2, default=str)


def main():
    print("=" * 70)
    print("Portfolio LIVE Trading — REAL MT5 Execution")
    print("Assets: XAUUSD + EURUSD + NAS100")
    print("=" * 70)
    
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
    
    executor = MT5Executor(mt5, symbols=ASSETS)
    
    try:
        account = adapter.get_account_info()
        print(f"\nAccount: #{account['login']} @ {account['server']}")
        print(f"Balance: ${account['balance']:,.2f} | Equity: ${account['equity']:,.2f}")
        print(f"Leverage: 1:{account['leverage']}")
        
        strategy = MultiTFStrategy(FrozenStrategyConfig())
        total_equity = account['equity']
        
        # Load previous state
        prev_state = load_portfolio_state()
        prev_positions = prev_state.get("positions", {})
        
        signals = {}
        executions = []
        all_h1_data = {}
        all_h4_data = {}
        
        # Phase 1: Pull data for all assets
        print("\n--- Phase 1: Data Collection ---")
        for symbol in ASSETS:
            try:
                h1, h4 = adapter.get_data(symbol, h1_bars=300, h4_bars=100)
                all_h1_data[symbol] = h1
                all_h4_data[symbol] = h4
                print(f"  {symbol}: {len(h1)} H1 bars, {len(h4)} H4 bars")
            except Exception as e:
                print(f"  {symbol}: ERROR fetching data: {e}")
        
        # Phase 2: Calculate risk-parity weights
        print("\n--- Phase 2: Risk-Parity Weights ---")
        rp = RiskParityWeights(lookback_bars=50)
        weights = get_weights(rp, all_h1_data)
        
        # Phase 3: Execute per asset
        print("\n--- Phase 3: Execution ---")
        for symbol in ASSETS:
            print(f"\n--- {symbol} ---")
            
            h1 = all_h1_data.get(symbol)
            h4 = all_h4_data.get(symbol)
            if h1 is None or h4 is None:
                print(f"  Skipped: no data")
                continue
            
            try:
                ts = h1.index[-1]
                bar = h1.iloc[-1]
                
                sig = strategy.generate_signal(h1, h4, ts)
                tick = adapter.get_tick(symbol)
                spread = tick['spread']
                
                # Allocate equity by weight
                alloc_equity = total_equity * weights[symbol]
                
                # Fresh risk wrapper per asset
                risk_cfg = cfg.risk_wrapper.model_copy()
                risk_cfg.circuit_breakers = CircuitBreakerConfig(
                    daily_loss_stop_pct=20.0,
                    weekly_loss_stop_pct=30.0,
                    monthly_loss_stop_pct=50.0,
                    total_drawdown_warning_pct=50.0,
                    total_drawdown_kill_pct=50.0,
                )
                risk = RiskWrapper(risk_cfg)
                
                # Restore expectancy filter history from previous state
                prev_expectancy = prev_state.get("expectancy_history", [])
                for trade in prev_expectancy:
                    risk.expectancy.add_trade(trade.get("symbol", symbol), trade.get("pnl", 0))
                
                wrapped = risk.apply(sig, h1, alloc_equity, spread)
                
                dir_str = "LONG" if sig.is_long else "SHORT" if sig.is_short else "FLAT"
                final_str = "LONG" if wrapped.final_direction == 1 else "SHORT" if wrapped.final_direction == -1 else "FLAT"
                
                print(f"  Signal: {dir_str} (H1={sig.h1_momentum:+.4f}, H4={sig.h4_momentum:+.4f})")
                print(f"  Risk:   {wrapped.action.name} -> {final_str} (scale={wrapped.position_scale:.2f})")
                
                # Check current real MT5 position
                current_pos = executor.get_position(symbol)
                current_dir = 0
                if current_pos:
                    current_dir = 1 if current_pos["type"] == 0 else -1
                    print(f"  Current MT5 position: {'LONG' if current_dir==1 else 'SHORT'} {current_pos['volume']:.2f} lots (P&L: ${current_pos['profit']:+.2f})")
                else:
                    print(f"  Current MT5 position: FLAT")
                
                # Execute if direction changed
                if wrapped.final_direction != current_dir:
                    print(f"  >>> EXECUTING: {current_dir} -> {wrapped.final_direction}")
                    result = executor.execute(
                        symbol, wrapped.final_direction, 0.0,
                        h4_bars=h4, h1_bars=h1,
                        equity=alloc_equity, scale=wrapped.position_scale
                    )
                    
                    for r in result.get("results", []):
                        if r["action"] == "close":
                            print(f"  >>> CLOSED: P&L ${r.get('profit', 0):+.2f}")
                            executions.append({"symbol": symbol, "action": "CLOSE", "profit": r.get("profit", 0)})
                        elif r["action"] == "risk_check":
                            print(f"  >>> RISK: Kelly={r.get('kelly', 0):.4f}, Regime={r.get('regime', 'unknown')}, Scale={r.get('risk_scale', 1.0):.2f}, Reason={r.get('reason', '')}")
                            print(f"  >>> FINAL LOTS: {r.get('final_lots', 0):.2f}")
                        elif r["action"] == "heat_block":
                            print(f"  >>> HEAT BLOCKED: {r.get('reason', '')}")
                        elif r["action"] == "heat_scale":
                            print(f"  >>> HEAT SCALED: {r.get('scale', 1.0):.2f}, Reason={r.get('reason', '')}, Lots={r.get('final_lots', 0):.2f}")
                        elif r["action"] == "block":
                            print(f"  >>> BLOCKED: {r.get('reason', '')}")
                        elif r["action"] == "open":
                            if r.get("partial_tp"):
                                print(f"  >>> OPENED (Partial TP): {final_str}")
                                for sub in r.get("results", []):
                                    if sub.get("success"):
                                        print(f"      {sub.get('comment', '')}: {sub.get('volume', 0):.2f} lots @ {sub.get('price', 0):.5f} | SL {sub.get('sl', 0):.5f} | TP {sub.get('tp', 0):.5f}")
                            else:
                                sl = r.get('sl', 0)
                                tp = r.get('tp', 0)
                                print(f"  >>> OPENED: {final_str} {r.get('volume', 0):.2f} lots @ {r.get('price', 0):.5f} | SL {sl:.5f} | TP {tp:.5f}")
                            executions.append({"symbol": symbol, "action": "OPEN", "side": final_str, "size": r.get('volume', 0), "price": r.get('price', 0), "sl": sl, "tp": tp})
                    
                    if not result["success"]:
                        print(f"  ERROR: {result.get('error', 'Unknown')}")
                else:
                    # Position exists — ensure SL/TP set and trail if in profit
                    if current_dir != 0:
                        sl, tp = executor._calculate_sl_tp(symbol, current_dir, current_pos['price_open'], h4)
                        mod = executor.modify_position(symbol, sl, tp)
                        if mod["success"] and "message" not in mod:
                            print(f"  >>> SL/TP SET: SL {sl:.5f} | TP {tp:.5f}")
                        
                        # Trail stop if in profit
                        trail = executor.trail_stop(symbol)
                        if trail.get("success") and "new_sl" in trail:
                            print(f"  >>> TRAIL: SL moved to {trail['new_sl']:.5f} ({trail['reason']}, locked {trail['profit_locked']:.1f}x risk)")
                        elif "message" in trail:
                            print(f"  {trail['message']}")
                        else:
                            print(f"  No action needed (already {final_str})")
                    else:
                        print(f"  No action needed (already {final_str})")
                
                signals[symbol] = {
                    "timestamp": str(ts),
                    "direction": sig.direction,
                    "h1_momentum": float(sig.h1_momentum),
                    "h4_momentum": float(sig.h4_momentum),
                    "risk_action": wrapped.action.name,
                    "final_direction": wrapped.final_direction,
                    "position_scale": wrapped.position_scale,
                    "bid": float(tick['bid']),
                    "ask": float(tick['ask']),
                    "spread": float(spread),
                    "target_lots": lots,
                }
                
            except Exception as e:
                print(f"  ERROR: {e}")
                import traceback
                traceback.print_exc()
                signals[symbol] = {"error": str(e)}
        
        # Portfolio summary
        print(f"\n{'='*70}")
        print("PORTFOLIO SUMMARY")
        print(f"{'='*70}")
        
        for symbol in ASSETS:
            pos = executor.get_position(symbol)
            s = signals.get(symbol, {})
            w = weights[symbol]
            alloc = total_equity * w
            if pos:
                dir_str = "LONG" if pos["type"] == 0 else "SHORT"
                print(f"  {symbol:8s} | Weight {w:>5.1%} | Alloc ${alloc:>6.2f} | {dir_str} {pos['volume']:.2f} lots | P&L ${pos['profit']:+.2f}")
            else:
                print(f"  {symbol:8s} | Weight {w:>5.1%} | Alloc ${alloc:>6.2f} | FLAT")
        
        # Build equity history
        prev_state = load_portfolio_state()
        equity_history = prev_state.get("equity_history", [])
        equity_history.append({
            "time": datetime.utcnow().isoformat(),
            "equity": float(total_equity),
        })
        equity_history = equity_history[-500:]  # Keep last 500 points
        
        # Build regime map
        regimes = {}
        for symbol in ASSETS:
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
            for symbol in ASSETS:
                h1 = all_h1_data.get(symbol)
                if h1 is not None and len(h1) > 0:
                    cc.update_price(symbol, h1["close"].iloc[-1], h1.index[-1])
            for i, s1 in enumerate(ASSETS):
                for s2 in ASSETS[i+1:]:
                    r1 = cc._get_returns(s1)
                    r2 = cc._get_returns(s2)
                    if len(r1) > 10 and len(r2) > 10:
                        import numpy as np
                        combined = pd.DataFrame({"a": r1, "b": r2}).dropna()
                        if len(combined) > 10:
                            corr = np.corrcoef(combined["a"], combined["b"])[0, 1]
                            correlations[f"{s1}-{s2}"] = round(float(corr), 3)
        except Exception:
            pass
        
        # Save state
        portfolio_state = {
            "timestamp": datetime.utcnow().isoformat(),
            "account": account,
            "signals": signals,
            "weights": weights,
            "executions": executions,
            "equity_history": equity_history,
            "regimes": regimes,
            "correlations": correlations,
        }
        save_portfolio_state(portfolio_state)
        
        # Audit log
        audit = AuditLogger()
        for symbol, sig in signals.items():
            if "error" not in sig:
                audit.log_signal(
                    pd.Timestamp(sig["timestamp"]),
                    sig["direction"],
                    sig["h1_momentum"],
                    sig["h4_momentum"],
                    True,
                    None
                )
        
        print(f"\nState saved. Audit logged.")
        
    finally:
        adapter.disconnect()
        print("MT5 disconnected.")
    
    return 0


if __name__ == "__main__":
    main()
