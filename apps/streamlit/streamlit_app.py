from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "apps" / "engine"
DATA = ROOT / "data"
OUTPUTS = DATA / "outputs"
sys.path.insert(0, str(ENGINE))

try:
    from quantlab_core import STORE, build_features, import_raw_data, list_outputs, read_data_health
    from discovery_fast import discover_edges
    from inefficiency_lab import run_inefficiency_lab
except Exception as exc:  # pragma: no cover
    st.error(f"Could not import EdgeLab engine modules: {exc}")
    st.stop()

INCUBATION_TRACKER = STORE / "incubation" / "incubation_candidates.csv"

st.set_page_config(page_title="CoreEA EdgeLab Streamlit", layout="wide", page_icon="🧪")
st.title("🧪 CoreEA EdgeLab — Python Research Dashboard")
st.caption("Optional zero-budget Streamlit dashboard. Uses your existing local EdgeLab engine/data; no React/Node required for this view.")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path).replace([float("inf"), float("-inf")], pd.NA).fillna("")


def run_dir(name: str) -> Path:
    return OUTPUTS / name


def fmt_money(x: float) -> str:
    try:
        return f"€{round(float(x)):,}"
    except Exception:
        return "-"


def num(v, default=0.0):
    try:
        if v == "" or pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


def add_account_examples(df: pd.DataFrame, account: float, risk_pct: float) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    risk_eur = account * (risk_pct / 100.0)
    if "sumR" in out.columns:
        r_col = "sumR"
    elif "real_sumR" in out.columns:
        r_col = "real_sumR"
    elif "paper_sumR" in out.columns:
        r_col = "paper_sumR"
    else:
        r_col = None
    if "maxDD_R" in out.columns:
        dd_col = "maxDD_R"
    elif "standalone_monthly_dd_R" in out.columns:
        dd_col = "standalone_monthly_dd_R"
    elif "p95_dd_R" in out.columns:
        dd_col = "p95_dd_R"
    elif "paper_maxDD_R" in out.columns:
        dd_col = "paper_maxDD_R"
    else:
        dd_col = None
    if r_col:
        out["example_profit_eur"] = out[r_col].apply(lambda v: round(num(v) * risk_eur, 2))
    if dd_col:
        out["example_dd_eur"] = out[dd_col].apply(lambda v: round(num(v) * risk_eur, 2))
    return out


with st.sidebar:
    st.header("Controls")
    account_size = st.number_input("Example account size (€)", min_value=1000, max_value=1_000_000, value=10_000, step=1000)
    risk_pct = st.slider("Risk per trade (%)", 0.1, 3.0, 1.0, 0.1)
    st.info(f"1R = {fmt_money(account_size * risk_pct / 100)} at {risk_pct:.1f}% risk/trade.")
    outputs = list_outputs()
    run_names = [o["name"] for o in outputs]
    selected_run = st.selectbox("Output run", run_names, index=0 if run_names else None, placeholder="No runs yet") if run_names else ""
    mode = st.selectbox("Discovery mode", ["balanced", "deep", "quick"], index=0)

    st.divider()
    if st.button("Import raw data"):
        with st.spinner("Importing raw data..."):
            st.write(import_raw_data(st.write))
    if st.button("Build features"):
        with st.spinner("Building features..."):
            st.write(build_features(st.write))
    if st.button("Run discovery scan"):
        scan_name = f"streamlit_{mode}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
        with st.spinner(f"Running {mode} discovery..."):
            st.write(discover_edges(scan_name, mode=mode, logger=st.write))
        st.rerun()
    if st.button("Run Inefficiency Lab"):
        name = selected_run or f"inefficiency_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
        with st.spinner("Profiling liquidity / price-action inefficiencies..."):
            st.write(run_inefficiency_lab(scan_name=name, mode="balanced", logger=st.write))
        st.rerun()

