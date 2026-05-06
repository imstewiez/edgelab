"""Statistical Arbitrage (Pairs Trading) Engine.

Implements cointegration-based pairs trading on FX pairs.
Research-backed edge: academic studies show 5-15% annual returns,
Sharpe 1.0-2.0, win rate 55-65% on cointegrated pairs.

Pairs traded:
- EURUSD / GBPUSD   (correlation ~0.85, cointegrated through USD)
- AUDUSD / NZDUSD   (correlation ~0.90, both commodity currencies)
- EURUSD / USDCHF   (natural hedge, EUR/CHF stability)

Logic:
1. Rolling OLS regression to estimate hedge ratio
2. Spread = Leg1 - hedge_ratio * Leg2
3. Z-score = (spread - rolling_mean) / rolling_std
4. Entry: |Z| > entry_threshold (default 2.0)
5. Exit: |Z| < exit_threshold (default 0.5)
6. Position: Z > threshold → Short spread (short leg1, long leg2)
            Z < -threshold → Long spread (long leg1, short leg2)

Market neutral — profit comes from mean reversion of the spread,
not directional market movement.
"""
from dataclasses import dataclass
from typing import Optional, Dict, Tuple
from enum import Enum
import pandas as pd
import numpy as np


class PairStatus(Enum):
    FLAT = 0
    LONG_SPREAD = 1   # Long leg1, Short leg2
    SHORT_SPREAD = -1 # Short leg1, Long leg2


@dataclass(frozen=True)
class StatArbSignal:
    """Signal output from StatArb engine."""
    pair_name: str
    leg1: str
    leg2: str
    status: PairStatus
    z_score: float
    hedge_ratio: float
    spread: float
    timestamp: pd.Timestamp
    leg1_direction: int  # 1=LONG, -1=SHORT, 0=FLAT
    leg2_direction: int
    leg1_size: float     # lot size for leg1
    leg2_size: float     # lot size for leg2
    warmup_complete: bool
    blocked_reason: Optional[str] = None
    
    @property
    def is_active(self) -> bool:
        return self.status != PairStatus.FLAT and self.warmup_complete


