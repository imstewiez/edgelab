from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HEALTH = DATA / "data_health.json"
FEATURE_CATALOG = DATA / "feature_catalog.csv"
CATALOG = DATA / "catalog.csv"
OUT = DATA / "DATA_AUDIT_REPORT.json"

MIN_COVERAGE_DAYS = {
    "M1": 365,
    "M5": 540,
    "M15": 720,
    "M30": 720,
    "H1": 1095,
    "H4": 1460,
    "D1": 1825,
}

GOOD_COVERAGE_DAYS = {
    "M1": 730,
    "M5": 1095,
    "M15": 1460,
    "M30": 1460,
    "H1": 1825,
    "H4": 2190,
    "D1": 2920,
}

MIN_ROWS = {
    "M1": 150_000,
    "M5": 80_000,
    "M15": 35_000,
    "M30": 20_000,
    "H1": 12_000,
    "H4": 4_000,
    "D1": 1_250,
}

GOOD_ROWS = {
    "M1": 300_000,
    "M5": 150_000,
    "M15": 70_000,
    "M30": 35_000,
    "H1": 25_000,
    "H4": 8_000,
    "D1": 2_000,
}

CORE_SYMBOLS = {"XAUUSD", "NAS100", "US30", "EURUSD", "GBPUSD", "USDJPY", "GBPJPY"}


def load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path).fillna("")


def judge_dataset(row: dict) -> dict:
    symbol = str(row.get("symbol", "")).upper()
    tf = str(row.get("tf", "")).upper()
    rows = int(float(row.get("rows", 0) or 0))
    days = int(float(row.get("coverage_days", 0) or 0))
    gaps = int(float(row.get("gap_count", 0) or 0))
    quality_score = int(float(row.get("quality_score", 0) or 0))
    has_spread = bool(row.get("has_spread_points", False))

    min_days = MIN_COVERAGE_DAYS.get(tf, 365)
    good_days = GOOD_COVERAGE_DAYS.get(tf, min_days * 2)
    min_rows = MIN_ROWS.get(tf, 1_000)
    good_rows = GOOD_ROWS.get(tf, min_rows * 2)

    issues: list[str] = []
    strengths: list[str] = []
    score = 0

    if days >= good_days:
        score += 30; strengths.append("long coverage")
    elif days >= min_days:
        score += 20; strengths.append("usable coverage")
    else:
        issues.append(f"coverage too short for {tf}: {days}d < {min_days}d")

    if rows >= good_rows:
        score += 25; strengths.append("good row count")
    elif rows >= min_rows:
        score += 15; strengths.append("usable row count")
    else:
        issues.append(f"low row count for {tf}: {rows} < {min_rows}")

    if gaps == 0:
        score += 15; strengths.append("no suspicious gaps")
    elif gaps <= max(3, days // 120):
        score += 8; strengths.append("limited suspicious gaps")
    else:
        issues.append(f"many suspicious gaps: {gaps}")

    if quality_score >= 75:
        score += 15; strengths.append("health score good")
    elif quality_score >= 55:
        score += 8; strengths.append("health score usable")
    else:
        issues.append(f"weak health score: {quality_score}")

    if has_spread:
        score += 10; strengths.append("spread data available")
    else:
        issues.append("no spread_points column; broker-cost model uses defaults")

    if symbol in CORE_SYMBOLS:
        score += 5

    if score >= 75 and not any("too short" in x or "low row" in x for x in issues):
        status = "research_ready"
    elif score >= 55:
        status = "usable_with_caution"
    else:
        status = "not_enough_data"

    return {
        "symbol": symbol,
        "tf": tf,
        "rows": rows,
        "coverage_days": days,
        "gap_count": gaps,
        "quality_score": quality_score,
        "has_spread_points": has_spread,
        "data_status": status,
        "audit_score": int(score),
        "strengths": strengths,
        "issues": issues,
    }


def main() -> int:
    health = load_json(HEALTH)
    catalog = read_csv(CATALOG)
    feature_catalog = read_csv(FEATURE_CATALOG)

    if not health:
        print("No data_health.json found. Run the pipeline import/features first.")
        return 1

    datasets = health.get("datasets", [])
    if not datasets:
        print("No datasets found in data_health.json. Upload/import data first.")
        return 1

    feature_flags = set()
    if not feature_catalog.empty and {"symbol", "tf"}.issubset(feature_catalog.columns):
        feature_flags = {f"{str(r.symbol).upper()}_{str(r.tf).upper()}" for _, r in feature_catalog.iterrows()}

    rows = []
    for d in datasets:
        judged = judge_dataset(d)
        judged["has_feature_cache"] = f"{judged['symbol']}_{judged['tf']}" in feature_flags
        if not judged["has_feature_cache"]:
            judged["issues"].append("feature cache missing; run Build Features")
        rows.append(judged)

    df = pd.DataFrame(rows)
    counts = df.data_status.value_counts().to_dict() if not df.empty else {}
    core_ready = df[(df.symbol.isin(CORE_SYMBOLS)) & (df.data_status == "research_ready")]
    no_spread = df[~df.has_spread_points]

    verdict = "not_ready"
    if counts.get("research_ready", 0) >= 12 and len(core_ready) >= 6:
        verdict = "good_for_research"
    elif counts.get("research_ready", 0) >= 6 or counts.get("usable_with_caution", 0) >= 12:
        verdict = "usable_but_limited"

    report = {
        "verdict": verdict,
        "summary": {
            "datasets_total": int(len(df)),
            "research_ready": int(counts.get("research_ready", 0)),
            "usable_with_caution": int(counts.get("usable_with_caution", 0)),
            "not_enough_data": int(counts.get("not_enough_data", 0)),
            "core_research_ready": int(len(core_ready)),
            "datasets_without_spread_points": int(len(no_spread)),
            "feature_catalog_rows": int(len(feature_catalog)),
            "catalog_rows": int(len(catalog)),
        },
        "interpretation": {
            "good_for_research": "Enough OHLC history to search for candidate inefficiencies. Still not enough alone for live EA deployment.",
            "usable_but_limited": "Can run discovery, but conclusions must be treated carefully and validated with out-of-sample/paper-forward.",
            "not_ready": "Data is not sufficient for reliable strategy research yet.",
        },
        "minimums_used": {
            "min_coverage_days": MIN_COVERAGE_DAYS,
            "min_rows": MIN_ROWS,
            "good_coverage_days": GOOD_COVERAGE_DAYS,
            "good_rows": GOOD_ROWS,
        },
        "datasets": rows,
        "top_issues": [],
    }

    issue_counts: dict[str, int] = {}
    for r in rows:
        for issue in r["issues"]:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
    report["top_issues"] = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:15]

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps({"verdict": report["verdict"], **report["summary"], "report_path": str(OUT)}, indent=2))
    print("\nTop issues:")
    for issue, count in report["top_issues"][:8]:
        print(f"- {count}x {issue}")
    print("\nBest datasets:")
    best = df.sort_values(["audit_score", "coverage_days", "rows"], ascending=[False, False, False]).head(12)
    for _, r in best.iterrows():
        print(f"- {r.symbol} {r.tf}: {r.data_status} | score={r.audit_score} | rows={r.rows} | days={r.coverage_days} | gaps={r.gap_count} | spread={r.has_spread_points}")
    return 0 if report["verdict"] != "not_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
