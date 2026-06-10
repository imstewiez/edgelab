# EdgeLab Project Context

## Purpose

EdgeLab is a local quant research environment for FX, gold, indices, commodities and CFD-style MT5 market data. Its purpose is to discover, reject, validate and stress-test trading strategy hypotheses before anything is considered for an MT5 Expert Advisor.

The project must never assume profitability from a single backtest. Every strategy is treated as a hypothesis until it survives multiple validation gates and then forward testing.

## Current objective

Build a serious research-to-EA pipeline for strategies with strong return potential and controlled drawdown. The practical focus is XAUUSD/FX/CFD style trading through MT5, with the option to add crypto/futures data later.

The system should become increasingly intelligent by accumulating curated research context, but research notes are not proof. They are used to create better experiments, better features, better validation and better reporting.

DOM/order book is currently deprioritized because MT5 FX/CFD DOM is broker-specific, often limited or synthetic, and historical DOM is not available unless recorded live. EdgeLab may still collect it later as an optional filter, not a core alpha source.

## Repository

Repository: `imstewiez/edgelab`

Main components:

```text
apps/engine    FastAPI backend and quant research logic
apps/web       React/Vite compact dashboard
tools/mt5      MT5 helper tools and recorders
tools/crypto   Notes/planned crypto order-book collectors
docs/          Research notes and implementation context
data/          Local runtime data folder, not source of truth in git
```

## Current UI / local workflow

The dashboard is intentionally compact with three top-level areas:

```text
Pipeline | Dados | Resultados
```

The preferred workflow is:

```text
1. Dados -> upload MT5 CSV/ZIP
2. Pipeline -> Run Full Pipeline
3. Watch progress 0-100%, steps and logs
4. Resultados -> inspect final candidates and stage details
```

`Run Full Pipeline` runs:

```text
Import -> Features -> Discover -> Validate -> Walk-forward -> Stress -> Monte Carlo -> Sensitivity -> Portfolio Risk
```

The backend exposes job status, percent, stage, steps, logs, error and result. The UI must always make it obvious whether the system is running, done, failed or waiting.

## Core pipeline stages

### Stage 1 — Discovery

Implemented in `apps/engine/quantlab_core.py`.

Responsibilities:

- Import raw MT5 CSV/ZIP exports.
- Normalize OHLC/spread columns.
- Build feature caches.
- Screen many strategy variants.
- Assign stable `setup_id` using full variant identity: symbol, timeframe, concept, session, lookback, RR and ATR stop multiplier.
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
- Setup identity preservation.

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
- Preserve original discovery metrics and setup identity for downstream stages.

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

### Stage 4 — Broker-aware execution stress

Implemented in `apps/engine/execution_stress.py`.

Purpose:

Check whether candidates survive bad execution assumptions by re-running the strategy with different spread/slippage/delay scenarios.

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

Important limitation: Stage 4 is now broker-aware and uses `spread_points` when available, otherwise broker profile defaults from `data/broker_profile.json`. It is still OHLC-based and must eventually be upgraded with tick/spread history before EA export.

### Stage 5 — Monte Carlo robustness

Implemented in `apps/engine/monte_carlo.py`.

Purpose:

- Reconstruct trade R sequences for candidates.
- Simulate reshuffled trade order.
- Simulate missed trades and adverse noise/slippage.
- Estimate tail drawdown and loss-streak risk.
- Use exact setup handoffs rather than loose concept matching.

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
- Uses exact setup handoffs.

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
- `spread` or `spread_points` should be included when possible.

Data health distinguishes:

```text
missing-data gaps
market closure gaps
coverage length
row count
duplicates
```

Upload rules:

- Accept `.csv` and `.zip`.
- ZIP extraction should only import CSV files.
- File names are sanitized.
- Upload errors should be reported per file.
- Data should be listed in the dashboard before running the pipeline.

DOM/order book:

