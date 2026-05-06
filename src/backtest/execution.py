"""
Execution simulator with realistic trading costs.
Models ECN/raw-spread + commission accounts like DPrime.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class ExecutionConfig:
    """Configuration for trade execution simulation."""
    spread_pips: Optional[float] = None  # Fixed spread in pips; if None, uses data['avg_spread']
    commission_per_lot: float = 7.0      # Round-turn commission per standard lot (e.g., $7)
    lot_size: float = 100_000.0          # Standard FX lot in units
    trade_lots: float = 1.0              # Number of lots per trade
    slippage_pips: float = 0.0           # Additional slippage in pips
    pip_value: float = 10.0              # Value of 1 pip per lot in account currency


class ExecutionSimulator:
    """
    Simulates trade execution costs on OHLCV data.
    
    For each bar where a position is entered/exited/held:
    - Spread cost is applied on entry (and optionally on exit)
    - Commission is charged per round-turn lot
    - Slippage can be modeled as additional spread
    """
    
    def __init__(self, config: ExecutionConfig = None):
        self.cfg = config or ExecutionConfig()
    
    def get_spread(self, data: pd.DataFrame) -> pd.Series:
        """Return spread series in price terms (not pips)."""
        if self.cfg.spread_pips is not None:
            # Convert pips to price: for 5-digit pairs, 1 pip = 0.0001
            # We'll auto-detect based on typical price magnitude
            typical_price = data["close"].mean()
            if typical_price < 10:  # FX pair like EURUSD
                pip_size = 0.0001
            elif typical_price < 1000:  # JPY pairs or indices
                pip_size = 0.01
            else:  # Gold, etc.
                pip_size = 0.01 if typical_price > 2000 else 0.1
            return pd.Series(self.cfg.spread_pips * pip_size, index=data.index)
        
        if "avg_spread" in data.columns:
            return data["avg_spread"]
        
        # MT5 data has 'spread' in points; convert to price
        if "spread" in data.columns:
            typical_price = data["close"].mean()
            if typical_price > 1000:
                # XAUUSD, XAGUSD: 1 point = 0.01
                point_value = 0.01
            elif typical_price < 10:
                # FX: 1 point = 0.00001 (5-digit broker)
                point_value = 0.00001
            else:
                point_value = 0.01
            return data["spread"] * point_value
        
        # Fallback: estimate spread from high-low ratio
        return (data["high"] - data["low"]) * 0.05
    
    def calculate_costs(
        self,
        data: pd.DataFrame,
        trades: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate transaction costs for a trade log.
        
        trades DataFrame expected columns:
            entry_time, exit_time, entry_price, exit_price, direction (1 or -1), lots
        Returns trades with added cost columns.
        """
        trades = trades.copy()
        spread = self.get_spread(data)
        
        # Map spread by time index
        spread_map = spread.to_dict()
        
        trades["entry_spread"] = trades["entry_time"].map(spread_map).fillna(spread.mean())
        trades["exit_spread"] = trades["exit_time"].map(spread_map).fillna(spread.mean())
        
        # Entry cost: half spread + slippage
        trades["entry_cost_price"] = (trades["entry_spread"] / 2) + self._slippage_price(data)
        # Exit cost: half spread + slippage
        trades["exit_cost_price"] = (trades["exit_spread"] / 2) + self._slippage_price(data)
        
        # Total spread+slippage cost in price terms
        trades["total_cost_price"] = trades["entry_cost_price"] + trades["exit_cost_price"]
        
        # Commission: per lot round-turn
        trades["commission"] = trades["lots"] * self.cfg.commission_per_lot
        
        # Convert price costs to monetary value
        # For FX: cost in pips * pip_value * lots
        typical_price = data["close"].mean()
        pip_size = self._detect_pip_size(typical_price)
        
        trades["spread_cost_usd"] = (trades["total_cost_price"] / pip_size) * self.cfg.pip_value * trades["lots"]
        trades["total_cost_usd"] = trades["spread_cost_usd"] + trades["commission"]
        
        return trades
    
    def _slippage_price(self, data: pd.DataFrame) -> float:
        typical_price = data["close"].mean()
        pip_size = self._detect_pip_size(typical_price)
        return self.cfg.slippage_pips * pip_size
    
    @staticmethod
    def _detect_pip_size(typical_price: float) -> float:
        if typical_price < 10:
            return 0.0001
        elif typical_price < 1000:
            return 0.01
        else:
            return 0.01
    
    def apply_costs_to_returns(
        self,
        data: pd.DataFrame,
        returns: pd.Series,
        positions: pd.Series
    ) -> pd.Series:
        """
        Apply realistic transaction costs to returns.
        Costs are applied when position changes (entry/exit events).
        
        Returns adjusted return series.
        """
        adj_returns = returns.astype(float).copy()
        spread = self.get_spread(data)
        
        # Detect position changes (entry, exit, flip)
        position_changes = positions.diff().fillna(0) != 0
        
        # Notional value per trade (auto-detect lot size for metals)
        typical_price = data["close"].mean()
        if typical_price > 1000:
            # XAUUSD: 1 lot = 100 oz
            lot_size = 100.0
        else:
            lot_size = self.cfg.lot_size
        notional = self.cfg.trade_lots * lot_size * data["close"]
        
        # Spread cost in return terms: half-spread per side
        # Full spread applied across entry + exit
        spread_cost_return = (spread / 2) / data["close"]
        
        # Commission cost in return terms: half commission per side
        # Round-turn commission split across entry + exit
        commission_per_trade = self.cfg.commission_per_lot * self.cfg.trade_lots
        commission_return = (commission_per_trade / 2) / notional
        
        # Total cost per side = half-spread + half-commission
        total_cost = spread_cost_return + commission_return
        adj_returns[position_changes] -= total_cost[position_changes]
        
        return adj_returns
