"""
Vectorized backtesting engine.
Fast simulation for research and strategy development.
"""
from typing import Dict, Optional

import numpy as np
import pandas as pd

from .execution import ExecutionSimulator, ExecutionConfig
from .metrics import calculate_metrics


class VectorizedBacktester:
    """
    Fast vectorized backtester for OHLCV data.
    
    Execution model:
    - Strategy generates signals at bar close (time T)
    - Position is entered at next bar's close (time T+1)
    - This prevents lookahead bias
    - Costs (spread, commission, slippage) are applied on entry/exit
    """
    
    def __init__(
        self,
        data: pd.DataFrame,
        strategy,
        initial_capital: float = 100_000.0,
        position_size: str = "fixed",  # "fixed", "percent", "volatility"
        position_pct: float = 1.0,     # For "fixed": fraction of capital per trade
        volatility_lookback: int = 20,
        target_volatility: float = 0.10,  # Annual target vol for vol targeting
        execution_config: Optional[ExecutionConfig] = None,
        periods_per_year: int = 252 * 24  # Hourly default
    ):
        """
        Args:
            data: DataFrame with columns [open, high, low, close, ...] indexed by time
            strategy: Strategy instance with generate_signals(data) method
            initial_capital: Starting portfolio value
            position_size: Position sizing method
            position_pct: Fraction of equity to deploy (for fixed sizing)
            volatility_lookback: Lookback for vol targeting
            target_volatility: Annualized target volatility
            execution_config: Execution cost parameters
            periods_per_year: For annualization
        """
        self.data = data.copy()
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.position_size = position_size
        self.position_pct = position_pct
        self.volatility_lookback = volatility_lookback
        self.target_volatility = target_volatility
        self.execution = ExecutionSimulator(execution_config or ExecutionConfig())
        self.periods_per_year = periods_per_year
        
        self.signals: Optional[pd.Series] = None
        self.positions: Optional[pd.Series] = None
        self.returns: Optional[pd.Series] = None
        self.equity_curve: Optional[pd.Series] = None
        self.trades: Optional[pd.DataFrame] = None
        self.metrics: Optional[Dict] = None
    
    def run(self) -> Dict:
        """
        Execute the full backtest.
        Returns metrics dict.
        """
        # Generate signals
        self.signals = self.strategy.generate_signals(self.data)
        self.signals = self.signals.reindex(self.data.index).fillna(0)
        
        # Shift signals by 1 bar to avoid lookahead bias
        # Signal at T, execute at T+1
        self.positions = self.signals.shift(1).fillna(0)
        
        # Calculate raw returns from close-to-close
        price_returns = self.data["close"].pct_change().fillna(0)
        
        # Position sizing
        position_multiplier = self._calculate_position_sizes()
        self.positions = self.positions * position_multiplier
        
        # Strategy returns = position * price return
        self.returns = self.positions * price_returns
        
        # Apply execution costs
        self.returns = self.execution.apply_costs_to_returns(
            self.data, self.returns, self.positions
        )
        
        # Build equity curve
        self.equity_curve = self.initial_capital * (1 + self.returns).cumprod()
        
        # Extract trade log
        self.trades = self._extract_trades()
        
        # Calculate metrics
        self.metrics = calculate_metrics(
            self.equity_curve,
            trades=self.trades,
            periods_per_year=self.periods_per_year
        )
        
        return self.metrics
    
    def _calculate_position_sizes(self) -> pd.Series:
        """Calculate position size multiplier based on sizing method."""
        if self.position_size == "fixed":
            return pd.Series(self.position_pct, index=self.data.index)
        
        elif self.position_size == "percent":
            # Risk X% per trade - simplified to fixed fraction
            return pd.Series(self.position_pct, index=self.data.index)
        
        elif self.position_size == "volatility":
            # Target annual volatility
            # Position = target_vol / realized_vol
            log_returns = np.log(self.data["close"] / self.data["close"].shift(1))
            realized_vol = log_returns.rolling(self.volatility_lookback).std() * np.sqrt(self.periods_per_year)
            size = self.target_volatility / realized_vol
            return size.fillna(0).clip(0, 2.0)  # Cap at 2x leverage
        
        else:
            return pd.Series(1.0, index=self.data.index)
    
    def _extract_trades(self) -> pd.DataFrame:
        """
        Extract individual trades from position series.
        A trade is a contiguous period with non-zero position.
        """
        pos = self.positions.copy()
        
        # Detect trade boundaries: position changes or goes to/from zero
        trades = []
        entry_time = None
        entry_price = None
        current_direction = 0
        
        for time, direction in pos.items():
            if direction == 0 and current_direction != 0:
                # Exit trade
                exit_price = self.data.loc[time, "close"]
                trade_return = (exit_price / entry_price - 1) * current_direction
                
                trades.append({
                    "entry_time": entry_time,
                    "exit_time": time,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "direction": current_direction,
                    "return": trade_return,
                    "bars_held": len(pos.loc[entry_time:time]) - 1,
                })
                
                current_direction = 0
                entry_time = None
                entry_price = None
            
            elif direction != 0 and current_direction == 0:
                # Enter trade
                entry_time = time
                entry_price = self.data.loc[time, "close"]
                current_direction = direction
            
            elif direction != current_direction and current_direction != 0:
                # Reverse position (exit and re-enter)
                exit_price = self.data.loc[time, "close"]
                trade_return = (exit_price / entry_price - 1) * current_direction
                
                trades.append({
                    "entry_time": entry_time,
                    "exit_time": time,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "direction": current_direction,
                    "return": trade_return,
                    "bars_held": len(pos.loc[entry_time:time]) - 1,
                })
                
                # Re-enter in new direction
                entry_time = time
                entry_price = self.data.loc[time, "close"]
                current_direction = direction
        
        if not trades:
            return pd.DataFrame()
        
        return pd.DataFrame(trades)
    
    def get_results(self) -> Dict:
        """Return full backtest results."""
        return {
            "metrics": self.metrics,
            "equity_curve": self.equity_curve,
            "returns": self.returns,
            "positions": self.positions,
            "signals": self.signals,
            "trades": self.trades,
        }
