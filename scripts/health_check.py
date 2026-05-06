import json
import subprocess
from pathlib import Path

print("=" * 60)
print("SYSTEM HEALTH CHECK")
print("=" * 60)

# Check scheduler
r = subprocess.run(["schtasks", "/query", "/tn", "MultiTF-PaperTrader", "/fo", "list"], capture_output=True, text=True)
print("\n--- SCHEDULER ---")
for line in r.stdout.strip().split("\n")[:4]:
    print(f"  {line}")

# Check portfolio state
print("\n--- PORTFOLIO STATE ---")
f = Path("state/portfolio_state.json")
if f.exists():
    d = json.load(open(f))
    sigs = d.get("signals", {})
    for sym in ["XAUUSD", "EURUSD", "NAS100"]:
        s = sigs.get(sym, {})
        if "error" in s:
            print(f"  {sym}: ERROR - {s['error']}")
        else:
            final = s.get("final_direction", 0)
            dir_str = "LONG" if final == 1 else "SHORT" if final == -1 else "FLAT"
            print(f"  {sym}: {dir_str} (scale={s.get('position_scale', 0):.2f})")
else:
    print("  No portfolio state file")

# Check MT5 positions
print("\n--- MT5 POSITIONS (REAL) ---")
try:
    import MetaTrader5 as mt5
    mt5.initialize()
    for sym in ["XAUUSD", "EURUSD", "NAS100"]:
        pos = mt5.positions_get(symbol=sym)
        if pos:
            p = pos[0]
            dir_str = "LONG" if p.type == 0 else "SHORT"
            sl_set = "YES" if p.sl > 0 else "NO"
            tp_set = "YES" if p.tp > 0 else "NO"
            print(f"  {sym}: {dir_str} {p.volume:.2f} lots @ {p.price_open:.5f}")
            print(f"         SL={p.sl:.5f} ({sl_set}) | TP={p.tp:.5f} ({tp_set}) | P&L=${p.profit:+.2f}")
        else:
            print(f"  {sym}: No position")
    mt5.shutdown()
except Exception as e:
    print(f"  MT5 check failed: {e}")

# Check files
print("\n--- FILES ---")
for f in ["trade_portfolio.bat", "src/multitf_platform/cli/portfolio_live.py", "src/multitf_platform/brokers/mt5/executor.py"]:
    exists = "OK" if Path(f).exists() else "MISSING"
    print(f"  {f}: {exists}")

print("\n" + "=" * 60)
