# Phase 2: Multi-Asset Expansion — Findings

**Date:** 2026-05-06  
**Strategy:** MultiTF v1.0.0 (H1 MOM100 + H4 MOM50)  
**Discovery:** Previous research had a **cost model bug** that masked viable assets

---

## The Bug

Previous research (`RESEARCH_SUMMARY.md`) reported EURUSD and NAS100 as "flat/negative." This was caused by hardcoding `lot_size=100.0` and `pip_value=1.0` (metal specs) for ALL assets in the backtest.

**Correct cost model per asset:**
| Asset | Type | Lot Size | Pip Value | Typical Price |
|-------|------|----------|-----------|---------------|
| XAUUSD | Metal | 100 oz | $1/lot | $2,000 |
| XAGUSD | Metal | 5,000 oz | $50/lot | $25 |
| EURUSD | FX | 100,000 units | $10/lot | $1.08 |
| NAS100 | Index | 1 contract | $1/point | $15,000 |
| GER40 | Index | 1 contract | €1/point | $20,000 |
| US30 | Index | 1 contract | $1/point | $40,000 |

With auto-detected costs, results are completely different.

---

## Multi-Asset Results (Corrected)

| Asset | Sharpe | Ann Return | Max DD | Trades | WinRate | Profit Factor | Data | Verdict |
|-------|--------|-----------|--------|--------|---------|---------------|------|---------|
| **XAUUSD** | **1.895** | **+30.2%** | **-13.8%** | 673 | 46.2% | 1.84 | 4.3y | ✅ Core |
| **NAS100** | **1.334** | **+27.4%** | **-17.8%** | 728 | 44.4% | 1.29 | 4.3y | ✅ Diversify |
| **XAUEUR** | **1.202** | **+31.3%** | **-19.2%** | 178 | 37.1% | 1.73 | 7mo | ⚠️ Limited |
| **EURUSD** | **1.105** | **+7.7%** | **-5.1%** | 812 | 45.2% | 1.42 | 4.3y | ✅ Safe |
| **XAGUSD** | **0.692** | **+43.4%** | **-38.1%** | 170 | 37.1% | 1.45 | 7mo | ⚠️ High risk |
| GER40 | -0.882 | -14.6% | -16.2% | 270 | 41.9% | 0.83 | 7mo | ❌ |
| US30 | -1.751 | -23.6% | -21.1% | 206 | 37.4% | 0.64 | 7mo | ❌ |

### Viable Assets (Sharpe > 0.5)

**Tier 1 — Core Portfolio (4+ years data):**
1. **XAUUSD** — Sharpe 1.895, the original validated edge
2. **NAS100** — Sharpe 1.334, strong diversification (correlation with XAUUSD TBD)
3. **EURUSD** — Sharpe 1.105, lowest return but also **lowest DD (-5.1%)**. The "safe" asset.

**Tier 2 — Speculative (7 months data only):**
4. **XAUEUR** — Sharpe 1.202, gold in EUR terms. Good for EUR-based accounts.
5. **XAGUSD** — Sharpe 0.692, but **-38.1% max DD**. Too risky for small accounts.

### Non-Viable
- **GER40** — Negative Sharpe, momentum doesn't work on German index
- **US30** — Negative Sharpe, Dow Jones is mean-reverting on H1/H4

---

## Key Insights

### EURUSD: The "Safe" Asset
- Lowest return (+7.7%) but also **lowest drawdown (-5.1%)**
- Most trades (812) — highest frequency
- Profit factor 1.42 — solid but not spectacular
- **Best asset for risk-averse capital preservation**

### NAS100: The "Growth" Asset  
- Strong Sharpe (1.334) with high return (+27.4%)
- Moderate DD (-17.8%)
- Diversifies away from gold exposure
- **Best complement to XAUUSD in a portfolio**

### XAUEUR: The "Currency Hedge"
- Same gold exposure as XAUUSD but in EUR terms
- Sharpe 1.202 — comparable to XAUUSD
- Useful for EUR-denominated accounts
- **Limited data — needs more validation**

### XAGUSD: The "Volatility Play"
- Highest return (+43.4%) but also highest DD (-38.1%)
- Win rate only 37.1% — many small wins, few big losses
- **Not suitable for $300 accounts**

---

## Portfolio Construction Hypothesis

A 3-asset portfolio of XAUUSD + NAS100 + EURUSD could:
- Reduce correlation risk (gold + tech + FX)
- Smooth equity curve through diversification
- Maintain Sharpe > 1.2 while reducing max DD

**Suggested weights (inverse-volatility):**
| Asset | Ann Vol | Weight |
|-------|---------|--------|
| EURUSD | ~7% | 45% |
| XAUUSD | ~16% | 20% |
| NAS100 | ~21% | 35% |

---

## Recommendation

1. **Immediate:** Add NAS100 and EURUSD to paper trading alongside XAUUSD
2. **Portfolio:** Test 3-asset inverse-vol weighting in backtest
3. **XAGUSD/XAUEUR:** Wait for 12+ months of data before considering
4. **GER40/US30:** Abandon — momentum doesn't work on these indices

---

*Next: Phase 2.2 — Cross-Asset Lead-Lag, or Phase 3 — Scalping Feasibility*
