"""Paper broker simulating MT5-style execution for XAUUSD CFDs."""
import numpy as np
import pandas as pd
from typing import Optional, List
from dataclasses import dataclass, field

from ...config.models import BrokerConfig
from ...risk.v1_1.wrapper import Action, WrappedDecision
from .models import (
    Position, FillEvent, TradeRecord, BrokerState,
    TradeSide, TradeAction,
)


# XAUUSD contract constants
OZ_PER_LOT = 100.0          # 1 lot = 100 troy ounces
PIP_VALUE = 0.01            # 1 pip = $0.01 for XAUUSD


class PaperBroker:
    """Simulates paper trading with realistic execution costs.
    
    Uses bar close as execution price, applies spread for direction,
    adds random slippage, and tracks margin requirements.
    """
    
    def __init__(self, config: Optional[BrokerConfig] = None):
        self.cfg = config or BrokerConfig()
        self.rng = np.random.default_rng(seed=42)
        
        # Account state
        self.balance: float = self.cfg.initial_equity
        self.equity: float = self.cfg.initial_equity
        self.margin_used: float = 0.0
        
        # Position state
        self.position: Optional[Position] = None
        
        # History
        self.fills: List[FillEvent] = []
        self.trades: List[TradeRecord] = []
        self.states: List[BrokerState] = []
        
        # Tracking
        self._current_bar_idx: int = 0
        self._last_trade_day: Optional[pd.Timestamp] = None
        self._daily_pnl: float = 0.0
        self._weekly_pnl: float = 0.0
    
    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    
    def process_bar(self, decision: WrappedDecision, bar: pd.Series,
                    bar_idx: int) -> BrokerState:
        """Process one bar: apply decision, simulate fills, update state.
        
        Args:
            decision: Risk wrapper output with action and scale.
            bar: OHLC data for current bar (must have 'close', 'spread').
            bar_idx: Integer bar index for tracking.
        
        Returns:
            BrokerState snapshot after processing.
        """
        self._current_bar_idx = bar_idx
        ts = bar.name if isinstance(bar.name, pd.Timestamp) else pd.Timestamp(bar.name)
        
        # Update unrealized P&L on existing position
        if self.position is not None:
            mark = float(bar["close"])
            self.position.update_unrealized_pnl(mark)
            self.equity = self.balance + self.position.unrealized_pnl
        
        # Determine target direction from decision
        target_direction = self._target_direction_from_decision(decision)
        
        # Execute if position needs to change
        self._execute_if_needed(target_direction, decision, bar, ts)
        
        # Recalculate margin
        self._update_margin(bar)
        
        # Track daily/weekly P&L
        self._update_time_tracking(ts, bar)
        
        # Record state
        state = BrokerState(
            timestamp=ts,
            balance=self.balance,
            equity=self.equity,
            margin_used=self.margin_used,
            free_margin=self.equity - self.margin_used,
            margin_level_pct=(self.equity / self.margin_used * 100.0) 
                             if self.margin_used > 0 else float('inf'),
            open_position=self.position,
            daily_pnl=self._daily_pnl,
            weekly_pnl=self._weekly_pnl,
            total_trades=len(self.trades),
        )
        self.states.append(state)
        return state
    
    def get_state(self) -> BrokerState:
        """Return latest state."""
        if not self.states:
            return BrokerState(
                timestamp=pd.Timestamp.now(),
                balance=self.balance,
                equity=self.equity,
                margin_used=self.margin_used,
                free_margin=self.equity - self.margin_used,
                margin_level_pct=0.0,
            )
        return self.states[-1]
    
    def flatten(self, bar: pd.Series, reason: str = "flatten"):
        """Close any open position immediately."""
        if self.position is None:
            return
        ts = bar.name if isinstance(bar.name, pd.Timestamp) else pd.Timestamp(bar.name)
        self._close_position(bar, ts, reason)
    
    def get_equity_curve(self) -> pd.Series:
        """Return equity curve as time-indexed Series."""
        if not self.states:
            return pd.Series(dtype=float)
        return pd.Series(
            {s.timestamp: s.equity for s in self.states}
        )
    
    def get_trade_stats(self) -> dict:
        """Compute trade statistics."""
        if not self.trades:
            return {"total_trades": 0, "win_rate": 0.0, "avg_pnl": 0.0}
        
        pnls = [t.net_pnl for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        return {
            "total_trades": len(self.trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / len(pnls) if pnls else 0.0,
            "avg_pnl": np.mean(pnls),
            "avg_win": np.mean(wins) if wins else 0.0,
            "avg_loss": np.mean(losses) if losses else 0.0,
            "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf'),
            "max_consecutive_wins": self._max_consecutive(pnls, win=True),
            "max_consecutive_losses": self._max_consecutive(pnls, win=False),
        }
    
    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------
    
    def _target_direction_from_decision(self, decision: WrappedDecision) -> int:
        """Map risk wrapper decision to target position direction."""
        action = decision.action
        
        if action in (Action.KILL_SWITCH, Action.FLATTEN):
            return 0
        elif action == Action.BLOCK:
            # Maintain current position (if any)
            return self.position.direction if self.position else 0
        elif action == Action.REDUCE:
            # Direction same but we handle sizing later
            return decision.final_direction
        elif action == Action.ALLOW:
            return decision.final_direction
        else:
            return 0
    
    def _execute_if_needed(self, target_direction: int,
                           decision: WrappedDecision,
                           bar: pd.Series, ts: pd.Timestamp):
        """Execute trades if target direction differs from current."""
        current_direction = self.position.direction if self.position else 0
        
        # No change needed
        if target_direction == current_direction:
            return
        
        # Close existing position if flipping or flattening
        if self.position is not None and target_direction != current_direction:
            self._close_position(bar, ts, self._exit_reason(decision))
        
        # Open new position if target is non-zero
        if target_direction != 0:
            size_lots = self._calculate_lot_size(decision, bar)
            if size_lots >= self.cfg.min_lot_size:
                self._open_position(target_direction, size_lots, bar, ts, decision)
    
    def _open_position(self, direction: int, size_lots: float,
                       bar: pd.Series, ts: pd.Timestamp,
                       decision: WrappedDecision):
        """Simulate opening a position."""
        mid = float(bar["close"])
        spread = self._get_spread(bar)
        
        # Long fills at ask, short fills at bid
        if direction == 1:
            fill_price = mid + spread / 2.0
            side = TradeSide.BUY
        else:
            fill_price = mid - spread / 2.0
            side = TradeSide.SELL
        
        # Add slippage against the trader
        slippage = self._draw_slippage()
        fill_price += slippage if direction == 1 else -slippage
        
        # Commission on open (half round-turn)
        commission = self._commission(size_lots) / 2.0
        self.balance -= commission
        
        self.position = Position(
            direction=direction,
            size_lots=size_lots,
            entry_price=fill_price,
            entry_time=ts,
            entry_spread=spread,
            commission_paid=commission,
        )
        
        self.fills.append(FillEvent(
            timestamp=ts,
            action=TradeAction.OPEN,
            side=side,
            size_lots=size_lots,
            fill_price=fill_price,
            spread=spread,
            slippage=slippage,
            commission=commission,
            balance_before=self.balance + commission,
            balance_after=self.balance,
            reason=decision.reason or "signal",
        ))
    
    def _close_position(self, bar: pd.Series, ts: pd.Timestamp, reason: str):
        """Simulate closing the current position."""
        if self.position is None:
            return
        
        mid = float(bar["close"])
        spread = self._get_spread(bar)
        
        # Long closes at bid, short closes at ask
        if self.position.is_long:
            fill_price = mid - spread / 2.0
            side = TradeSide.SELL
        else:
            fill_price = mid + spread / 2.0
            side = TradeSide.BUY
        
        # Slippage
        slippage = self._draw_slippage()
        fill_price -= slippage if self.position.is_long else -slippage
        
        # Realized P&L
        price_change = fill_price - self.position.entry_price
        gross_pnl = self.position.direction * self.position.size_lots * OZ_PER_LOT * price_change
        
        # Commission on close (half round-turn)
        commission = self._commission(self.position.size_lots) / 2.0
        net_pnl = gross_pnl - commission
        
        self.balance += gross_pnl - commission
        
        # Record trade
        holding_bars = self._current_bar_idx - self._bar_idx_at(self.position.entry_time)
        self.trades.append(TradeRecord(
            entry_time=self.position.entry_time,
            exit_time=ts,
            direction=self.position.direction,
            size_lots=self.position.size_lots,
            entry_price=self.position.entry_price,
            exit_price=fill_price,
            gross_pnl=gross_pnl,
            commission=self.position.commission_paid + commission,
            net_pnl=net_pnl,
            holding_bars=max(holding_bars, 1),
            exit_reason=reason,
        ))
        
        self.fills.append(FillEvent(
            timestamp=ts,
            action=TradeAction.CLOSE,
            side=side,
            size_lots=self.position.size_lots,
            fill_price=fill_price,
            spread=spread,
            slippage=slippage,
            commission=commission,
            realized_pnl=net_pnl,
            balance_before=self.balance - net_pnl,
            balance_after=self.balance,
            reason=reason,
        ))
        
        self.position = None
        self.equity = self.balance
    
    # ------------------------------------------------------------------
    # Sizing, spread, slippage, commission, margin
    # ------------------------------------------------------------------
    
    def _calculate_lot_size(self, decision: WrappedDecision,
                            bar: pd.Series) -> float:
        """Convert risk wrapper scale to lot size, respecting min lot.
        
        Base sizing: 1.0 lot per $100k equity (matches vectorized backtest).
        Risk wrapper scale further modulates based on vol targeting.
        """
        scale = decision.position_scale
        equity = self.get_state().equity
        
        # Base: proportional to account size, 1.0 lot per $100k
        base_lots = equity / 100000.0
        
        raw_lots = base_lots * scale
        
        # Round to lot step
        rounded = round(raw_lots / self.cfg.lot_step) * self.cfg.lot_step
        
        # Apply min/max
        return max(rounded, self.cfg.min_lot_size)
    
    def _get_spread(self, bar: pd.Series) -> float:
        """Extract or estimate spread from bar data in price terms (USD).
        
        MT5 data stores spread in 'points' where for XAUUSD:
        1 point = $0.01 (1 cent). We convert to dollars.
        """
        if "spread" in bar:
            # MT5 spread column is in points; convert to price
            typical_price = float(bar["close"])
            if typical_price > 1000:  # XAUUSD, XAGUSD
                point_value = 0.01
            elif typical_price < 10:  # FX pairs
                point_value = 0.00001
            else:
                point_value = 0.01
            return float(bar["spread"]) * point_value
        if "ask" in bar and "bid" in bar:
            return float(bar["ask"] - bar["bid"])
        # Estimate: use high-low as proxy (conservative)
        return float(bar["high"] - bar["low"]) * 0.3
    
    def _draw_slippage(self) -> float:
        """Draw random slippage in price terms."""
        # slippage_pips is in cents ($0.01 = 1 pip for XAUUSD)
        slippage_pips = max(0, self.rng.normal(
            self.cfg.slippage_pips_mean,
            self.cfg.slippage_pips_std,
        ))
        return slippage_pips * PIP_VALUE
    
    def _commission(self, size_lots: float) -> float:
        """Round-turn commission for given lot size."""
        return size_lots * self.cfg.commission_per_lot
    
    def _update_margin(self, bar: pd.Series):
        """Recalculate margin used based on open position."""
        if self.position is None:
            self.margin_used = 0.0
            return
        
        price = float(bar["close"])
        notional = self.position.size_lots * OZ_PER_LOT * price
        self.margin_used = notional / self.cfg.leverage
    
    def _update_time_tracking(self, ts: pd.Timestamp, bar: pd.Series):
        """Update daily/weekly P&L tracking."""
        current_day = ts.normalize()
        if self._last_trade_day is None or current_day != self._last_trade_day:
            self._daily_pnl = 0.0
            self._last_trade_day = current_day
        
        # Simple approach: accumulate equity change from previous state
        if len(self.states) >= 2:
            change = self.equity - self.states[-1].equity
            self._daily_pnl += change
            self._weekly_pnl += change
    
    def _exit_reason(self, decision: WrappedDecision) -> str:
        """Generate human-readable exit reason."""
        action = decision.action
        reasons = decision.sub_reasons
        if action == Action.KILL_SWITCH:
            return "kill_switch"
        elif action == Action.FLATTEN:
            return "risk_flatten"
        elif reasons:
            return reasons[0]
        return "signal_change"
    
    def _bar_idx_at(self, ts: pd.Timestamp) -> int:
        """Approximate bar index from timestamp (fallback)."""
        # Simple fallback: if we can't map exactly, use current - 1
        return max(0, self._current_bar_idx - 1)
    
    def _max_consecutive(self, pnls: List[float], win: bool) -> int:
        """Count max consecutive wins or losses."""
        max_streak = 0
        current = 0
        for p in pnls:
            is_match = (p > 0) if win else (p <= 0)
            if is_match:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak
