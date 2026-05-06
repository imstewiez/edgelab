# Paper Trading Guide - MultiTF v1.0.0

## What is Paper Trading?
Trading with a **demo account** on your broker (DPrime). You get:
- Real market prices
- Real spreads
- Real execution delays
- Fake money (no risk)

## Why Paper Trade First?
1. **Verify backtest assumptions** - Are fills as good as simulated?
2. **Catch bugs** - Is the signal generating correctly live?
3. **Build discipline** - Log every trade before risking capital
4. **Build track record** - 4-6 weeks of verified demo logs

## Minimum Viable Paper Trade
- **Duration:** 4-6 weeks minimum
- **Trades needed:** 20+ (to match backtest sample size)
- **Frequency:** Check signals every hour (or run auto)
- **Logging:** Every signal, every fill, every slippage event

---

## Step 1: Open DPrime Demo Account

1. Go to DPrime website -> Open Demo Account
2. Select **MetaTrader 5**
3. Choose account type: **ECN** (match your planned live account)
4. Set leverage: **1:100** (conservative)
5. Deposit amount: **$10,000** demo (matches backtest notional)

**Important:** Use the EXACT same server, symbol names, and account type as your planned live account. Spreads and execution can differ between account types.

---

## Step 2: Trading Parameters (Demo)

```
Symbol: XAUUSD.s
Timeframe: H1
Strategy: MultiTF v1.0.0 (H1 MOM100 + H4 MOM50 confirmation)
Position sizing: 0.01 lots per $10,000 equity
Max spread: 30 points (0.30)
Max daily loss: $200 (2% of $10,000)
Circuit breaker: Stop trading if equity drops to $8,500 (-15%)
```

**Why 0.01 lots?**
- Backtest assumes 1.0 lot per $100,000
- $10,000 demo = 0.10x backtest size
- But we want EXTRA conservative for paper trading
- 0.01 lots = $0.01 per point on XAUUSD
- Typical trade P&L: $1-5 per trade

---

## Step 3: Daily Routine

### Every Hour (or set alarm for 5 min before each hour):
1. Open MT5
2. Check current MultiTF signal (Long / Short / Flat)
3. If signal changed from last hour:
   - Note the price
   - Place market order (0.01 lots)
   - Screenshot the order
   - Log entry time, price, spread, signal
4. If signal unchanged:
   - Hold position
   - Log "hold"

### End of Day:
1. Export daily trades from MT5 (Account History -> Save as Report)
2. Compare actual P&L vs backtest predicted P&L
3. Calculate slippage: (Fill price - Signal price) in points
4. Log any anomalies (wider spreads, rejected orders, delays)

### End of Week:
1. Calculate weekly Sharpe (if enough data)
2. Compare to backtest weekly Sharpe
3. If diverging >30% from backtest -> investigate why

---

## Step 4: Validation Checklist

After 4 weeks of paper trading, check:

| Criterion | Minimum | Target |
|-----------|---------|--------|
| Number of trades | 15 | 25+ |
| Actual trades vs backtest | Within 20% | Exact match |
| Average slippage | < 5 points | < 2 points |
| Win rate | 35-55% | 40-50% |
| Profit Factor | > 1.0 | > 1.3 |
| Max DD | < 15% | < 10% |
| Spread during entries | < 25 points | < 15 points |
| Rejected orders | 0 | 0 |
| Backtest vs live Sharpe | Within 50% | Within 30% |

**If 7/9 criteria pass -> consider $500 live test**
**If < 5/9 pass -> strategy has execution problems, fix before live**

---

## Step 5: What to Watch For

### Red Flags (Stop Paper Trading):
- Demo Sharpe < 0 after 4 weeks
- Consistently negative slippage (broker filling against you)
- Spreads consistently > 50 points during entries
- Orders rejected or requoted frequently
- Strategy signals not matching backtest signals

### Yellow Flags (Investigate):
- Win rate significantly lower than backtest (35% vs 46%)
- Average loss larger than backtest predicted
- Drawdown clustering in specific sessions

### Green Flags (Proceed to Live):
- Demo Sharpe within 30% of backtest
- Slippage minimal and random (not systematic)
- Spreads match backtest assumptions
- No execution issues

---

## Step 6: From Paper to Live

### Only proceed if:
1. 4-6 weeks paper trading complete
2. Demo Sharpe > 0.5
3. Max DD < 15%
4. Execution matches backtest assumptions
5. You understand every losing trade

### Live test ($500):
```
Deposit: $500
Lot size: 0.01 lots (maximum)
Risk per trade: ~$1-2
Circuit breaker: Stop at $425 (-15%)
Duration: 3 months minimum
```

---

## Logging Template

Create a spreadsheet with these columns:

| Date | Time | Signal | Entry Price | Fill Price | Slippage | Spread | Lots | P&L | Cumulative P&L | Equity | Notes |
|------|------|--------|-------------|------------|----------|--------|------|-----|----------------|--------|-------|

---

## Important Reminders

1. **Demo fills are often BETTER than live** - DPrime demo may have zero slippage. Live will be worse. Add 20% slippage buffer to expectations.

2. **Your psychology changes with real money** - Demo = calm. Live = panic. The strategy doesn't change, YOU do.

3. **4 weeks is minimum, not sufficient** - 4 weeks proves execution. 3-6 months proves edge.

4. **Don't optimize during paper trade** - If strategy underperforms, log why. Don't change parameters to make it fit.

5. **Weekend gaps matter** - If holding over weekend, Monday open may gap against you. Demo may not show this accurately.