class StatArbEngine:
    """Cointegration-based pairs trading engine.
    
    Args:
        pair: Tuple of (leg1, leg2) symbol names
        lookback: Rolling window for hedge ratio / Z-score (default 100 bars)
        entry_z: Z-score threshold for entry (default 2.0)
        exit_z: Z-score threshold for exit (default 0.5)
    """
    
    VERSION = "1.0.0"
    
    def __init__(
        self,
        pair: Tuple[str, str],
        lookback: int = 100,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
        min_lookback: int = 50,
    ):
        self.leg1, self.leg2 = pair
        self.pair_name = f"{self.leg1}_{self.leg2}"
        self.lookback = lookback
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.min_lookback = min_lookback
        
        # State tracking
        self.current_status = PairStatus.FLAT
        self.entry_z_score = 0.0
    
    def generate_signal(
        self,
        leg1_bars: pd.DataFrame,
        leg2_bars: pd.DataFrame,
        equity: float = 300.0,
        now_utc: Optional[pd.Timestamp] = None,
    ) -> StatArbSignal:
        """Generate pairs trading signal from H1 bar data for both legs.
        
        Args:
            leg1_bars: DataFrame [open, high, low, close] for leg1
            leg2_bars: DataFrame [open, high, low, close] for leg2
            equity: Current account equity for lot sizing
            now_utc: Current timestamp
            
        Returns:
            StatArbSignal with directions and sizes for both legs
        """
        if now_utc is None:
            now_utc = leg1_bars.index[-1]
        
        # Validate data
        if len(leg1_bars) < self.min_lookback or len(leg2_bars) < self.min_lookback:
            return self._make_signal(
                PairStatus.FLAT, 0.0, 1.0, 0.0, now_utc, 0, 0, 0.0, 0.0,
                blocked_reason=f"Insufficient bars: {len(leg1_bars)}/{len(leg2_bars)} < {self.min_lookback}"
            )
        
        # Align data to common index
        combined = pd.DataFrame({
            "leg1": leg1_bars["close"],
            "leg2": leg2_bars["close"],
        }).dropna()
        
        if len(combined) < self.min_lookback:
            return self._make_signal(
                PairStatus.FLAT, 0.0, 1.0, 0.0, now_utc, 0, 0, 0.0, 0.0,
                blocked_reason="Insufficient aligned bars"
            )
        
        # Use last `lookback` bars for calculation
        window = combined.tail(self.lookback)
        
        # Calculate hedge ratio via OLS: leg1 = alpha + beta * leg2
        # beta = Cov(leg1, leg2) / Var(leg2)
        beta = window["leg1"].cov(window["leg2"]) / window["leg2"].var()
        if np.isnan(beta) or beta == 0:
            beta = 1.0
        
        # Calculate spread
        spread = window["leg1"] - beta * window["leg2"]
        spread_mean = spread.mean()
        spread_std = spread.std()
        
        if spread_std == 0 or np.isnan(spread_std):
            return self._make_signal(
                PairStatus.FLAT, 0.0, beta, 0.0, now_utc, 0, 0, 0.0, 0.0,
                blocked_reason="Zero spread std"
            )
        
        # Current Z-score
        current_spread = combined["leg1"].iloc[-1] - beta * combined["leg2"].iloc[-1]
        z_score = (current_spread - spread_mean) / spread_std
        
        # Half-life of mean reversion (Ornstein-Uhlenbeck)
        spread_lag = spread.shift(1)
        spread_diff = spread.diff()
        spread_lag = spread_lag.dropna()
        spread_diff = spread_diff.dropna()
        aligned = pd.DataFrame({"lag": spread_lag, "diff": spread_diff}).dropna()
        if len(aligned) > 10:
            theta = np.polyfit(aligned["lag"], aligned["diff"], 1)[0]
            half_life = -np.log(2) / theta if theta < 0 else np.inf
        else:
            half_life = np.inf
        
        # Block if half-life is too long (>100 bars = slow mean reversion)
        if half_life > 100:
            return self._make_signal(
                PairStatus.FLAT, z_score, beta, current_spread, now_utc, 0, 0, 0.0, 0.0,
                blocked_reason=f"Half-life too long: {half_life:.1f} bars"
            )
        
        # Determine target status
        target_status = self.current_status
        
        if self.current_status == PairStatus.FLAT:
            # No position — check for entry
            if z_score > self.entry_z:
                target_status = PairStatus.SHORT_SPREAD  # Spread too high → short it
            elif z_score < -self.entry_z:
                target_status = PairStatus.LONG_SPREAD   # Spread too low → long it
        else:
            # Have position — check for exit
            if abs(z_score) < self.exit_z:
                target_status = PairStatus.FLAT
            # Also check if Z-score moved against us beyond 3.5 (cointegration break)
            elif abs(z_score) > 3.5:
                target_status = PairStatus.FLAT  # Stop loss: cointegration likely broken
        
        # Calculate lot sizes
        leg1_dir, leg2_dir, leg1_size, leg2_size = self._calculate_sizes(
            target_status, equity, beta
        )
        
        # Update internal state
        if target_status != self.current_status:
            self.current_status = target_status
            self.entry_z_score = z_score if target_status != PairStatus.FLAT else 0.0
        
        return self._make_signal(
            target_status, z_score, beta, current_spread, now_utc,
            leg1_dir, leg2_dir, leg1_size, leg2_size
        )
    
    def _calculate_sizes(
        self, status: PairStatus, equity: float, hedge_ratio: float
    ) -> Tuple[int, int, float, float]:
        """Calculate direction and lot size for each leg.
        
        For $300 equity:
        - Base size: 0.01 lots per leg
        - Adjust leg2 by inverse hedge ratio for dollar neutrality
        """
        if status == PairStatus.FLAT:
            return 0, 0, 0.0, 0.0
        
        # Base lot size for $300 account: minimum 0.01
        base_size = 0.01
        
        if status == PairStatus.LONG_SPREAD:
            # Long leg1, Short leg2
            leg1_dir = 1
            leg2_dir = -1
            leg1_size = base_size
            # Adjust leg2 size by hedge ratio for dollar-neutral exposure
            leg2_size = max(0.01, round(base_size * abs(hedge_ratio), 2))
        else:  # SHORT_SPREAD
            # Short leg1, Long leg2
            leg1_dir = -1
            leg2_dir = 1
            leg1_size = base_size
            leg2_size = max(0.01, round(base_size * abs(hedge_ratio), 2))
        
        return leg1_dir, leg2_dir, leg1_size, leg2_size
    
    def _make_signal(
        self, status, z_score, hedge_ratio, spread, timestamp,
        leg1_dir, leg2_dir, leg1_size, leg2_size,
        blocked_reason=None, warmup_complete=True
    ) -> StatArbSignal:
        return StatArbSignal(
            pair_name=self.pair_name,
            leg1=self.leg1,
            leg2=self.leg2,
            status=status,
            z_score=round(z_score, 4),
            hedge_ratio=round(hedge_ratio, 4),
            spread=round(spread, 6),
            timestamp=timestamp,
            leg1_direction=leg1_dir,
            leg2_direction=leg2_dir,
            leg1_size=leg1_size,
            leg2_size=leg2_size,
            warmup_complete=warmup_complete,
            blocked_reason=blocked_reason,
        )
    
    def reset(self):
        """Reset internal state (for backtesting)."""
        self.current_status = PairStatus.FLAT
        self.entry_z_score = 0.0


# Predefined pair configurations
PAIRS_CONFIG = [
    # (leg1, leg2, lookback, entry_z, exit_z)
    ("EURUSD", "GBPUSD", 100, 2.0, 0.5),
    ("AUDUSD", "NZDUSD", 100, 2.0, 0.5),
    ("EURUSD", "USDCHF", 100, 2.0, 0.5),
]


def create_all_engines() -> Dict[str, StatArbEngine]:
    """Create engines for all predefined pairs."""
    engines = {}
    for leg1, leg2, lb, ez, xz in PAIRS_CONFIG:
        engine = StatArbEngine((leg1, leg2), lookback=lb, entry_z=ez, exit_z=xz)
        engines[engine.pair_name] = engine
    return engines
