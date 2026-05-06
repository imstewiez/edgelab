import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

state = json.load(open("state/paper_state.json"))
audit_lines = list(open("logs/audit.jsonl")) if Path("logs/audit.jsonl").exists() else []

print("=" * 60)
print("Paper Trading Live Status")
print("=" * 60)
print(f"Position:   {state['position']}")
print(f"Equity:     {state['equity']:.2f}")
print(f"Balance:    {state['balance']:.2f}")
print(f"Unrealized: {state.get('unrealized_pl', 0):.2f}")
print(f"Peak:       {state['peak_equity']:.2f}")
print(f"Drawdown:   {(state['equity']/state['peak_equity'] - 1)*100:.2f}%")
print(f"Trades:     {state['total_trades']}")
print(f"Updated:    {state['last_updated']}")
print()

if audit_lines:
    print("=" * 60)
    print("Recent Audit Log (last 10)")
    print("=" * 60)
    for line in audit_lines[-10:]:
        d = json.loads(line)
        ts = d["timestamp"]
        sig = d["signal"]
        risk = d["risk_action"]
        final = d.get("final_direction", 0)
        price = sig.get("price", 0)
        print(f"{ts} | signal={sig['direction']:+3d} | risk={risk:8s} | final={final:+3d} | price={price:.2f}")
else:
    print("No audit log found.")
