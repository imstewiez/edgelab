from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "apps" / "engine"
OUT = ROOT / "data" / "BENCHMARK_REPORT.json"


def run_step(name: str, code: str) -> dict:
    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ENGINE),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3600,
    )
    elapsed = round(time.perf_counter() - started, 2)
    return {
        "name": name,
        "ok": proc.returncode == 0,
        "elapsed_sec": elapsed,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }


def main() -> int:
    steps = [
        ("import", "from quantlab_core import import_raw_data; print(import_raw_data(lambda m: None))"),
        ("features", "from quantlab_core import build_features; print(build_features(lambda m: None))"),
        ("balanced_discovery", "from discovery_fast import discover_edges; print(discover_edges('benchmark_balanced', mode='balanced', logger=lambda m: None))"),
        ("validation", "from robustness import run_validation; print(run_validation('benchmark_balanced', logger=lambda m: None))"),
        ("walkforward", "from walkforward import run_walkforward; print(run_walkforward('benchmark_balanced', logger=lambda m: None))"),
        ("stress", "from execution_stress import run_execution_stress; print(run_execution_stress('benchmark_balanced', logger=lambda m: None))"),
        ("monte_carlo", "from monte_carlo import run_monte_carlo; print(run_monte_carlo('benchmark_balanced', logger=lambda m: None))"),
    ]
    results = []
    total_start = time.perf_counter()
    for name, code in steps:
        print(f"Running benchmark step: {name}...")
        res = run_step(name, code)
        results.append(res)
        print(json.dumps({"step": name, "ok": res["ok"], "elapsed_sec": res["elapsed_sec"]}, indent=2))
        if not res["ok"]:
            break
    report = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_elapsed_sec": round(time.perf_counter() - total_start, 2),
        "results": results,
        "notes": "This benchmark runs a balanced pipeline under local hardware and writes timing bottlenecks.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nBenchmark report: {OUT}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
