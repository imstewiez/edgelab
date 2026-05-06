"""MultiTF Trading Dashboard — Live web UI for portfolio monitoring.

Runs a Flask server that reads MT5 data, portfolio state, and logs
to serve a real-time trading dashboard.

Usage:
    cd fx-trading-bot/dashboard
    python app.py
    # Open http://localhost:5000 in your browser
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


def _mt5_connected():
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
    return {"positions": {}, "executions": [], "equity_history": []}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/account")
def api_account():
    mt5 = _mt5_connected()
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
    mt5 = _mt5_connected()
    if not mt5:
        return jsonify({"positions": []})
    
    positions = mt5.positions_get()
    result = []
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
    state = _load_state()
    executions = state.get("executions", [])
    
    # Group by closed trades
    trades = []
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
                "open_time": ex.get("timestamp", ""),
            }
        elif action == "CLOSE":
            if symbol in open_trades:
                ot = open_trades.pop(symbol)
                ot["close_time"] = ex.get("timestamp", "")
                ot["profit"] = ex.get("profit", 0)
                trades.append(ot)
    
    # Still open from history
    for symbol, ot in open_trades.items():
        ot["profit"] = 0
        trades.append(ot)
    
    return jsonify({"trades": trades[-50:]})  # Last 50


@app.route("/api/stats")
def api_stats():
    state = _load_state()
    executions = state.get("executions", [])
    equity_history = state.get("equity_history", [])
    
    profits = []
    wins = 0
    losses = 0
    total_profit = 0.0
    total_loss = 0.0
    
    for ex in executions:
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
    profit_factor = (total_profit / total_loss) if total_loss > 0 else 0
    
    # Equity curve
    eq_curve = []
    running = 300.0  # Starting estimate
    for pt in equity_history:
        if isinstance(pt, dict):
            running = pt.get("equity", running)
            eq_curve.append({"time": pt.get("time", ""), "equity": running})
        else:
            eq_curve.append({"time": "", "equity": running})
    
    # Calculate drawdown
    peak = 0
    max_dd = 0
    for pt in eq_curve:
        eq = pt["equity"]
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
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
        "max_drawdown_pct": round(max_dd, 2),
        "equity_curve": eq_curve[-100:],  # Last 100 points
    })


@app.route("/api/logs")
def api_logs():
    logs = []
    
    # Read latest log files
    log_files = sorted(glob(str(LOGS_DIR / "*.log")) + glob(str(LOGS_DIR / "*.txt")))
    for lf in log_files[-3:]:  # Last 3 log files
        try:
            with open(lf) as f:
                lines = f.readlines()
                for line in lines[-200:]:  # Last 200 lines each
                    line = line.strip()
                    if line:
                        level = "INFO"
                        if "ERROR" in line or "error" in line.lower():
                            level = "ERROR"
                        elif "WARN" in line or "warning" in line.lower():
                            level = "WARN"
                        elif "EXECUTING" in line or "OPENED" in line or "CLOSED" in line:
                            level = "TRADE"
                        elif "BLOCKED" in line or "BLOCK" in line:
                            level = "BLOCK"
                        
                        logs.append({
                            "time": "",
                            "level": level,
                            "message": line[:500],
                        })
        except Exception:
            pass
    
    # Also read portfolio_live output if captured
    return jsonify({"logs": logs[-300:]})  # Last 300 entries


@app.route("/api/risk")
def api_risk():
    state = _load_state()
    mt5 = _mt5_connected()
    
    # Portfolio heat
    heat_pct = 0.0
    total_risk = 0.0
    breakdown = {}
    
    if mt5:
        positions = mt5.positions_get()
        if positions:
            account = mt5.account_info()
            equity = account.equity if account else 300.0
            
            for p in positions:
                info = mt5.symbol_info(p.symbol)
                if info:
                    tick_size = info.trade_tick_size if info.trade_tick_size > 0 else info.point
                    tick_value = info.trade_tick_value if info.trade_tick_value > 0 else info.point
                    sl_distance = abs(p.price_open - p.sl) if p.sl > 0 else 0
                    if tick_size > 0:
                        ticks = sl_distance / tick_size
                        risk = p.volume * ticks * tick_value
                    else:
                        risk = 0
                    total_risk += risk
                    breakdown[p.symbol] = {
                        "volume": p.volume,
                        "risk": round(risk, 2),
                        "risk_pct": round(risk / equity * 100, 2) if equity > 0 else 0,
                    }
            
            heat_pct = (total_risk / equity * 100) if equity > 0 else 0
    
    # Regime info (from state if saved)
    regimes = state.get("regimes", {})
    correlations = state.get("correlations", {})
    
    return jsonify({
        "heat_pct": round(heat_pct, 2),
        "total_risk": round(total_risk, 2),
        "breakdown": breakdown,
        "max_allowed_pct": 5.0,
        "regimes": regimes,
        "correlations": correlations,
    })


if __name__ == "__main__":
    print("=" * 60)
    print("MultiTF Trading Dashboard")
    print("Open http://localhost:5000 in your browser")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False)
