"""Phase 1.3: Weekend Gap Analysis on XAUUSD

Tests whether Friday close -> Sunday open gaps are predictive,
fill quickly, or should be avoided.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from collections import defaultdict
from scipy import stats


def load_data(symbol="XAUUSD"):
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    h1 = pd.read_parquet(base / f"{symbol}_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    return h1


def find_weekend_gaps(h1):
    """Find all Friday close -> Sunday/Monday open gaps.
    
    Returns list of dicts with gap info.
    """
    gaps = []
    
    # Group by date
    h1["date"] = h1.index.date
    daily = h1.groupby("date").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    })
    daily.index = pd.to_datetime(daily.index)
    
    for i in range(1, len(daily)):
        prev_date = daily.index[i - 1]
        curr_date = daily.index[i]
        
        # Check if weekend gap (Friday -> Monday)
        if prev_date.weekday() == 4 and curr_date.weekday() == 0:
            fri_close = daily.iloc[i - 1]["close"]
            mon_open = daily.iloc[i]["open"]
            gap = mon_open - fri_close
            gap_pct = gap / fri_close * 100
            
            # Find how long until gap fills (if at all)
            mon_bars = h1[h1.index.date == curr_date.date()]
            fills_in_4h = False
            fills_in_24h = False
            never_fills = True
            
            if len(mon_bars) > 0:
                for j, (ts, bar) in enumerate(mon_bars.iterrows()):
                    # Gap fill = price returns to Friday close
                    if gap > 0 and bar["low"] <= fri_close:
                        fills_in_4h = j < 4
                        fills_in_24h = True
                        never_fills = False
                        break
                    elif gap < 0 and bar["high"] >= fri_close:
                        fills_in_4h = j < 4
                        fills_in_24h = True
                        never_fills = False
                        break
            
            # Monday direction persistence (close vs open)
            if len(mon_bars) > 0:
                mon_close = mon_bars.iloc[-1]["close"]
                mon_persistence = mon_close - mon_open
                mon_persistence_pct = mon_persistence / mon_open * 100
                # Direction: did Monday continue the gap direction?
                continued = (gap > 0 and mon_persistence > 0) or (gap < 0 and mon_persistence < 0)
            else:
                mon_persistence_pct = 0
                continued = False
            
            # H1 momentum on Monday (first 4 bars)
            if len(mon_bars) >= 4:
                h1_mom = (mon_bars.iloc[3]["close"] / mon_bars.iloc[0]["open"] - 1) * 100
            else:
                h1_mom = 0
            
            gaps.append({
                "friday": prev_date,
                "monday": curr_date,
                "fri_close": fri_close,
                "mon_open": mon_open,
                "gap": gap,
                "gap_pct": gap_pct,
                "gap_direction": "up" if gap > 0 else "down",
                "fills_in_4h": fills_in_4h,
                "fills_in_24h": fills_in_24h,
                "never_fills": never_fills,
                "mon_persistence_pct": mon_persistence_pct,
                "continued": continued,
                "h1_mom_4bar_pct": h1_mom,
            })
    
    return pd.DataFrame(gaps)


def analyze_gaps(gap_df):
    """Compute gap statistics."""
    print(f"\nTotal weekend gaps analyzed: {len(gap_df)}")
    print(f"Date range: {gap_df['friday'].min()} to {gap_df['friday'].max()}")
    
    # Basic stats
    print(f"\n--- GAP SIZE DISTRIBUTION ---")
    print(f"  Mean gap:     {gap_df['gap_pct'].mean():+.3f}%")
    print(f"  Median gap:   {gap_df['gap_pct'].median():+.3f}%")
    print(f"  Std gap:      {gap_df['gap_pct'].std():.3f}%")
    print(f"  Min gap:      {gap_df['gap_pct'].min():+.3f}%")
    print(f"  Max gap:      {gap_df['gap_pct'].max():+.3f}%")
    print(f"  |Gap| > 1%:   {(gap_df['gap_pct'].abs() > 1).sum()} / {len(gap_df)} ({(gap_df['gap_pct'].abs() > 1).mean()*100:.1f}%)")
    print(f"  |Gap| > 5%:   {(gap_df['gap_pct'].abs() > 5).sum()} / {len(gap_df)} ({(gap_df['gap_pct'].abs() > 5).mean()*100:.1f}%)")
    
    # Direction
    up = gap_df[gap_df["gap_direction"] == "up"]
    down = gap_df[gap_df["gap_direction"] == "down"]
    print(f"\n--- GAP DIRECTION ---")
    print(f"  Up gaps:   {len(up)} ({len(up)/len(gap_df)*100:.1f}%) | Avg: {up['gap_pct'].mean():+.3f}%")
    print(f"  Down gaps: {len(down)} ({len(down)/len(gap_df)*100:.1f}%) | Avg: {down['gap_pct'].mean():+.3f}%")
    
    # Fill rates
    print(f"\n--- GAP FILL RATES ---")
    print(f"  Fills within 4 hours:  {gap_df['fills_in_4h'].sum()} / {len(gap_df)} ({gap_df['fills_in_4h'].mean()*100:.1f}%)")
    print(f"  Fills within 24 hours: {gap_df['fills_in_24h'].sum()} / {len(gap_df)} ({gap_df['fills_in_24h'].mean()*100:.1f}%)")
    print(f"  Never fills:           {gap_df['never_fills'].sum()} / {len(gap_df)} ({gap_df['never_fills'].mean()*100:.1f}%)")
    
    # Monday persistence
    print(f"\n--- MONDAY DIRECTION PERSISTENCE ---")
    print(f"  Gap continues on Monday: {gap_df['continued'].sum()} / {len(gap_df)} ({gap_df['continued'].mean()*100:.1f}%)")
    print(f"  Avg Monday persistence: {gap_df['mon_persistence_pct'].mean():+.3f}%")
    
    # Predictive power: does gap direction predict Monday H1 momentum?
    gap_df["h1_mom_sign"] = np.sign(gap_df["h1_mom_4bar_pct"])
    gap_df["gap_sign"] = np.sign(gap_df["gap_pct"])
    matches = (gap_df["h1_mom_sign"] == gap_df["gap_sign"]).sum()
    print(f"\n--- PREDICTIVE POWER ---")
    print(f"  Gap direction matches Monday H1 momentum: {matches} / {len(gap_df)} ({matches/len(gap_df)*100:.1f}%)")
    
    # T-test: is Monday persistence different from zero?
    t_stat, p_val = stats.ttest_1samp(gap_df["mon_persistence_pct"], 0)
    print(f"  Monday persistence t-test: t={t_stat:.3f}, p={p_val:.4f}")
    
    # Gap size vs fill rate
    big_gaps = gap_df[gap_df["gap_pct"].abs() > gap_df["gap_pct"].abs().median()]
    small_gaps = gap_df[gap_df["gap_pct"].abs() <= gap_df["gap_pct"].abs().median()]
    print(f"\n--- GAP SIZE vs FILL RATE ---")
    print(f"  Small gaps (<= median) fill in 24h: {small_gaps['fills_in_24h'].mean()*100:.1f}%")
    print(f"  Big gaps (> median) fill in 24h:    {big_gaps['fills_in_24h'].mean()*100:.1f}%")
    
    # Correlation: gap size vs Monday persistence
    corr = gap_df["gap_pct"].corr(gap_df["mon_persistence_pct"])
    print(f"\n  Correlation (gap size vs Monday persistence): {corr:.3f}")
    
    return gap_df


def main():
    print("=" * 70)
    print("Phase 1.3: Weekend Gap Analysis -- XAUUSD")
    print("=" * 70)
    
    h1 = load_data("XAUUSD")
    print(f"Loaded {len(h1)} H1 bars")
    
    gap_df = find_weekend_gaps(h1)
    gap_df = analyze_gaps(gap_df)
    
    out_dir = Path(__file__).parent.parent.parent.parent / "results" / "time_patterns"
    out_dir.mkdir(parents=True, exist_ok=True)
    gap_df.to_csv(out_dir / "weekend_gaps.csv", index=False)
    print(f"\nSaved: {out_dir / 'weekend_gaps.csv'}")


if __name__ == "__main__":
    main()
