"""MultiTF Trading Dashboard — Professional live trading monitor.

Usage:
    cd fx-trading-bot/dashboard
    python app.py
    # Open http://localhost:5000
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import json
import re
from datetime import datetime, timedelta
from collections import defaultdict
from glob import glob

from flask import Flask, render_template, jsonify

app = Flask(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
STATE_FILE = PROJECT_ROOT / "state" / "portfolio_state.json"
LOGS_DIR = PROJECT_ROOT / "logs"


def _mt5():
    try:
        import MetaTrader5 as mt5
        if not mt5.terminal_info():
            mt5.initialize()
        return mt5
    except Exception:
        return None


def _load_state():
    if STATE_FILE.exists():
        try:
            return json.load(open(STATE_FILE))
        except Exception:
            pass
    return {"positions": {}, "executions": [], "equity_history": [], "regimes": {}, "correlations": {}}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/account")
def api_account():
    mt5 = _mt5()
    if not mt5:
        return jsonify({"connected": False, "error": "MT5 not available"})
    info = mt5.account_info()
    if info is None:
        return jsonify({"connected": False, "error": "MT5 not logged in"})
    return jsonify({
        "connected": True,
        "login": info.login,
        "server": info.server,
        "balance": info.balance,
        "equity": info.equity,
        "margin": info.margin,
        "margin_free": info.margin_free,
        "margin_level": info.margin_level,
        "leverage": info.leverage,
        "currency": info.currency,
    })


@app.route("/api/positions")
def api_positions():
    mt5 = _mt5()
    if not mt5:
        return jsonify({"positions": []})
    positions = mt5.positions_get()
    result = []
    if positions:
        for p in positions:
            result.append({
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "BUY" if p.type == 0 else "SELL",
                "volume": p.volume,
                "price_open": p.price_open,
                "price_current": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "swap": p.swap,
                "comment": p.comment,
                "time": p.time.strftime("%Y-%m-%d %H:%M:%S") if hasattr(p.time, "strftime") else str(p.time),
            })
    return jsonify({"positions": result})


@app.route("/api/history")
def api_history():
    """Return closed trades from MT5 history + state executions."""
    mt5 = _mt5()
    trades = []
    
    # Try MT5 history first
    if mt5:
        from_date = datetime.now() - timedelta(days=30)
        deals = mt5.history_deals_get(from_date, datetime.now())
        if deals:
            for d in deals:
                profit = d.profit + d.commission + d.swap
                if profit != 0:  # Only show exit deals (with P&L)
                    trades.append({
                        "symbol": d.symbol,
                        "side": "BUY" if d.type == 0 else "SELL",
                        "entry_price": d.price,
                        "size": d.volume,
                        "profit": profit,
                        "time": d.time.strftime("%Y-%m-%d %H:%M:%S") if hasattr(d.time, "strftime") else str(d.time),
                        "ticket": d.ticket,
                        "source": "mt5",
                    })
    
    # Fallback to state executions
    state = _load_state()
    executions = state.get("executions", [])
    open_trades = {}
    for ex in executions:
        symbol = ex.get("symbol")
        action = ex.get("action")
        if action == "OPEN":
            open_trades[symbol] = {
                "symbol": symbol,
                "side": ex.get("side"),
                "entry_price": ex.get("price"),
                "size": ex.get("size"),
                "sl": ex.get("sl"),
                "tp": ex.get("tp"),
                "time": ex.get("timestamp", ""),
                "source": "state",
            }
        elif action == "CLOSE" and symbol in open_trades:
            ot = open_trades.pop(symbol)
            ot["profit"] = ex.get("profit", 0)
            ot["close_time"] = ex.get("timestamp", "")
            if not any(t.get("source") == "mt5" and t.get("symbol") == symbol and abs(t.get("profit", 0) - ot["profit"]) < 0.01 for t in trades):
                trades.append(ot)
    
    trades.sort(key=lambda x: x.get("time", ""), reverse=True)
    return jsonify({"trades": trades[:50]})


@app.route("/api/stats")
def api_stats():
    mt5 = _mt5()
    state = _load_state()
    
    profits = []
    wins = 0
    losses = 0
    total_profit = 0.0
    total_loss = 0.0
    
    # Try MT5 history for accurate stats
    if mt5:
        from_date = datetime.now() - timedelta(days=90)
        deals = mt5.history_deals_get(from_date, datetime.now())
        if deals:
            for d in deals:
                pnl = d.profit + d.commission + d.swap
                if pnl != 0:
                    profits.append(pnl)
                    if pnl > 0:
                        wins += 1
                        total_profit += pnl
                    elif pnl < 0:
                        losses += 1
                        total_loss += abs(pnl)
    
    # Fallback to state
    if not profits:
        for ex in state.get("executions", []):
            if ex.get("action") == "CLOSE":
                pnl = ex.get("profit", 0)
                profits.append(pnl)
                if pnl > 0:
                    wins += 1
                    total_profit += pnl
                elif pnl < 0:
                    losses += 1
                    total_loss += abs(pnl)
    
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    avg_win = (total_profit / wins) if wins > 0 else 0
    avg_loss = (total_loss / losses) if losses > 0 else 0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else (999 if total_profit > 0 else 0)
    
    # Equity curve
    eq_curve = []
    equity_history = state.get("equity_history", [])
    if equity_history:
        for pt in equity_history:
            eq_curve.append({
                "time": pt.get("time", ""),
                "equity": pt.get("equity", 10300),
            })
    elif profits:
        running = 10300.0
        eq_curve.append({"time": "", "equity": running})
        for p in profits:
            running += p
            eq_curve.append({"time": "", "equity": running})
    else:
        eq_curve = [{"time": "", "equity": 10300.0}]
    
    # Calculate drawdown
    peak = 0
    max_dd = 0
    dd_points = []
    for pt in eq_curve:
        eq = pt["equity"]
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        dd_points.append({"time": pt["time"], "drawdown": dd})
        if dd > max_dd:
            max_dd = dd
    
    return jsonify({
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "total_pnl": round(total_profit - total_loss, 2),
        "gross_profit": round(total_profit, 2),
        "gross_loss": round(total_loss, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "equity_curve": eq_curve,
        "drawdown_curve": dd_points,
    })


@app.route("/api/logs")
def api_logs():
    logs = []
    
    # Read latest log files
    log_files = sorted(glob(str(LOGS_DIR / "*.log")))
    for lf in log_files[-2:]:
        try:
            with open(lf, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                for line in lines[-100:]:
                    line = line.strip()
                    if not line:
                        continue
                    level = "INFO"
                    msg = line
                    if "ERROR" in line or "Traceback" in line:
                        level = "ERROR"
                    elif "WARN" in line:
                        level = "WARN"
                    elif "EXECUTING" in line or "OPENED" in line or "CLOSED" in line:
                        level = "TRADE"
                    elif "BLOCKED" in line or "BLOCK" in line:
                        level = "BLOCK"
                    elif "RISK" in line and "Kelly" in line:
                        level = "RISK"
                    
                    # Try extract timestamp
                    time_match = re.match(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})", line)
                    time_str = time_match.group(1) if time_match else ""
                    if time_str:
                        msg = line[len(time_str):].strip()
                    
                    logs.append({"time": time_str, "level": level, "message": msg[:400]})
        except Exception:
            pass
    
    return jsonify({"logs": logs[-150:]})


@app.route("/api/risk")
def api_risk():
    state = _load_state()
    mt5 = _mt5()
    
    heat_pct = 0.0
    total_risk = 0.0
    breakdown = {}
    
    if mt5:
        positions = mt5.positions_get()
        account = mt5.account_info()
        equity = account.equity if account else 10300.0
        
        if positions:
            for p in positions:
                info = mt5.symbol_info(p.symbol)
                risk = 0.0
                if info and p.sl > 0:
                    tick_size = info.trade_tick_size if info.trade_tick_size > 0 else info.point
                    tick_value = info.trade_tick_value if info.trade_tick_value > 0 else info.point
                    sl_distance = abs(p.price_open - p.sl)
                    if tick_size > 0:
                        risk = p.volume * (sl_distance / tick_size) * tick_value
                breakdown[p.symbol] = {
                    "volume": p.volume,
                    "risk": round(risk, 2),
                    "risk_pct": round(risk / equity * 100, 2) if equity > 0 else 0,
                }
                total_risk += risk
        
        heat_pct = (total_risk / equity * 100) if equity > 0 else 0
    
    regimes = state.get("regimes", {})
    correlations = state.get("correlations", {})
    
    # Calculate total exposure
    long_exposure = 0
    short_exposure = 0
    if mt5:
        positions = mt5.positions_get()
        if positions:
            for p in positions:
                if p.type == 0:
                    long_exposure += p.volume
                else:
                    short_exposure += p.volume
    
    return jsonify({
        "heat_pct": round(heat_pct, 2),
        "total_risk": round(total_risk, 2),
        "breakdown": breakdown,
        "max_allowed_pct": 5.0,
        "regimes": regimes,
        "correlations": correlations,
        "long_exposure": round(long_exposure, 2),
        "short_exposure": round(short_exposure, 2),
    })


@app.route("/api/signals")
def api_signals():
    state = _load_state()
    signals = state.get("signals", {})
    return jsonify({"signals": signals})


@app.route("/api/expectancy")
def api_expectancy():
    """Calculate expectancy from MT5 history deals."""
    mt5 = _mt5()
    result = {}
    
    if mt5:
        from_date = datetime.now() - timedelta(days=90)
        deals = mt5.history_deals_get(from_date, datetime.now())
        if deals:
            symbol_pnls = {}
            for d in deals:
                pnl = d.profit + d.commission + d.swap
                if pnl == 0:
                    continue
                sym = d.symbol
                if sym not in symbol_pnls:
                    symbol_pnls[sym] = []
                symbol_pnls[sym].append(pnl)
            
            for sym, pnls in symbol_pnls.items():
                if len(pnls) < 5:
                    result[sym] = {"sufficient_data": False, "trade_count": len(pnls)}
                    continue
                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p <= 0]
                win_rate = len(wins) / len(pnls)
                avg_win = sum(wins) / len(wins) if wins else 0
                avg_loss = abs(sum(losses) / len(losses)) if losses else 0
                expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
                result[sym] = {
                    "expectancy": round(expectancy, 2),
                    "win_rate": round(win_rate * 100, 1),
                    "avg_win": round(avg_win, 2),
                    "avg_loss": round(avg_loss, 2),
                    "trade_count": len(pnls),
                    "sufficient_data": True,
                }
    
    return jsonify({"expectancies": result})


@app.route("/api/calendar")
def api_calendar():
    """Get upcoming economic events."""
    try:
        from multitf_platform.risk.v1_1.economic_calendar import EconomicCalendar
        cal = EconomicCalendar()
        upcoming = cal.get_upcoming(hours_ahead=48)
        blocked, reason = cal.is_blocked()
        return jsonify({
            "upcoming": upcoming,
            "blocked": blocked,
            "reason": reason,
        })
    except Exception as e:
        return jsonify({"upcoming": [], "blocked": False, "reason": str(e)})


@app.route("/api/slippage")
def api_slippage():
    """Get slippage diagnostics from state."""
    state = _load_state()
    # Slippage data would be stored in state by executor
    # For now return empty or from MT5 history comparison
    return jsonify({"slippage": state.get("slippage_diagnostics", {})})


@app.route("/api/mae_mfe")
def api_mae_mfe():
    """Get MAE/MFE diagnostics from MT5 history."""
    mt5 = _mt5()
    result = {}
    
    if mt5:
        from_date = datetime.now() - timedelta(days=30)
        deals = mt5.history_deals_get(from_date, datetime.now())
        # Simplified: can't get true MAE/MFE from deals alone without tick data
        # Return placeholder
        result = {"note": "MAE/MFE requires tick-level data during trade lifetime"}
    
    return jsonify({"mae_mfe": result})


if __name__ == "__main__":
    print("=" * 60)
    print("MultiTF Trading Dashboard")
    print("http://localhost:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False)