health = read_data_health()
summary = health.get("summary", {}) if isinstance(health, dict) else {}
cols = st.columns(5)
cols[0].metric("Good datasets", summary.get("good", 0))
cols[1].metric("Usable datasets", summary.get("usable", 0))
cols[2].metric("Weak datasets", summary.get("weak", 0))
cols[3].metric("Runs", len(outputs))
cols[4].metric("1R example", fmt_money(account_size * risk_pct / 100))

if not selected_run:
    st.warning("No output run found yet. Import data, build features and run a discovery scan.")
    st.stop()

rd = run_dir(selected_run)
candidates = read_csv(rd / "candidate_edges.csv")
all_edges = read_csv(rd / "all_edges.csv")
validation = read_csv(rd / "stage2_validation.csv")
walkforward = read_csv(rd / "stage3_walkforward.csv")
stress = read_csv(rd / "stage4_execution_stress.csv")
mc = read_csv(rd / "stage5_monte_carlo.csv")
portfolio = read_csv(rd / "stage7_portfolio_risk.csv")
perm = read_csv(rd / "stage8_permutation_test.csv")
final_shortlist = read_csv(rd / "FINAL_SHORTLIST.csv")
strict_shortlist = read_csv(rd / "FINAL_SHORTLIST_STRICT.csv")
incubation_all = read_csv(INCUBATION_TRACKER)
incubation = incubation_all[incubation_all.scan_name.astype(str) == selected_run].copy() if not incubation_all.empty and "scan_name" in incubation_all.columns else incubation_all
ineff = read_csv(rd / "inefficiency_lab.csv")

st.subheader(f"Run: {selected_run}")
st.caption("Research results are not EA-ready until they survive walk-forward, execution stress, randomization/permutation and paper-forward incubation.")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("All tests", len(all_edges))
m2.metric("Candidates", len(candidates))
m3.metric("Validation rows", len(validation))
m4.metric("Strict shortlist", len(strict_shortlist))
m5.metric("Incubation rows", len(incubation))

tabs = st.tabs(["Shortlist", "Coverage", "Inefficiencies", "Stage Tables", "Explain Stats"])

with tabs[0]:
    if not strict_shortlist.empty:
        source_name = "FINAL_SHORTLIST_STRICT"
        source = strict_shortlist
        st.success("Showing strict paper-forward shortlist. This excludes setups with weak/zero walk-forward survival.")
    elif not final_shortlist.empty:
        source_name = "FINAL_SHORTLIST"
        source = final_shortlist
        st.warning("Showing non-strict final shortlist. Run the strict reducer to filter by walk-forward/stress/permutation.")
    elif not incubation.empty:
        source_name = "Incubation"
        source = incubation
    elif not perm.empty:
        source_name = "Permutation"
        source = perm
        st.warning("Showing raw permutation table because no FINAL_SHORTLIST_STRICT.csv exists yet.")
    elif not portfolio.empty:
        source_name = "Portfolio"
        source = portfolio
    elif not mc.empty:
        source_name = "Monte Carlo"
        source = mc
    elif not stress.empty:
        source_name = "Execution Stress"
        source = stress
    elif not walkforward.empty:
        source_name = "Walk-forward"
        source = walkforward
    elif not validation.empty:
        source_name = "Validation"
        source = validation
    else:
        source_name = "Candidates"
        source = candidates
    source = add_account_examples(source, account_size, risk_pct)
    st.write(f"### Best current shortlist — {source_name}")
    if source.empty:
        st.info("No shortlist rows yet. Run tools\\run_final_shortlist.py --strict for this output run.")
    else:
        show_cols = [c for c in ["setup_id", "symbol", "tf", "concept", "session", "strict_pass", "final_rank_score", "gates_passed", "pf", "test_pf", "wf_pass_rate", "stress_pass_rate", "permutation_score", "sumR_percentile", "real_sumR", "maxDD_R", "p95_dd_R", "avg_abs_corr", "example_profit_eur", "example_dd_eur", "verdict", "paper_reason", "promotion_rule"] if c in source.columns]
        st.dataframe(source[show_cols].head(50), width="stretch", height=520)
        if "example_profit_eur" in source.columns or "example_dd_eur" in source.columns:
            st.success(f"Example uses account {fmt_money(account_size)} and {risk_pct:.1f}% risk/trade. 1R = {fmt_money(account_size * risk_pct / 100)}.")

