# MultiTF v1.0.0: 8-Week Deep Dive Research Report

**Completed:** 2026-05-06
**Assets tested:** XAUUSD, EURUSD, NAS100, XAUEUR, XAGUSD, GER40, US30
**Data:** Dec 2021 -- May 2026 (4.5 years), M1--D1 timeframes
**Status:** MultiTF v1.0.0 FROZEN. All improvements go into risk/execution layers.

---

## Executive Summary

| Phase | Finding | Actionable? |
|-------|---------|-------------|
| 1.1 Time Patterns | Overlap session (+0.322% exp), best hours 02:00/09:00/13-15/17/21 | Yes -- session filter |
| 1.2 Calendar | Friday best (+0.358%), NFP week toxic (p=0.0008), Sep/Jan/Oct best | Yes -- NFP week block |
| 1.3 Weekend Gaps | 77.7% fill in 4h, direction not predictive | No -- don't trade gaps |
| 2.1 Multi-Asset | Works on 5 assets with correct costs. EURUSD safest (DD -5.1%) | Yes -- multi-asset portfolio |
| 2.2 Lead-Lag | Minimal cross-asset prediction. EURUSD->NAS100 weak causality | No -- no lead-lag edge |
| 3 Scalping | Viable on synthetic M15 (Sharpe ~2.0) but data quality concern | Maybe -- needs real M15 data |
| 4 News Calendar | NFP day +/-24h filter: Sharpe +0.099. Over-filtering kills alpha | Yes -- NFP day block |
| 5 Microstructure | Spread data synthetic (constant 20 pts). Volume filtering hurts | No -- no micro edge |
| 6 Portfolio | Inv-vol portfolio: Sharpe 2.491, DD -4.8%. Low correlations (0.09-0.17) | Yes -- multi-asset live |

---

## Phase 1: Time-Pattern Microstructure

### 1.1 Session & Hour-of-Day Analysis

**Sessions:**
- Asian (00-08 UTC): +0.15% expectancy, 51.2% WR
- London (08-16 UTC): **Weakest** -- -0.08% expectancy, 48.9% WR
- NY (13-21 UTC): +0.18% expectancy, 51.8% WR
- Overlap (13-16 UTC): **Best** -- +0.322% expectancy, 53.5% WR
- Off-hours (21-00 UTC): +0.12% expectancy, 50.8% WR

**Best hours (UTC):**
- 02:00 (+0.41% exp)
- 09:00 (+0.35% exp)
- 13:00 -- 15:00 (+0.30% to +0.38% exp)
- 17:00 (+0.28% exp)
- 21:00 (+0.22% exp)

**Worst hours:**
- 12:00 (-0.25% exp)
- 07:00 (-0.18% exp)
- 23:00 (-0.15% exp)

**Recommendation:** Consider session-based position sizing (larger during overlap, smaller during London open).

### 1.2 Calendar Effects

**Weekday:**
- Monday: **Worst** (-0.12% avg, p=0.03)
- Friday: **Best** (+0.358% avg, p=0.008)

**Week-of-month:**
- Week 1 (NFP week): **Significantly worse** (-0.28% avg, p=0.0008)
- Week 2: **Best** (+0.22% avg, p=0.04)
- Week 3: Neutral
- Week 4: Slightly positive
- Week 5: Variable (only some months)

**Month:**
- Best: Sep (+0.45%), Jan (+0.38%), Oct (+0.32%)
- Worst: May (-0.15%), Jun (-0.12%)

**NFP week effect:**
- 53 trades in NFP weeks vs 620 in non-NFP weeks
- Average return per trade: -0.28% vs +0.15%
- T-test: p=0.0008 (highly significant)

**Recommendation:** Block new trades during NFP week (first week of month).

### 1.3 Weekend Gap Analysis

- **77.7%** of gaps fill within 4 hours
- **88.2%** fill within 24 hours
- Gap direction **not predictive** of Monday open direction (p=0.96)
- Average gap size: $1.20 (0.03%)

**Recommendation:** Do not trade based on weekend gap direction. Gap-fading is not an edge.

---

## Phase 2: Multi-Asset Validation

### 2.1 Single-Asset Performance

**CRITICAL FIX:** Previous research had cost model bug (metal lot sizes applied to FX). With auto-detected costs:

| Asset | Sharpe | Max DD | Trades | Data Quality |
|-------|--------|--------|--------|--------------|
| XAUUSD | 1.895 | -13.8% | 673 | Full 4.5y |
| NAS100 | 1.334 | -17.8% | 728 | Full 4.5y |
| XAUEUR | 1.202 | -19.2% | ~400 | 7 months |
| EURUSD | 1.105 | **-5.1%** | 812 | Full 4.5y |
| XAGUSD | 0.692 | -38.1% | ~350 | 7 months |
| GER100 | -0.45 | -45% | ~200 | 7 months |
| US30 | -0.38 | -42% | ~180 | 7 months |

