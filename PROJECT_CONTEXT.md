# EdgeLab Project Context

## Purpose

EdgeLab is a local quant research environment for FX, gold, indices, commodities and CFD-style market data. Its purpose is to discover, reject, validate and stress-test trading strategy hypotheses before anything is considered for an MT5 Expert Advisor.

The project must never assume profitability from a single backtest. Every strategy is treated as a hypothesis until it survives multiple validation gates and then forward testing.

## Current objective

Build a serious research-to-EA pipeline for strategies with strong return potential and controlled drawdown. The practical focus is XAUUSD/FX/CFD style trading through MT5, with the option to add crypto/futures data later.

DOM/order book is currently deprioritized because MT5 FX/CFD DOM is broker-specific, often limited or synthetic, and historical DOM is not available unless recorded live. EdgeLab may still collect it later as an optional filter, not a core alpha source.

## Repository

Repository: `imstewiez/edgelab`

Main components:

```text
apps/engine    FastAPI backend and quant research logic
apps/web       React/Vite dashboard
tools/mt5      MT5 helper tools and recorders
tools/crypto   Notes/planned crypto order-book collectors
data/          Local runtime data folder, not source of truth in git
```

## Core pipeline stages

### Stage 1 — Discovery

Implemented in `apps/engine/quantlab_core.py`.

Responsibilities:

- Import raw MT5 CSV/ZIP exports.
- Normalize OHLC/spread columns.
- Build feature caches.
- Screen many strategy variants.
- Produce candidate, rejected and all-ideas CSV outputs.

Main outputs:

```text
data/outputs/<run>/all_edges.csv
data/outputs/<run>/candidate_edges.csv
data/outputs/<run>/rejected_edges.csv
data/outputs/<run>/DISCOVERY_REPORT.md
data/outputs/<run>/edge_cards.json
```

Important language: these are **screened ideas**, not proven systems.

### Stage 2 — Robustness validation

Implemented in `apps/engine/robustness.py`.

Checks:

- Trade count.
- Profit factor.
- Out-of-sample PF.
- Expectancy.
- R drawdown.
- Loss streak.
- Positive month percentage.
- Conservative stress PF approximation.

Statuses:

```text
robust_candidate
watchlist
not_robust
```

Output:

```text
stage2_validation.csv
VALIDATION_SUMMARY.json
```

### Stage 3 — Walk-forward matrix

Implemented in `apps/engine/walkforward.py`.

Purpose:

- Split history into multiple time windows.
- Re-run candidate rules in each window.
- Check whether the idea survives different market periods.

Metrics:

```text
wf_pass
wf_watchlist
wf_fail
wf_windows
wf_pass_rate
wf_median_pf
wf_min_pf
wf_median_expR
wf_maxDD_R
```

Output:

```text
stage3_walkforward.csv
WALKFORWARD_SUMMARY.json
```

### Stage 4 — Execution stress

Implemented in `apps/engine/execution_stress.py`.

Purpose:

Check whether candidates survive bad execution assumptions.

Scenarios:

```text
base
spread_x2
spread_x3
slippage_light
slippage_heavy
entry_delay
combined_bad_fill
```

Statuses:

```text
stress_pass
stress_watchlist
stress_fail
```

Output:

```text
stage4_execution_stress.csv
EXECUTION_STRESS_SUMMARY.json
```

Important limitation: current Stage 4 uses conservative approximations from backtest stats. Future improvement should use actual tick/spread history.

### Stage 5 — Monte Carlo robustness

Implemented in `apps/engine/monte_carlo.py`.

Purpose:

- Reconstruct trade R sequences for candidates.
- Simulate reshuffled trade order.
- Simulate missed trades and adverse noise/slippage.
- Estimate tail drawdown and loss-streak risk.

Metrics:

```text
profit_probability
p05_totalR
p95_dd_R
p99_dd_R
p95_loss_streak
ruin_probability
mc_score
mc_status
```

Statuses:

```text
mc_pass
mc_watchlist
mc_fail
```

Output:

```text
stage5_monte_carlo.csv
MONTE_CARLO_SUMMARY.json
```

### Stage 6 — Parameter sensitivity

Implemented in `apps/engine/sensitivity.py`.

Purpose:

Check whether an edge works only on one lucky setting or across nearby settings.

It varies:

```text
lookback
RR
ATR SL multiplier
```

Metrics:

```text
variants_tested
variants_passed
pass_rate
median_pf
min_pf
median_expR
maxDD_R
sensitivity_score
sensitivity_status
```

Statuses:

```text
sensitivity_pass
sensitivity_watchlist
sensitivity_fail
```

Output:

```text
stage6_sensitivity.csv
SENSITIVITY_SUMMARY.json
```

