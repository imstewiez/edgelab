# EdgeLab Paper-Forward Spec — AUDUSD M5 Compression Breakout

Generated from run: `pipeline_20260610_072404`

Strict candidate:

```text
setup_id: AUDUSD_M5_compression_breakout_1ff8259ee1
symbol: AUDUSD
timeframe: M5
concept: compression_breakout
session: overlap
lookback: 48
rr: 2.5
sl_mult: 2.0
```

## Research metrics

```text
strict_pass: true
gates_passed: 7
real_sumR: 29.151R
PF: 2.037
test_pf: 4.223
maxDD_R: 6.523R
Monte Carlo p95 DD: 13.039R
profit_probability: 0.97
walk-forward pass rate: 0.80
stress pass rate: 0.857
portfolio_score: 100
avg_abs_corr: 0.065
permutation_score: 100
sumR_percentile: 1.0
```

## Plain-English thesis

This setup tries to catch a directional expansion after volatility/range compression during the London/New York overlap window.

The edge hypothesis is:

1. AUDUSD compresses.
2. Price breaks a 48-bar range during the overlap session.
3. EMA21 is aligned above/below EMA55.
4. Entry is taken on the next bar/open after confirmation.
5. Stop is ATR-based; take profit is 2.5R.

## Signal rules

Evaluate only on closed M5 candles.

### Long signal

```text
compression on previous candle = true
current closed candle close > highest high of previous 48 candles
EMA21 > EMA55
session hour is >= 13 and < 17 broker/server time
spread <= max allowed spread
```

### Short signal

```text
compression on previous candle = true
current closed candle close < lowest low of previous 48 candles
EMA21 < EMA55
session hour is >= 13 and < 17 broker/server time
spread <= max allowed spread
```

## Compression definition

```text
ATR14 rank over 500 bars < 0.35
range rank over 200 bars < 0.45
```

In the MT5 EA this is approximated from the local terminal history. It should be checked against Python signals before any live use.

## Position model

```text
entry: next bar / current market price after signal confirmation
stop loss: 2.0 * ATR14
take profit: 2.5R
risk: configurable, default 0.50% per trade
max positions: 1 per symbol/magic
mode: paper/logging only by default
```

## Hard safety rules

This setup is not production-ready.

Do not enable live trading until it passes all paper-forward rules below.

### Paper-forward promotion rule

Minimum requirements before even considering small-live:

```text
30 calendar days minimum
30+ paper trades minimum
positive paper R
paper max DD <= 8R preferred, <= 12R hard warning
no severe spread/slippage problems
signal frequency similar to backtest expectations
no obvious broker/session-time mismatch
```

## What to monitor

Track every signal/trade with:

```text
time
side
entry
SL
TP
ATR
spread
risk distance
expected R
paper result R
reason for exit
broker server hour
```

## Current decision

```text
Status: PAPER-FORWARD ONLY
Primary candidate: yes
EA/live-ready: no
Portfolio-ready: no
```