**Key insight:** EURUSD has the **lowest drawdown** (-5.1%) making it the safest asset for live trading, even though its Sharpe is lower.

### 2.2 Cross-Asset Lead-Lag

- **Cross-correlations very weak** (< 0.04)
- Only significant Granger causality: EURUSD momentum -> NAS100 future returns (p=0.0202)
- No reliable predictive relationships

**Conclusion:** Assets move contemporaneously during risk events but do not predict each other. This is good for portfolio diversification.

---

## Phase 3: Scalping Feasibility

**⚠️ Data quality warning:** M15 data was resampled from H1 (OHLC fraud). Real M15 would have more noise.

| Strategy | Tight ECN | Typical | Wide Retail |
|----------|-----------|---------|-------------|
| MOM20 | 2.071 | 2.000 | 1.914 |
| MOM10+40 | 1.986 | 1.810 | 1.599 |
| MOM10 | 1.721 | 1.614 | 1.486 |
| SessionOpen | -1.003 | -1.176 | -1.383 |

**Conclusion:** Simple momentum is surprisingly robust to cost compression. Session-open breakout is dead. **Scalping may be viable with real M15 data and tight spreads.**

---

## Phase 4: Economic Calendar

| Filter | Sharpe | Delta | Trades Lost |
|--------|--------|-------|-------------|
| None (baseline) | 1.978 | -- | -- |
| NFP day +/-24h | **2.077** | **+0.099** | 23 |
| NFP week | 2.023 | +0.045 | 146 |
| FOMC day +/-24h | 1.778 | -0.200 | 9 |
| All high-impact | 1.605 | -0.373 | 36 |

**Key finding:** NFP day filter is the only net-positive. Over-filtering destroys alpha.

**Recommendation:** Add NFP day +/-24h blocker to risk wrapper.

---

## Phase 5: Market Microstructure

- Spread data from MT5 exports appears synthetic (constant 20 points, 99.9% within 23-25)
- Spread filtering has zero effect
- Volume filtering hurts performance (low volume = Asian session = still profitable)

**Conclusion:** No microstructure edge found with current data quality. Live system must use real-time spread from broker.

---

## Phase 6: Portfolio Construction

| Portfolio | Sharpe | Return | Max DD |
|-----------|--------|--------|--------|
| Inv-vol (all) | **2.491** | +28.7% | **-4.8%** |
| Equal-weight | 2.469 | +40.7% | -6.9% |
| Pair XAUUSD+EURUSD | 2.243 | +32.1% | -8.0% |
| Best single (XAUUSD) | 2.059 | +67.1% | -13.7% |

**Correlation matrix:**
```
        XAUUSD  EURUSD  NAS100
XAUUSD   1.000   0.166   0.091
EURUSD   0.166   1.000   0.137
NAS100   0.091   0.137   1.000
```

**Key insight:** Inverse-volatility weighting achieves **Sharpe 2.491** with only **-4.8% drawdown** -- a massive improvement over single-asset XAUUSD (-13.7% DD).

**Trade-off:** Lower absolute return (28.7% vs 67.1%) but vastly superior risk-adjusted performance.

---

## Recommendations for Live System v1.1

### High Priority (implement immediately)
1. **NFP week filter** -- Block new trades during first week of month
2. **Multi-asset portfolio** -- Trade XAUUSD + EURUSD + NAS100 with inv-vol weights
3. **Session sizing** -- Increase size during overlap (13-16 UTC), reduce during London open

### Medium Priority
4. **NFP day filter** -- Block +/- 24h around first Friday
5. **Real-time spread** -- Use live MT5 spread data instead of historical average
6. **Calendar awareness** -- Reduce size in May/June, increase in Sep/Jan/Oct

### Low Priority / Not Actionable
7. Weekend gap trading -- Not an edge
8. Cross-asset lead-lag -- No predictive power
9. Scalping M15 -- Needs real M15 data validation
10. Volume filtering -- Hurts performance

---

## Data Quality Issues Identified

1. **Spread data synthetic** -- MT5 exports show almost constant 20-point spread. Real spread varies 20-50+ points.
2. **M15 data resampled** -- No true M15 bars available. H1 resampling overstates scalping viability.
3. **Dukascopy downloads incomplete** -- Batches 0-3 complete, batches 4-9 pending.

---

## Next Steps

1. Implement v1.1 risk wrapper with NFP + session filters
2. Build multi-asset live pipeline (currently single-asset XAUUSD)
3. Source real M15 tick data for scalping validation
4. Continue Dukascopy downloads for 10-year backfill
5. A/B test single-asset vs portfolio on paper trading
