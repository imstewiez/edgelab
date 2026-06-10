from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "data" / "outputs"


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path).replace([float("inf"), float("-inf")], pd.NA).fillna("")


def money(v: float) -> str:
    return f"€{round(float(v)):,}"


def main() -> int:
    p = argparse.ArgumentParser(description="Describe strict paper-forward candidate in plain English.")
    p.add_argument("--run", required=True)
    p.add_argument("--account", type=float, default=10000)
    p.add_argument("--risk", type=float, default=0.5, help="Risk percent per trade")
    args = p.parse_args()

    run_dir = OUTPUTS / args.run
    df = read_csv(run_dir / "FINAL_SHORTLIST_STRICT.csv")
    if df.empty:
        print("No FINAL_SHORTLIST_STRICT.csv found. Run tools\\run_final_shortlist.py --strict first.")
        return 1

    r = df.iloc[0].to_dict()
    risk_eur = args.account * args.risk / 100.0
    real_sumr = float(r.get("real_sumR", 0) or 0)
    maxdd = float(r.get("maxDD_R", 0) or 0)
    p95dd = float(r.get("p95_dd_R", 0) or 0)
    report = {
        "setup": {k: r.get(k, "") for k in ["setup_id", "symbol", "tf", "concept", "session", "lookback", "rr", "sl_mult"]},
        "decision": "PAPER-FORWARD ONLY. Do not trade live yet.",
        "account_example": {
            "account": args.account,
            "risk_percent_per_trade": args.risk,
            "one_R": risk_eur,
            "historical_result_estimate": round(real_sumr * risk_eur, 2),
            "historical_dd_estimate": round(maxdd * risk_eur, 2),
            "monte_carlo_p95_dd_estimate": round(p95dd * risk_eur, 2),
        },
        "metrics": {k: r.get(k, "") for k in ["final_rank_score", "gates_passed", "strict_pass", "real_sumR", "sumR_percentile", "permutation_score", "pf", "test_pf", "expR", "maxDD_R", "n", "profit_probability", "p95_dd_R", "wf_score", "wf_pass_rate", "stress_pass_rate", "portfolio_score", "avg_abs_corr", "paper_reason"]},
        "next_steps": [
            "Compile mt5/AUDUSD_M5_CompressionBreakout_Paper.mq5 in MetaEditor.",
            "Attach to AUDUSD M5 demo chart with PaperMode=true.",
            "Let it run for at least 30 calendar days or 30+ paper trades.",
            "Export the CSV log and compare paper R/DD against research expectations.",
        ],
    }
    print(json.dumps(report, indent=2))
    print("\nPlain English:")
    print(f"- 1R = {money(risk_eur)} on a {money(args.account)} account at {args.risk}% risk/trade.")
    print(f"- Historical research result: approx {money(real_sumr * risk_eur)}.")
    print(f"- Historical research DD: approx -{money(maxdd * risk_eur)}.")
    print(f"- Monte Carlo p95 DD: approx -{money(p95dd * risk_eur)}.")
    print("- This is paper-forward only, not live-ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