- Deprioritized for FX/CFDs for now.
- MT5 DOM recorder exists at `tools/mt5/EdgeLab_DOM_Recorder.mq5`, but should be treated as optional data collection.
- Crypto order-book plan exists in `tools/crypto/README.md`.

## Curated transcript research context

A large transcript file containing trading, quant trading, algo trading, strategy development, MQL, risk and portfolio discussions was reviewed and distilled into `docs/research_transcript_digest.md`.

The main conclusion: EdgeLab should not try to build one magic EA. It should become a structured research platform that discovers many small, measurable, robust, diversified edges and only later exports conservative EA modules for the few that survive validation and forward incubation.

### Research framework to adopt

The strongest framework from the transcripts is:

```text
event-defining feature -> contextual features -> outcome labels -> model/rules -> risk protocol -> validation -> deployment
```

For EdgeLab this means every concept should be broken into:

1. **Event definition** — what timestamp is worth studying?
2. **Context features** — why might this event behave differently this time?
3. **Outcome label** — what happened after the event?
4. **Execution/risk model** — how the trade is entered, exited and sized.
5. **Validation gates** — whether the apparent edge survives adversarial testing.

### Feature engineering principles

Good features transform raw data into measurable ideas. Raw OHLC alone is usually not enough.

Useful feature classes:

```text
continuous   ATR, realized volatility, normalized distance, MA slope, wick/body ratio
binary       sweep yes/no, breakout yes/no, session open yes/no, compression break yes/no
ordinal      volatility bucket, trend bucket, session/regime class
reference    prior day high/low, Asian range, rolling highs/lows, moving averages
outcome      forward return, TP/SL first, double-barrier result, MFE/MAE
```

Important rule: price-distance features should usually be normalized by ATR, percent, z-score or rolling range. Raw price differences do not compare well across history or symbols.

### Event definition principles

Trying to predict every candle is usually forecasting noise. Event filters define the sample that is worth studying.

Useful event ideas for EdgeLab:

```text
prior day/session high-low sweep and reclaim
CUSUM-style cumulative movement event using ATR-normalized thresholds
compression followed by expansion
breakout through rolling/session range
violent breakout using short ATR / long ATR ratio
session transition events such as Asian range -> London or London -> NY
```

Bad event definitions:

```text
every candle
overly frequent weak events
overly rare events with no sample size
human labels that cannot be computed deterministically
```

### Cascade/pyramiding transcript conclusion

The cascade ordering idea is useful only as a **trade-management module**, not as an entry edge.

It should be modeled as:

```text
flat TP/SL
trail stop
break-even shift
partial close
cascade/pyramid with max_layers, shared stop, max heat and cost/margin checks
```

Rules:

- Test only on already-profitable base entries.
- Never allow unlimited stacking.
- Compare against normal TP/SL on the same entry signal.
- Include giveback, spread, slippage and margin impact.
- Never use money management to hide a weak entry edge.

### Quant strategy examples conclusion

The transcript examples around Russell rebalancing, rubber-band mean reversion, MFI/RSI, monthly ETF rotation, weekly RSI, turn-of-month, volatility and bonds are useful as strategy families, not as plug-and-play CFD systems.

Keep:

- Simple rules can work.
- Seasonality and regime effects should be tested.
- Mean reversion works better on some assets than others.
- Momentum/rotation and mean reversion are separate families.
- Time-in-market matters.

Do not blindly port:

- ETF-specific rules to leveraged CFDs.
- Equity seasonal rules without CFD broker/session/calendar validation.
- Any claimed performance without transaction costs and out-of-sample evidence.

### Validation principles from transcripts

Backtests are easy to fool. Validation must be adversarial.

Keep these gates:

```text
walk-forward
Monte Carlo of trade order / missed trades / adverse noise
parameter sensitivity across stable zones
execution stress with spread/slippage/delay
permutation/randomization test
forward paper incubation
```

New roadmap stages to add later:

```text
Stage 8 — Permutation/randomization test
Stage 9 — Forward incubation tracker
```

