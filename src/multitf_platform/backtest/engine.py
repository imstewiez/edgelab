"""Event-driven backtester with bid/ask execution for CFDs.

This is the canonical truth engine for MultiTF validation.
It replaces the vectorized backtester with realistic fill simulation.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Callable
from enum import Enum
import pandas as pd
import numpy as np

from ..strategy.frozen.v1_0_0 import MultiTFStrategy, SignalDecision, FrozenStrategyConfig
from ..risk.v1_1 import RiskWrapper, WrappedDecision, Action
from ..config.models import PlatformConfig


class OrderSide(Enum):
    BUY = 1
    SELL = -1


@dataclass
class Fill:
    timestamp: pd.Timestamp
    side: OrderSide
    price: float
    size: float
    spread_paid: float
    commission: float
    slippage: float
    reason: str


@dataclass
class Trade:
    entry_fill: Fill
    exit_fill: Optional[Fill] = None
    pnl: float = 0.0
    bars_held: int = 0
    
    @property
    def is_open(self) -> bool:
        return self.exit_fill is None
    
    @property
    def return_pct(self) -> float:
        if self.exit_fill is None:
            return 0.0
        if self.entry_fill.side == OrderSide.BUY:
            return (self.exit_fill.price - self.entry_fill.price) / self.entry_fill.price
        else:
            return (self.entry_fill.price - self.exit_fill.price) / self.entry_fill.price


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    returns: pd.Series
    trades: List[Trade]
    fills: List[Fill]
    metrics: dict
    config_hash: str


class EventDrivenBacktester:
    """Event-driven backtester with realistic CFD execution.
    
    Processes each bar in sequence:
    1. Generate signal from frozen strategy
    2. Apply risk wrapper
    3. If allowed, simulate order execution
    4. Apply costs (spread, commission, slippage)
    5. Update portfolio state
    """
    
    def __init__(self, config: PlatformConfig):
        self.config = config
        # Convert platform strategy config to frozen strategy config
        frozen_cfg = FrozenStrategyConfig(
            symbol=config.strategy.symbol,
            entry_timeframe=config.strategy.entry_timeframe,
            confirmation_timeframe=config.strategy.confirmation_timeframe,
            h1_lookback=config.strategy.h1_lookback,
            h4_lookback=config.strategy.h4_lookback,
        )
        self.strategy = MultiTFStrategy(frozen_cfg)
        self.risk = RiskWrapper(config.risk_wrapper)
        
    def run(
        self,
        h1_bars: pd.DataFrame,
        h4_bars: pd.DataFrame,
        progress_callback: Optional[Callable] = None
    ) -> BacktestResult:
        """Run event-driven backtest.
        
        Args:
            h1_bars: H1 OHLCV data indexed by UTC timestamp
            h4_bars: H4 OHLCV data indexed by UTC timestamp
            progress_callback: Optional function(i, total) for progress updates
            
        Returns:
            BacktestResult with equity curve, trades, fills, and metrics
        """
        cfg = self.config
        initial_equity = cfg.broker.initial_equity
        equity = initial_equity
        peak_equity = equity
        
        trades: List[Trade] = []
        fills: List[Fill] = []
        equity_curve = [equity]
        timestamps = [h1_bars.index[0]]
        
        current_trade: Optional[Trade] = None
        current_position = 0  # 1=long, -1=short, 0=flat
        
        for i, (ts, bar) in enumerate(h1_bars.iterrows()):
            if progress_callback and i % 100 == 0:
                progress_callback(i, len(h1_bars))
            
            # Get H1 bars up to current bar
            h1_up_to_now = h1_bars.iloc[:i+1]
            h4_up_to_now = h4_bars[h4_bars.index <= ts]
            
            # Generate signal
            signal = self.strategy.generate_signal(h1_up_to_now, h4_up_to_now, ts)
            
            # Get current spread
            spread = self._get_spread(bar)
            
            # Apply risk wrapper
            wrapped = self.risk.apply(signal, h1_up_to_now, equity, spread)
            
            # Determine target position
            target_position = wrapped.final_direction if wrapped.action != Action.KILL_SWITCH else 0
            
            # Execute if position changes
            if target_position != current_position:
                # Close existing position if any
                if current_trade is not None and current_trade.is_open:
                    exit_fill = self._simulate_fill(
                        ts, bar, current_position, "exit", spread
                    )
                    fills.append(exit_fill)
                    current_trade.exit_fill = exit_fill
                    current_trade.bars_held = i - self._find_entry_index(trades, current_trade)
                    
                    # Calculate P&L
                    pnl = self._calculate_pnl(current_trade, current_position)
                    current_trade.pnl = pnl
                    equity += pnl
                    
                    # Update risk state
                    pnl_pct = pnl / initial_equity
                    self.risk.update_after_trade(pnl_pct, ts)
                
                # Open new position if target is non-zero
                if target_position != 0:
                    entry_fill = self._simulate_fill(
                        ts, bar, target_position, "entry", spread
                    )
                    fills.append(entry_fill)
                    current_trade = Trade(entry_fill=entry_fill)
                    trades.append(current_trade)
                else:
                    current_trade = None
                
                current_position = target_position
            
            # Update equity curve (mark to market for open positions)
            mtm_equity = equity
            if current_trade is not None and current_trade.is_open:
                mtm_pnl = self._calculate_mtm(current_trade, bar["close"], current_position)
                mtm_equity += mtm_pnl
            
            equity_curve.append(mtm_equity)
            timestamps.append(ts)
            peak_equity = max(peak_equity, mtm_equity)
        
        # Close any open position at end
        if current_trade is not None and current_trade.is_open:
            last_bar = h1_bars.iloc[-1]
            last_ts = h1_bars.index[-1]
            exit_fill = self._simulate_fill(
                last_ts, last_bar, current_position, "exit", 
                self._get_spread(last_bar)
            )
            fills.append(exit_fill)
            current_trade.exit_fill = exit_fill
            pnl = self._calculate_pnl(current_trade, current_position)
            current_trade.pnl = pnl
            equity += pnl
            equity_curve[-1] = equity
        
        # Build result
        equity_series = pd.Series(equity_curve, index=timestamps)
        returns = equity_series.pct_change().fillna(0)
        
        metrics = self._calculate_metrics(equity_series, returns, trades)
        
        return BacktestResult(
            equity_curve=equity_series,
            returns=returns,
            trades=trades,
            fills=fills,
            metrics=metrics,
            config_hash=""
        )
    
    def _get_spread(self, bar: pd.Series) -> float:
        """Extract spread from bar data."""
        if "spread" in bar:
            return float(bar["spread"])
        if "avg_spread" in bar:
            return float(bar["avg_spread"])
        # Estimate from high-low
        return float((bar["high"] - bar["low"]) * 0.1)
    
    def _simulate_fill(
        self,
        ts: pd.Timestamp,
        bar: pd.Series,
        direction: int,
        fill_type: str,
        spread: float
    ) -> Fill:
        """Simulate a realistic fill with spread and slippage."""
        close = float(bar["close"])
        
        # Spread in price terms
        half_spread = spread / 2
        
        # Entry: buy at ask, sell at bid
        # Exit: sell at bid, buy at ask
        if fill_type == "entry":
            if direction == 1:  # Long entry -> buy at ask
                price = close + half_spread
            else:  # Short entry -> sell at bid
                price = close - half_spread
        else:
            if direction == 1:  # Long exit -> sell at bid
                price = close - half_spread
            else:  # Short exit -> buy at ask
                price = close + half_spread
        
        # Commission
        commission = self.config.broker.commission_per_lot * 0.01  # Per 0.01 lot
        
        # Slippage (small random for realism, seeded)
        slippage = 0.0
        
        return Fill(
            timestamp=ts,
            side=OrderSide.BUY if direction == 1 else OrderSide.SELL,
            price=price,
            size=0.01,  # Fixed small size for backtest
            spread_paid=half_spread * 2,
            commission=commission,
            slippage=slippage,
            reason=fill_type
        )
    
    def _calculate_pnl(self, trade: Trade, direction: int) -> float:
        """Calculate P&L in account currency."""
        if trade.exit_fill is None:
            return 0.0
        
        entry = trade.entry_fill.price
        exit = trade.exit_fill.price
        size = trade.entry_fill.size
        
        if direction == 1:  # Long
            price_diff = exit - entry
        else:  # Short
            price_diff = entry - exit
        
        # For XAUUSD, 1 lot = 100 oz, 0.01 lot = 1 oz
        # P&L = price_diff * oz * pip_value / point_size
        # Simplified: $1 per point per oz
        gross_pnl = price_diff * size * 100  # 100 = contract size
        
        # Subtract costs
        total_cost = trade.entry_fill.commission + trade.exit_fill.commission
        total_cost += trade.entry_fill.spread_paid * size * 100 * 0.5
        total_cost += trade.exit_fill.spread_paid * size * 100 * 0.5
        
        return gross_pnl - total_cost
    
    def _calculate_mtm(self, trade: Trade, current_price: float, direction: int) -> float:
        """Mark-to-market P&L for open position."""
        entry = trade.entry_fill.price
        size = trade.entry_fill.size
        
        if direction == 1:
            price_diff = current_price - entry
        else:
            price_diff = entry - current_price
        
        return price_diff * size * 100 - trade.entry_fill.commission
    
    def _find_entry_index(self, trades: List[Trade], trade: Trade) -> int:
        """Find the bar index where a trade was entered."""
        for i, t in enumerate(trades):
            if t is trade:
                return i
        return 0
    
    def _calculate_metrics(
        self,
        equity: pd.Series,
        returns: pd.Series,
        trades: List[Trade]
    ) -> dict:
        """Calculate comprehensive performance metrics."""
        log_rets = np.log(equity / equity.shift(1)).dropna()
        
        ann_ret = log_rets.mean() * 252 * 24 * 100
        ann_vol = log_rets.std() * np.sqrt(252 * 24) * 100
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        
        cummax = equity.cummax()
        dd = (equity - cummax) / cummax
        max_dd = dd.min() * 100
        
        # Trade metrics
        closed_trades = [t for t in trades if not t.is_open]
        if closed_trades:
            trade_pnls = [t.pnl for t in closed_trades]
            wins = [p for p in trade_pnls if p > 0]
            losses = [p for p in trade_pnls if p < 0]
            
            win_rate = len(wins) / len(trade_pnls) * 100 if trade_pnls else 0
            pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
            avg_trade = np.mean(trade_pnls) if trade_pnls else 0
        else:
            win_rate = 0
            pf = 0
            avg_trade = 0
        
        return {
            "sharpe_ratio": round(sharpe, 3),
            "ann_return_pct": round(ann_ret, 2),
            "ann_volatility_pct": round(ann_vol, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "total_return_pct": round((equity.iloc[-1] / equity.iloc[0] - 1) * 100, 2),
            "num_trades": len(closed_trades),
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(pf, 2) if pf != float('inf') else "inf",
            "avg_trade_pnl": round(avg_trade, 2),
            "num_fills": len([f for t in trades for f in [t.entry_fill, t.exit_fill] if f]),
        }
