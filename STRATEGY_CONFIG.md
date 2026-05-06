# XAUUSD MOM100 Strategy Configuration

**Final strategy as of 2026-05-06**

---

## Signal

```python
Symbol: XAUUSD.s
Timeframe: H1
Lookback: 100 bars (~4.2 days)
Signal: close.pct_change(100)
  - Long when momentum > 0
  - Short when momentum < 0
  - Always in market (immediate flip on signal change)
```

## Why MOM100?

| Lookback | Bull Sharpe | Sideways Sharpe | Min Sharpe |
|----------|------------|-----------------|------------|
| MOM20 | 1.046 | **-0.013** | -0.013 ❌ |
| MOM50 | 0.099 | 0.461 | 0.099 |
| MOM80 | 0.566 | 0.814 | 0.566 |
| **MOM100** | **0.880** | **0.909** | **0.880** ✅ |
| MOM120 | 0.528 | 0.641 | 0.528 |

MOM100 is the **sweet spot** — filters noise better than short lookbacks, reacts faster than MOM120.

## Expected Performance (Walk-Forward)

| Regime | Sharpe | Ann Return | Ann Vol | Max DD | Trades | Win Rate |
|--------|--------|------------|---------|--------|--------|----------|
| Bull (2021-2026) | 1.103 | 23.2% | 21.0% | -23.0% | ~900 | 43% |
| Sideways (2016-2019) | 0.925 | 10.7% | 11.5% | -15.1% | ~600 | 43% |

## Position Sizing

**Conservative setting (recommended):**
```python
base_lot_size = 0.005  # 0.005 lot per $1,000 equity
```

This gives **0.5x exposure** vs full size:
- Expected Sharpe: ~0.85 bull / ~0.63 sideways
- Expected return: ~9-12% annually (bull), ~4-5% (sideways)
- Expected volatility: ~10-11% (bull), ~7% (sideways)
- Expected max DD: ~-12% (bull), ~-12% (sideways)

**Account examples:**
| Equity | Lot Size | Margin (1:1000) | Notional |
|--------|----------|-----------------|----------|
| $1,000 | 0.01 | ~$4.50 | ~$4,500 |
| $5,000 | 0.025 | ~$11 | ~$11,250 |
| $10,000 | 0.05 | ~$23 | ~$22,500 |

**Minimum viable account: ~$2,000** (to trade 0.01 lots at 0.5x sizing)

## Risk Controls

| Control | Setting | Purpose |
|---------|---------|---------|
| Max daily loss | 2% of balance | Circuit breaker |
| Max spread | 30 points | Avoid trading during news |
| Slippage tolerance | 10 points | Execution protection |
| Position sizing | Dynamic by equity | Auto-de-risk as account shrinks |

## Costs

DPrime ECN:
- Spread: ~$0.20 (20 points)
- Commission: $7/lot round-turn
- Total round-trip: ~2.5 bps at $4,500/oz

## What NOT to Do

- ❌ Do NOT add trend filters — they hurt performance
- ❌ Do NOT add volatility targeting — causes catastrophic losses
- ❌ Do NOT trade session-filtered — Asian session contributes positively
- ❌ Do NOT use momentum thresholds — they reduce Sharpe
- ❌ Do NOT trade below 0.01 lots — transaction costs overwhelm alpha

## Execution

Run:
```bash
python src/execution/mt5_bridge.py
```

The bridge:
1. Connects to MT5
2. Reads last 110 H1 bars
3. Calculates 100-bar momentum
4. Enters/exits positions accordingly
5. Checks risk limits before every trade

## Forward Test Plan

1. Fund account with $2,000-$5,000
2. Run bridge for 4-8 weeks with 0.01-0.025 lots
3. Compare live P&L to backtest expectations
4. If live Sharpe > 0.5 after 2 months, scale up gradually
5. Withdraw profits monthly; never risk more than 50% of initial capital

## Known Limitations

- **Regime risk**: Untested in severe bear markets (2012-2015 gold crash)
- **Sample size**: Only ~7 years of H1 data validated
- **Single asset**: All eggs in one basket (gold)
- **Live slippage**: NFP/Fed events may exceed modeled costs
- **Psychology**: 43% win rate means 6-7 losses in a row are common

## Dukascopy Download Status

- ✅ 2016-2019 (3 years) — validated
- ⏳ 2019-2026 (7 years) — downloading
- ⏳ 2012-2016 (bear market) — pending