### Portfolio and diversification principles

The transcripts strongly support portfolio thinking:

- Run multiple independent models.
- Different instruments may require different models.
- Avoid over-leveraging one strategy.
- Do not rely on unproven regime prediction.
- Let diversified models run together so winners offset losers.
- Measure correlation and common factor exposure.
- Use an incubation/promote/demote workflow.

Recommended strategy lifecycle:

```text
Research candidate
-> validation pass
-> paper incubation
-> small live allocation
-> production allocation
-> demote/disable if forward decay appears
```

### Reactive vs predictive framing

A useful framing from the transcripts: stop trying to predict every movement. Define events and react to measurable structure.

For CFDs this maps well to:

```text
sweep -> reclaim confirmation
compression -> expansion confirmation
volatility shock -> follow-through or mean-reversion study
breakout -> continuation/rejection outcome study
```

### Order-flow/iceberg caution

Order-flow and iceberg ideas are conceptually interesting but weak for MT5 FX/CFDs unless real depth/tick data exists.

Keep only as measurable OHLC proxies:

```text
sweep/reclaim proxy
range compression proxy
impulse/expansion proxy
wick rejection proxy
```

Reject as current core alpha:

```text
true iceberg detection without L2/L3 data
assuming MT5 DOM is real centralized market depth
claiming an OHLC pattern proves institutional flow
```

### Risk sizing principles

Kelly-style sizing is theoretical context only. Full Kelly is not suitable for the default EA path because drawdowns can be intolerable.

EdgeLab should eventually support:

```text
fixed fractional risk
fractional Kelly only after stable forward data
max risk per strategy
max portfolio heat
max correlated exposure
drawdown-based risk reduction
```

Default EA behavior should stay conservative.

## Good vs weak information from transcripts

### High-value information

- Feature engineering framework.
- Event-defining features.
- Contextual features and outcome labels.
- Normalization of financial features.
- Walk-forward and Monte Carlo validation.
- Permutation/randomization tests.
- Portfolio diversification and correlation control.
- Forward incubation before live deployment.
- Strategy simplicity and robust parameter zones.

### Medium-value information

- Cascade/pyramiding as a trade-management module.
- Retail strategy categories such as RSI/MFI mean reversion, turn-of-month, rotation and volatility strategies.
- Discretionary pattern talk when translated into measurable features.
- Kelly sizing as a theoretical reference only.

### Low-value or risky information

- Marketing-style monthly return claims.
- Short backtests with no live/forward proof.
- Secret/premium strategy claims without rules.
- Order-flow claims without real order book data.
- Any idea that money management can rescue a weak entry edge.
- Over-optimized parameter values.

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
POST /api/jobs/full-pipeline
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

## How to run locally

```bat
cd C:\Users\steve\edgelab
git pull origin main
START_ALL.bat
```

Manual alternative:

```bat
START_ENGINE.bat
START_WEB.bat
```

Dashboard:

```text
http://localhost:5173
```

Engine health:

```text
http://127.0.0.1:8765/health
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

1. Add explicit event-study output:
   - `events.csv`
   - event count by symbol/timeframe/concept
   - sample-size warning
   - outcome distribution
2. Add feature/outcome lab:
   - feature type
   - normalization method
   - feature distribution snapshots
   - double-barrier labels
3. Add CUSUM/volatility-normalized event filters.
4. Add permutation/randomization validation stage.
5. Add forward paper-trading incubation tracker.
6. Add trade-management module comparison:
   - fixed TP/SL
   - trailing stop
   - break-even
   - partials
   - cascade/pyramid with strict max layers
7. Add EA module/config exporter only for strategies that pass all gates.
8. Add portfolio sizing, max heat and strategy promotion/demotion workflow.
9. Add better reporting/export package per selected strategy.

## Session handoff instruction

In a fresh session, start by reading this file first. Treat it as the main project context and do not assume trading profitability. Continue from the latest GitHub `main` branch and verify file state before editing.
