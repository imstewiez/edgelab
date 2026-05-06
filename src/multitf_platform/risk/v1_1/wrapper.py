"""Risk Wrapper v1.1 - Hard controls without modifying alpha."""
from dataclasses import dataclass, field
from typing import Optional, Literal
from enum import Enum
import pandas as pd
import numpy as np

from ...config.models import RiskWrapperConfig
from ...strategy.frozen.v1_0_0 import SignalDecision
from .regime import RegimeDetector, MarketRegime
from .correlation import CorrelationRiskChecker
from .kelly import KellySizer
from .session_filter import SessionFilter, SessionStatus
from .garch_forecast import GARCHForecaster
from .expectancy_filter import ExpectancyFilter
from .weekend_filter import WeekendFilter
from .economic_calendar import EconomicCalendar


class Action(Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REDUCE = "REDUCE"
    FLATTEN = "FLATTEN"
    KILL_SWITCH = "KILL_SWITCH"


@dataclass
class WrappedDecision:
    """Output from risk wrapper."""
    action: Action
    original_signal: SignalDecision
    position_scale: float  # 0.0 to 1.0 multiplier
    reason: Optional[str] = None
    sub_reasons: list = field(default_factory=list)
    
    @property
    def final_direction(self) -> int:
        """Effective direction after risk controls."""
        if self.action in (Action.BLOCK, Action.KILL_SWITCH):
            return 0
        if self.action == Action.FLATTEN:
            return 0
        return self.original_signal.direction
    
    @property
    def is_passed(self) -> bool:
        return self.action == Action.ALLOW and self.position_scale > 0


@dataclass
class RiskState:
    """Mutable state tracked by risk wrapper across bars."""
    consecutive_losses: int = 0
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    trades_today: int = 0
    trades_this_week: int = 0
    last_trade_day: Optional[pd.Timestamp] = None
    last_flip_bar: Optional[pd.Timestamp] = None
    recent_signals: list = field(default_factory=list)
    kill_switch_active: bool = False
    kill_reason: Optional[str] = None
    peak_equity: float = 0.0
    current_equity: float = 0.0
    cooldown_bars_remaining: int = 0


class RiskWrapper:
    """Wraps frozen strategy signals in hard risk controls.
    
    Order of operations:
    1. Check kill switch (highest priority)
    2. Check circuit breakers (drawdown, daily/weekly/monthly loss)
    3. Check volatility gate
    4. Check spread filter
    5. Check flip/chop filter
    6. Check trade throttle
    7. Apply position sizing
    """
    
    VERSION = "1.1.0"
    
    def __init__(self, config: RiskWrapperConfig):
        self.config = config
        self.state = RiskState()
        self.regime = RegimeDetector()
        self.correlation = CorrelationRiskChecker()
        self.kelly = KellySizer()
        self.session = SessionFilter(block_asian=True)
        self.garch = GARCHForecaster()
        self.expectancy = ExpectancyFilter()
        self.weekend = WeekendFilter(close_before_weekend=True, block_weekend=True)
        self.calendar = EconomicCalendar()
    
    def apply(
        self,
        signal: SignalDecision,
        h1_bars: pd.DataFrame,
        equity: float,
        spread_points: Optional[float] = None
    ) -> WrappedDecision:
        """Apply full risk wrapper to a signal decision.
        
        Args:
            signal: The raw signal from frozen MultiTF v1.0.0
            h1_bars: Recent H1 bars for ATR/volatility calculation
            equity: Current account equity
            spread_points: Current spread in points (optional)
            
        Returns:
            WrappedDecision with action, scale, and reasons
        """
        if not self.config.enabled:
            return WrappedDecision(
                action=Action.ALLOW,
                original_signal=signal,
                position_scale=1.0,
                reason="Risk wrapper disabled"
            )
        
        sub_reasons = []
        position_scale = 1.0
        
        # 1. Kill switch check
        if self.state.kill_switch_active:
            return WrappedDecision(
                action=Action.KILL_SWITCH,
                original_signal=signal,
                position_scale=0.0,
                reason="Kill switch active: %s" % self.state.kill_reason,
                sub_reasons=sub_reasons
            )
        
        # 2. Circuit breakers
        cb_action, cb_reason = self._check_circuit_breakers(equity)
        if cb_action == Action.KILL_SWITCH:
            self.state.kill_switch_active = True
            self.state.kill_reason = cb_reason
            return WrappedDecision(
                action=Action.KILL_SWITCH,
                original_signal=signal,
                position_scale=0.0,
                reason=cb_reason,
                sub_reasons=sub_reasons
            )
        elif cb_action == Action.FLATTEN:
            sub_reasons.append(cb_reason)
            return WrappedDecision(
                action=Action.FLATTEN,
                original_signal=signal,
                position_scale=0.0,
                reason=cb_reason,
                sub_reasons=sub_reasons
            )
        
        # 3. Economic calendar (high-impact news)
        cal_blocked, cal_reason = self.calendar.is_blocked()
        if cal_blocked:
            sub_reasons.append(cal_reason)
            return WrappedDecision(
                action=Action.BLOCK,
                original_signal=signal,
                position_scale=0.0,
                reason="Economic calendar blocked",
                sub_reasons=sub_reasons
            )
        
        # 4. News filter (NFP/FOMC synthetic)
        news_ok, news_reason = self._check_news_filter(signal)
        if not news_ok:
            sub_reasons.append(news_reason)
            return WrappedDecision(
                action=Action.BLOCK,
                original_signal=signal,
                position_scale=0.0,
                reason="News filter blocked",
                sub_reasons=sub_reasons
            )
        
        # 5. Weekend gap filter
        weekend_allow, weekend_reason = self.weekend.allow_new_trade()
        if not weekend_allow:
            sub_reasons.append(weekend_reason)
            return WrappedDecision(
                action=Action.BLOCK,
                original_signal=signal,
                position_scale=0.0,
                reason="Weekend filter blocked",
                sub_reasons=sub_reasons
            )
        
        # 6. Session filter (London + NY only)
        session_status, session_scale, session_reason = self.session.check()
        if session_status == SessionStatus.BLOCKED:
            sub_reasons.append(session_reason)
            return WrappedDecision(
                action=Action.BLOCK,
                original_signal=signal,
                position_scale=0.0,
                reason="Session filter blocked",
                sub_reasons=sub_reasons
            )
        position_scale *= session_scale
        if session_scale < 1.0:
            sub_reasons.append(session_reason)
        
        # 5. Volatility gate
        vol_scale, vol_reason = self._check_volatility(h1_bars)
        if vol_scale == 0.0:
            sub_reasons.append(vol_reason)
            return WrappedDecision(
                action=Action.BLOCK,
                original_signal=signal,
                position_scale=0.0,
                reason="Volatility gate blocked",
                sub_reasons=sub_reasons
            )
        position_scale *= vol_scale
        if vol_scale < 1.0:
            sub_reasons.append(vol_reason)
        
        # 7. Spread filter
        if spread_points is not None:
            spread_ok, spread_reason = self._check_spread(h1_bars, spread_points)
            if not spread_ok:
                sub_reasons.append(spread_reason)
                return WrappedDecision(
                    action=Action.BLOCK,
                    original_signal=signal,
                    position_scale=0.0,
                    reason="Spread filter blocked",
                    sub_reasons=sub_reasons
                )
        
        # 8. Flip/chop filter
        flip_ok, flip_reason = self._check_flip_chop(signal, h1_bars)
        if not flip_ok:
            sub_reasons.append(flip_reason)
            return WrappedDecision(
                action=Action.BLOCK,
                original_signal=signal,
                position_scale=0.0,
                reason="Flip/chop filter blocked",
                sub_reasons=sub_reasons
            )
        
        # 9. Trade throttle
        throttle_ok, throttle_reason = self._check_trade_throttle(signal)
        if not throttle_ok:
            sub_reasons.append(throttle_reason)
            return WrappedDecision(
                action=Action.BLOCK,
                original_signal=signal,
                position_scale=0.0,
                reason="Trade throttle blocked",
                sub_reasons=sub_reasons
            )
        
        # 10. Regime detection
        regime = self.regime.detect(h1_bars)
        adj = self.regime.get_position_adjustments()
        if adj["block_new"]:
            sub_reasons.append(f"Regime: {regime.value} (blocking)")
            return WrappedDecision(
                action=Action.BLOCK,
                original_signal=signal,
                position_scale=0.0,
                reason=f"Market regime blocked: {regime.value}",
                sub_reasons=sub_reasons
            )
        position_scale *= adj["scale"]
        if adj["scale"] < 1.0:
            sub_reasons.append(f"Regime: {regime.value} (scale {adj['scale']:.0%})")
        
        # 11. Correlation risk check (requires existing_positions dict)
        # Note: existing_positions passed via h1_bars metadata if available
        # This is checked at execution time, not signal time
        
        # 12. Expectancy filter
        ev_allow, ev_value, ev_reason = self.expectancy.check_trade()
        if not ev_allow:
            sub_reasons.append(ev_reason)
            return WrappedDecision(
                action=Action.BLOCK,
                original_signal=signal,
                position_scale=0.0,
                reason="Expectancy filter blocked",
                sub_reasons=sub_reasons
            )
        if ev_value > 0:
            sub_reasons.append(ev_reason)
        
        # 13. Position sizing (GARCH forecast + volatility targeting + Kelly)
        size_scale, size_reason = self._calculate_position_size(h1_bars, equity)
        position_scale *= size_scale
        if size_scale < 1.0:
            sub_reasons.append(size_reason)
        
        # Clamp to valid range
        position_scale = max(0.0, min(1.0, position_scale))
        
        if position_scale == 0.0:
            return WrappedDecision(
                action=Action.BLOCK,
                original_signal=signal,
                position_scale=0.0,
                reason="Position scale reduced to zero",
                sub_reasons=sub_reasons
            )
        
        action = Action.REDUCE if position_scale < 1.0 else Action.ALLOW
        
        return WrappedDecision(
            action=action,
            original_signal=signal,
            position_scale=position_scale,
            reason="Passed all gates" if action == Action.ALLOW else "Reduced by risk controls",
            sub_reasons=sub_reasons
        )
    
    def _check_circuit_breakers(self, equity: float) -> tuple:
        """Check daily, weekly, monthly, and total drawdown stops."""
        cfg = self.config.circuit_breakers
        
        # Update peak equity
        self.state.peak_equity = max(self.state.peak_equity, equity)
        self.state.current_equity = equity
        
        drawdown_pct = (self.state.peak_equity - equity) / self.state.peak_equity * 100
        
        # Total drawdown kill
        if drawdown_pct >= cfg.total_drawdown_kill_pct:
            return Action.KILL_SWITCH, "Total drawdown kill: %.1f%% >= %.1f%%" % (
                drawdown_pct, cfg.total_drawdown_kill_pct)
        
        # Total drawdown warning + flatten
        if drawdown_pct >= cfg.total_drawdown_warning_pct:
            return Action.FLATTEN, "Drawdown warning: %.1f%% >= %.1f%%" % (
                drawdown_pct, cfg.total_drawdown_warning_pct)
        
        # Daily loss stop
        if abs(self.state.daily_pnl) >= cfg.daily_loss_stop_pct / 100:
            return Action.FLATTEN, "Daily loss stop: %.2f%%" % (abs(self.state.daily_pnl) * 100)
        
        # Weekly loss stop
        if abs(self.state.weekly_pnl) >= cfg.weekly_loss_stop_pct / 100:
            return Action.FLATTEN, "Weekly loss stop: %.2f%%" % (abs(self.state.weekly_pnl) * 100)
        
        # Monthly loss stop
        if abs(self.state.monthly_pnl) >= cfg.monthly_loss_stop_pct / 100:
            return Action.FLATTEN, "Monthly loss stop: %.2f%%" % (abs(self.state.monthly_pnl) * 100)
        
        return Action.ALLOW, ""
    
    def _check_volatility(self, h1_bars: pd.DataFrame) -> tuple:
        """Check ATR percentile and return position scale."""
        cfg = self.config.volatility_gate
        
        if not cfg.enabled or len(h1_bars) < cfg.atr_lookback_bars:
            return 1.0, ""
        
        atr = (h1_bars["high"] - h1_bars["low"]).rolling(cfg.atr_lookback_bars).mean()
        atr_pct = atr / h1_bars["close"]
        current_atr_pct = atr_pct.iloc[-1]
        
        # Calculate percentiles from historical data
        hist = atr_pct.dropna()
        if len(hist) < 100:
            return 1.0, ""
        
        p_min = np.percentile(hist, cfg.allow_atr_percentile_min)
        p_max = np.percentile(hist, cfg.allow_atr_percentile_max)
        p_block_high = np.percentile(hist, cfg.block_new_trades_atr_percentile_above)
        p_flatten = np.percentile(hist, cfg.flatten_positions_atr_percentile_above)
        p_block_low = np.percentile(hist, cfg.block_new_trades_atr_percentile_below)
        
        # Extreme high vol -> flatten everything
        if current_atr_pct >= p_flatten:
            return 0.0, "ATR %.4f >= flatten threshold %.4f (%.0fth pct)" % (
                current_atr_pct, p_flatten, cfg.flatten_positions_atr_percentile_above)
        
        # High vol -> block new trades
        if current_atr_pct >= p_block_high:
            return 0.0, "ATR %.4f >= block threshold %.4f (%.0fth pct)" % (
                current_atr_pct, p_block_high, cfg.block_new_trades_atr_percentile_above)
        
        # Low vol -> block (not enough movement for edge)
        if current_atr_pct <= p_block_low:
            return 0.0, "ATR %.4f <= block threshold %.4f (%.0fth pct)" % (
                current_atr_pct, p_block_low, cfg.block_new_trades_atr_percentile_below)
        
        # Above normal range -> reduce to 50%
        if current_atr_pct > p_max:
            return 0.5, "ATR %.4f > max normal %.4f (%.0fth pct), reduced to 50%%" % (
                current_atr_pct, p_max, cfg.allow_atr_percentile_max)
        
        # Below normal range -> reduce to 50%
        if current_atr_pct < p_min:
            return 0.5, "ATR %.4f < min normal %.4f (%.0fth pct), reduced to 50%%" % (
                current_atr_pct, p_min, cfg.allow_atr_percentile_min)
        
        return 1.0, ""
    
    def _check_spread(self, h1_bars: pd.DataFrame, spread_points: float) -> tuple:
        """Check if current spread is within acceptable range."""
        cfg = self.config.spread_filter
        
        if not cfg.enabled:
            return True, ""
        
        # Estimate median spread from recent bars
        if "spread" in h1_bars.columns:
            recent_spread = h1_bars["spread"].tail(cfg.median_lookback_bars)
        elif "avg_spread" in h1_bars.columns:
            recent_spread = h1_bars["avg_spread"].tail(cfg.median_lookback_bars)
        else:
            # Estimate from high-low
            recent_spread = (h1_bars["high"] - h1_bars["low"]).tail(cfg.median_lookback_bars) * 0.1
        
        median_spread = recent_spread.median()
        if median_spread == 0 or pd.isna(median_spread):
            return True, ""
        
        max_allowed = median_spread * cfg.max_spread_multiple_of_median
        
        if spread_points > max_allowed:
            return False, "Spread %.1f > max allowed %.1f (%.1fx median)" % (
                spread_points, max_allowed, cfg.max_spread_multiple_of_median)
        
        return True, ""
    
    def _check_flip_chop(self, signal: SignalDecision, h1_bars: pd.DataFrame) -> tuple:
        """Check if signal is flipping too frequently (chop detection)."""
        cfg = self.config.flip_filter
        
        if not cfg.enabled:
            return True, ""
        
        # Track recent signals
        self.state.recent_signals.append(signal.direction)
        if len(self.state.recent_signals) > cfg.lookback_bars:
            self.state.recent_signals.pop(0)
        
        if len(self.state.recent_signals) < cfg.lookback_bars:
            return True, ""
        
        # Count flips (changes from one bar to next)
        flips = sum(1 for i in range(1, len(self.state.recent_signals))
                    if self.state.recent_signals[i] != self.state.recent_signals[i-1]
                    and self.state.recent_signals[i] != 0
                    and self.state.recent_signals[i-1] != 0)
        
        if flips > cfg.max_signal_flips:
            return False, "%d flips in %d bars > max %d (chop detected)" % (
                flips, cfg.lookback_bars, cfg.max_signal_flips)
        
        return True, ""
    
    def _check_trade_throttle(self, signal: SignalDecision) -> tuple:
        """Check daily/weekly trade limits and cooldowns."""
        cfg = self.config.trade_throttle
        
        if not cfg.enabled:
            return True, ""
        
        now = signal.timestamp
        
        # Reset daily/weekly counters
        if self.state.last_trade_day is not None:
            if now.date() != self.state.last_trade_day.date():
                self.state.trades_today = 0
                self.state.daily_pnl = 0.0
            if now.isocalendar()[1] != self.state.last_trade_day.isocalendar()[1]:
                self.state.trades_this_week = 0
                self.state.weekly_pnl = 0.0
        
        # Check daily limit
        if self.state.trades_today >= cfg.max_trades_per_day:
            return False, "Daily trade limit reached: %d/%d" % (
                self.state.trades_today, cfg.max_trades_per_day)
        
        # Check weekly limit
        if self.state.trades_this_week >= cfg.max_trades_per_week:
            return False, "Weekly trade limit reached: %d/%d" % (
                self.state.trades_this_week, cfg.max_trades_per_week)
        
        # Check cooldown
        if self.state.cooldown_bars_remaining > 0:
            self.state.cooldown_bars_remaining -= 1
            return False, "Cooldown active: %d bars remaining" % self.state.cooldown_bars_remaining
        
        # Check min bars between flips
        if self.state.last_flip_bar is not None:
            bars_since_flip = len(pd.date_range(self.state.last_flip_bar, now, freq="h")) - 1
            if bars_since_flip < cfg.min_bars_between_flips:
                return False, "Too soon after last flip: %d bars < %d minimum" % (
                    bars_since_flip, cfg.min_bars_between_flips)
        
        return True, ""
    
    def _check_news_filter(self, signal: SignalDecision) -> tuple:
        """Check if current date is near high-impact news events."""
        cfg = self.config.news_filter
        if not cfg.enabled:
            return True, ""
        
        ts = signal.timestamp
        if pd.isna(ts):
            return True, ""
        
        # Make timezone-naive for comparison
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        
        # NFP: first Friday of each month
        if cfg.block_nfp_day or cfg.block_nfp_week:
            # Find first Friday of this month
            first_day = pd.Timestamp(ts.year, ts.month, 1)
            first_friday = first_day + pd.Timedelta(days=(4 - first_day.dayofweek) % 7)
            
            if cfg.block_nfp_week:
                week_start = first_friday - pd.Timedelta(days=first_friday.dayofweek)
                week_end = week_start + pd.Timedelta(days=6)
                if week_start <= ts <= week_end:
                    return False, "NFP week block"
            
            if cfg.block_nfp_day:
                nfp_start = first_friday - pd.Timedelta(hours=cfg.nfp_buffer_hours)
                nfp_end = first_friday + pd.Timedelta(hours=cfg.nfp_buffer_hours)
                if nfp_start <= ts <= nfp_end:
                    return False, "NFP day +/-%dh block" % cfg.nfp_buffer_hours
        
        # FOMC: approximate mid-month Wednesday (simplified)
        if cfg.block_fomc_day:
            # Check if this is a Wednesday in the middle of the month
            if ts.dayofweek == 2 and 15 <= ts.day <= 23:
                fomc_start = ts - pd.Timedelta(hours=cfg.fomc_buffer_hours)
                fomc_end = ts + pd.Timedelta(hours=cfg.fomc_buffer_hours)
                if fomc_start <= ts <= fomc_end:
                    return False, "FOMC day +/-%dh block" % cfg.fomc_buffer_hours
        
        return True, ""
    
    def _calculate_position_size(self, h1_bars: pd.DataFrame, equity: float) -> tuple:
        """Calculate position scale based on GARCH forecast + volatility targeting + Kelly."""
        cfg = self.config.sizing
        
        if len(h1_bars) < 20:
            return cfg.min_position_scale, "Insufficient bars for vol sizing"
        
        # Realized volatility (annualized)
        returns = h1_bars["close"].pct_change().dropna()
        if len(returns) < 20:
            return cfg.min_position_scale, "Insufficient returns for vol sizing"
        
        realized_vol = returns.std() * np.sqrt(252 * 24) * 100  # annualized %
        
        if realized_vol <= 0:
            return cfg.min_position_scale, "Zero realized volatility"
        
        # GARCH forecast volatility
        garch_scale = self.garch.get_position_scale(h1_bars, target_vol=cfg.target_annualized_vol_pct)
        garch_diag = self.garch.get_diagnostics()
        
        # Target vol / realized vol = position scale
        vol_scale = cfg.target_annualized_vol_pct / realized_vol
        
        # Blend historical and GARCH: 60% GARCH, 40% historical
        blended_vol_scale = 0.6 * garch_scale + 0.4 * vol_scale
        
        # Kelly Criterion scale (fraction of equity to risk)
        kelly_frac = self.kelly.calculate(min_trades=10)
        # Normalize Kelly fraction: max Kelly = 10% of equity, so scale = kelly / 0.10
        kelly_scale = kelly_frac / 0.10
        
        # Combine: blended vol targeting × Kelly fraction
        combined_scale = blended_vol_scale * kelly_scale
        
        # Clamp to min/max
        final_scale = max(cfg.min_position_scale, min(cfg.max_position_scale, combined_scale))
        
        return final_scale, "GARCH=%.2f × Hist=%.2f × Kelly=%.2f = %.2f" % (
            garch_scale, vol_scale, kelly_scale, final_scale)
    
    def update_after_trade(self, pnl_pct: float, timestamp: pd.Timestamp):
        """Update risk state after a trade closes."""
        self.state.daily_pnl += pnl_pct
        self.state.weekly_pnl += pnl_pct
        self.state.monthly_pnl += pnl_pct
        
        if pnl_pct < 0:
            self.state.consecutive_losses += 1
            
            # Apply cooldown after losses
            cfg = self.config.trade_throttle
            if self.state.consecutive_losses >= 3:
                self.state.cooldown_bars_remaining = max(
                    self.state.cooldown_bars_remaining,
                    cfg.cooldown_after_three_losses_bars
                )
            else:
                self.state.cooldown_bars_remaining = max(
                    self.state.cooldown_bars_remaining,
                    cfg.cooldown_after_loss_bars
                )
        else:
            self.state.consecutive_losses = 0
        
        self.state.trades_today += 1
        self.state.trades_this_week += 1
        self.state.last_trade_day = timestamp
        
        # Track flip
        if len(self.state.recent_signals) >= 2:
            if self.state.recent_signals[-1] != self.state.recent_signals[-2]:
                self.state.last_flip_bar = timestamp
    
    def reset_kill_switch(self):
        """Manual reset after kill switch triggers."""
        if not self.config.circuit_breakers.manual_restart_required:
            self.state.kill_switch_active = False
            self.state.kill_reason = None
            return True
        return False
    
    def manual_reset(self):
        """Force reset all risk state (use with caution)."""
        self.state = RiskState()
