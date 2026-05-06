import json
from pathlib import Path
from collections import Counter

lines = list(open("logs/audit_20260506.jsonl"))
print(f"Total audit entries: {len(lines)}")

signals = [json.loads(l) for l in lines if json.loads(l).get("event") == "signal"]
risks = [json.loads(l) for l in lines if json.loads(l).get("event") == "risk_decision"]

print(f"Signal events: {len(signals)}")
print(f"Risk events: {len(risks)}")

# Direction distribution
dirs = Counter(s["direction"] for s in signals)
print(f"\nSignal directions: LONG={dirs[1]}, SHORT={dirs[-1]}, FLAT={dirs[0]}")

# Risk action distribution
actions = Counter(r["action"] for r in risks)
print(f"Risk actions: {dict(actions)}")

# Final direction distribution
finals = Counter(r["final_direction"] for r in risks)
print(f"Final directions: LONG={finals[1]}, SHORT={finals[-1]}, FLAT={finals[0]}")

# Show last 5 signals
print("\nLast 5 signals:")
for s in signals[-5:]:
    print(f"  {s['timestamp']} | dir={s['direction']:+2d} | h1={s['h1_momentum']:+.4f} | h4={s['h4_momentum']:+.4f}")

# Show last 5 risk decisions
print("\nLast 5 risk decisions:")
for r in risks[-5:]:
    print(f"  {r['timestamp']} | action={r['action']:8s} | final={r['final_direction']:+2d} | scale={r['scale']:.2f}")