### Stage 7 — Portfolio/risk heat

Implemented in `apps/engine/portfolio_risk.py`.

Purpose:

Evaluate whether multiple passing strategies are actually diversified or just duplicate/correlated exposure.

Current approximation:

- Rebuilds monthly R streams for candidates.
- Calculates correlation matrix.
- Measures average absolute correlation.
- Estimates combined monthly drawdown.
- Flags high-correlation pairs.

Metrics:

```text
portfolio_pass
portfolio_watchlist
portfolio_fail
portfolio_monthly_sumR
portfolio_monthly_dd_R
avg_pair_corr
high_corr_pairs
```

Output:

```text
stage7_portfolio_risk.csv
stage7_strategy_correlation.csv
PORTFOLIO_RISK_SUMMARY.json
```

## Current strategy concept universe

Implemented in `apps/engine/strategy_universe.py`.

Groups include:

```text
trend
breakout
pullback
mean_reversion
smc_liquidity
session_models
volatility_regime
microstructure_dom
risk_management
```

Active/tested OHLC concepts include:

```text
breakout_trend
breakout_fast
pullback_ema21
compression_breakout
sweep_reclaim
prev_day_sweep
asian_breakout
equal_high_low_sweep
bos_breakout
choch_reversal
fvg_rebalance
order_block_retest
```

SMC/ICT names are treated as measurable hypotheses, not proof of institutional flow.

## Data philosophy

Preferred current data source:

- MT5 CSV/ZIP exports from the broker environment to be traded.
- Multiple symbols and timeframes.
- Best value from H1/H4/D1 for robust research, with M5/M15/M30 useful when there is enough history.

Data health distinguishes:

```text
missing-data gaps
market closure gaps
coverage length
row count
duplicates
```

DOM/order book:

- Deprioritized for FX/CFDs for now.
- MT5 DOM recorder exists at `tools/mt5/EdgeLab_DOM_Recorder.mq5`, but should be treated as optional data collection.
- Crypto order-book plan exists in `tools/crypto/README.md`.

## API endpoints

Backend root: `http://127.0.0.1:8765`

Core endpoints:

```text
GET  /health
GET  /api/catalog
GET  /api/strategy-universe
GET  /api/outputs
GET  /api/jobs
POST /api/upload
POST /api/jobs/import
POST /api/jobs/features
POST /api/jobs/discover
POST /api/jobs/scan
```

Validation endpoints:

```text
POST /api/jobs/validate
GET  /api/validation
POST /api/jobs/walkforward
GET  /api/walkforward
POST /api/jobs/execution-stress
GET  /api/execution-stress
POST /api/jobs/monte-carlo
GET  /api/monte-carlo
POST /api/jobs/sensitivity
GET  /api/sensitivity
POST /api/jobs/portfolio-risk
GET  /api/portfolio-risk
```

## Dashboard

Frontend app: `apps/web`.

Current dashboard shows the main pipeline through Monte Carlo. API client includes Stage 6 and Stage 7 functions. If the UI has not yet been visually expanded for Stage 6/7, add cards/tables for:

```text
Sensitivity pass/watchlist/fail
Portfolio pass/watchlist/fail
Portfolio monthly DD
Average pair correlation
High correlation pairs
```

## How to run locally

```bat
cd C:\Users\steve\edgelab
git pull origin main
START_ENGINE.bat
START_WEB.bat
```

Suggested full research flow:

```text
Data -> Import Only
Data -> Build Features Only
Run -> Discover
Run -> Validate
Run -> Walk-forward
Run -> Stress
Run -> Monte Carlo
Run/API -> Sensitivity
Run/API -> Portfolio Risk
```

Stage 6/7 may be run via API until dashboard buttons are added:

```text
POST http://127.0.0.1:8765/api/jobs/sensitivity
POST http://127.0.0.1:8765/api/jobs/portfolio-risk
```

with optional JSON body:

```json
{"scan_name":"your_run_name"}
```

## Important current limitation

`EA-ready` deliberately remains 0. No strategy should be marked EA-ready until it passes at least:

```text
discovery
robustness
walk-forward
execution stress
Monte Carlo
parameter sensitivity
portfolio/risk heat
forward paper tracking
broker execution checks
```

## Next recommended upgrades

1. Add Stage 6/7 buttons and tables to the React dashboard if not already visible.
2. Add tick/spread-aware execution stress using real spread history.
3. Add forward paper-trading tracker.
4. Add EA module/config exporter only for strategies that pass all gates.
5. Add portfolio sizing and max heat optimizer.
6. Add better reporting/export package per selected strategy.

## Session handoff instruction

In a fresh session, start by reading this file first. Treat it as the main project context and do not assume trading profitability. Continue from the latest GitHub `main` branch and verify file state before editing.
