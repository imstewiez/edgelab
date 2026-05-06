import json
from pathlib import Path

print("=" * 60)
print("Portfolio Positions")
print("=" * 60)

for sym in ["XAUUSD", "EURUSD", "NAS100"]:
    f = Path(f"state/portfolio_{sym}_broker.json")
    if f.exists():
        d = json.load(open(f))
        pos = d.get("position")
        if pos:
            dir_str = "LONG" if pos["direction"] == 1 else "SHORT"
            print(f"{sym:8s} | Equity ${d['equity']:>7.2f} | Trades {d['total_trades']:>3d} | {dir_str} {pos['size_lots']:.2f} lots @ {pos['entry_price']:.4f} | uP&L ${pos['unrealized_pnl']:+.2f}")
        else:
            print(f"{sym:8s} | Equity ${d['equity']:>7.2f} | Trades {d['total_trades']:>3d} | FLAT")
    else:
        print(f"{sym:8s} | No state file")

# Check combined
total = sum(json.load(open(Path(f"state/portfolio_{sym}_broker.json")))["equity"] for sym in ["XAUUSD", "EURUSD", "NAS100"] if Path(f"state/portfolio_{sym}_broker.json").exists())
print(f"\nTotal equity: ${total:.2f}")