with tabs[1]:
    st.write("### What was actually tested")
    if all_edges.empty:
        st.info("No all_edges.csv found for this run.")
    else:
        c1, c2 = st.columns(2)
        sym_counts = all_edges.groupby("symbol").size().reset_index(name="tests").sort_values("tests", ascending=False)
        cand_sym = candidates.groupby("symbol").size().reset_index(name="candidates").sort_values("candidates", ascending=False) if not candidates.empty else pd.DataFrame(columns=["symbol", "candidates"])
        c1.plotly_chart(px.bar(sym_counts, x="symbol", y="tests", title="All tests by symbol"), width="stretch")
        c2.plotly_chart(px.bar(cand_sym, x="symbol", y="candidates", title="Candidates by symbol"), width="stretch")
        c3, c4 = st.columns(2)
        if "concept" in all_edges.columns:
            concept_counts = all_edges.groupby("concept").size().reset_index(name="tests").sort_values("tests", ascending=False)
            c3.plotly_chart(px.bar(concept_counts, x="concept", y="tests", title="Tests by concept"), width="stretch")
        if "tf" in all_edges.columns:
            tf_counts = all_edges.groupby("tf").size().reset_index(name="tests").sort_values("tests", ascending=False)
            c4.plotly_chart(px.bar(tf_counts, x="tf", y="tests", title="Tests by timeframe"), width="stretch")

with tabs[2]:
    st.write("### Liquidity / Price Action / Inefficiency profiler")
    if ineff.empty:
        st.info("No inefficiency_lab.csv for this run yet. Use the sidebar button 'Run Inefficiency Lab'.")
    else:
        top = ineff.sort_values("inefficiency_score", ascending=False).head(60)
        st.dataframe(top, width="stretch", height=520)
        fig = px.scatter(top, x="events", y="inefficiency_score", color="family", hover_data=["symbol", "tf", "pattern", "side", "interpretation"], title="Inefficiency score vs event sample")
        st.plotly_chart(fig, width="stretch")

with tabs[3]:
    for name, df in [("Strict Final Shortlist", strict_shortlist), ("Final Shortlist", final_shortlist), ("Candidates", candidates), ("Validation", validation), ("Walk-forward", walkforward), ("Execution Stress", stress), ("Monte Carlo", mc), ("Portfolio", portfolio), ("Permutation", perm), ("Incubation", incubation)]:
        with st.expander(name, expanded=name == "Strict Final Shortlist"):
            if df.empty:
                st.info(f"No {name} data yet.")
            else:
                st.dataframe(df.head(300), width="stretch", height=420)

with tabs[4]:
    st.markdown(
        f"""
### Plain-English interpretation

**R / Risk unit**  
1R is one trade's planned risk. With your current example settings, **1R = {fmt_money(account_size * risk_pct / 100)}**.

**Strict Shortlist**  
This is the serious paper-forward list. It requires meaningful walk-forward survival, execution stress survival, permutation strength, decent PF and controlled drawdown.

**Profit Factor (PF)**  
PF = gross wins / gross losses. PF 1.00 means breakeven before hidden costs. PF 1.25+ can be interesting. PF 1.60+ is strong but may be overfit if sample size is small.

**Drawdown in R**  
If a setup has 7R drawdown and you risk 1% per trade on €10k, that is roughly -7%, or -€700. If you risk 0.5%, it is roughly -€350.

**Score**  
Internal ranking score. It is not profit. It ranks candidates by expectancy, PF, out-of-sample PF, monthly stability, drawdown and robustness gates.

**Paper Incubation**  
This means the setup is only being tracked. It is **not live-ready**. A real EA should only be exported after forward/paper evidence.

**Buyers/Sellers/Liquidity caveat**  
With CSV OHLC data we infer liquidity zones, sweeps and trapped traders from price action. We do not see real order-book depth unless you later connect broker/order-flow data.
"""
    )
