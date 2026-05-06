"""Pydantic config models for the MultiTF platform."""
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    name: str = "MultiTF"
    version: str = "1.0.0"
    package: str = "multitf_platform.strategy.frozen.v1_0_0"
    symbol: str = "XAUUSD"
    entry_timeframe: Literal["H1", "H4", "D1"] = "H1"
    confirmation_timeframe: Literal["H1", "H4", "D1"] = "H4"
    h1_lookback: int = Field(default=100, ge=10, le=500)
    h4_lookback: int = Field(default=50, ge=10, le=500)
    require_native_h4: bool = True
    allow_internal_resample: bool = False


class VolatilityGateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    enabled: bool = True
    atr_lookback_bars: int = Field(default=252, ge=20, le=1000)
    realized_vol_lookback_bars: int = Field(default=100, ge=20, le=500)
    allow_atr_percentile_min: float = Field(default=20.0, ge=0, le=100)
    allow_atr_percentile_max: float = Field(default=80.0, ge=0, le=100)
    block_new_trades_atr_percentile_above: float = Field(default=85.0, ge=0, le=100)
    flatten_positions_atr_percentile_above: float = Field(default=95.0, ge=0, le=100)
    block_new_trades_atr_percentile_below: float = Field(default=15.0, ge=0, le=100)


class SpreadFilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    enabled: bool = True
    max_spread_multiple_of_median: float = Field(default=1.5, ge=1.0, le=5.0)
    median_lookback_bars: int = Field(default=96, ge=10, le=1000)


class SlippageFilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    enabled: bool = True
    max_expected_slippage_bps: float = Field(default=10.0, ge=0, le=100)


class FlipFilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    enabled: bool = True
    lookback_bars: int = Field(default=48, ge=10, le=500)
    max_signal_flips: int = Field(default=3, ge=1, le=20)
    cooldown_bars: int = Field(default=24, ge=1, le=200)


class TradeThrottleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    enabled: bool = True
    max_trades_per_day: int = Field(default=2, ge=1, le=50)
    max_trades_per_week: int = Field(default=8, ge=1, le=200)
    min_bars_between_flips: int = Field(default=4, ge=1, le=50)
    cooldown_after_loss_bars: int = Field(default=6, ge=0, le=100)
    cooldown_after_three_losses_bars: int = Field(default=24, ge=0, le=500)


class SizingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    base_risk_per_trade_pct: float = Field(default=0.25, ge=0.01, le=10.0)
    max_risk_per_trade_pct: float = Field(default=0.50, ge=0.01, le=10.0)
    max_portfolio_heat_pct: float = Field(default=1.0, ge=0.1, le=10.0)
    target_annualized_vol_pct: float = Field(default=8.0, ge=1.0, le=50.0)
    min_position_scale: float = Field(default=0.25, ge=0.0, le=1.0)
    max_position_scale: float = Field(default=1.0, ge=0.1, le=5.0)
    hard_max_leverage: float = Field(default=1.0, ge=0.1, le=10.0)


class CircuitBreakerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    daily_loss_stop_pct: float = Field(default=1.0, ge=0.1, le=20.0)
    weekly_loss_stop_pct: float = Field(default=3.0, ge=0.1, le=30.0)
    monthly_loss_stop_pct: float = Field(default=6.0, ge=0.1, le=50.0)
    total_drawdown_warning_pct: float = Field(default=8.0, ge=1.0, le=50.0)
    total_drawdown_kill_pct: float = Field(default=15.0, ge=1.0, le=50.0)
    manual_restart_required: bool = True
    flatten_on_kill: bool = True
    block_new_trades_while_killed: bool = True


class ExecutionProtectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    reject_stale_quotes: bool = True
    stale_quote_max_age_seconds: int = Field(default=5, ge=1, le=60)
    reject_during_disconnect: bool = True
    reject_unknown_spread: bool = True
    require_order_check: bool = True


class WeekendPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    block_new_positions_before_weekend_minutes: int = Field(default=60, ge=0, le=480)
    flatten_high_risk_positions_before_weekend: bool = True


class NewsFilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    enabled: bool = True
    block_nfp_day: bool = True
    nfp_buffer_hours: int = Field(default=24, ge=0, le=72)
    block_fomc_day: bool = False
    fomc_buffer_hours: int = Field(default=24, ge=0, le=72)
    block_nfp_week: bool = False


class RiskWrapperConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    version: str = "1.1.0"
    enabled: bool = True
    volatility_gate: VolatilityGateConfig = Field(default_factory=VolatilityGateConfig)
    spread_filter: SpreadFilterConfig = Field(default_factory=SpreadFilterConfig)
    slippage_filter: SlippageFilterConfig = Field(default_factory=SlippageFilterConfig)
    flip_filter: FlipFilterConfig = Field(default_factory=FlipFilterConfig)
    trade_throttle: TradeThrottleConfig = Field(default_factory=TradeThrottleConfig)
    sizing: SizingConfig = Field(default_factory=SizingConfig)
    circuit_breakers: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    execution_protection: ExecutionProtectionConfig = Field(default_factory=ExecutionProtectionConfig)
    weekend_policy: WeekendPolicyConfig = Field(default_factory=WeekendPolicyConfig)
    news_filter: NewsFilterConfig = Field(default_factory=NewsFilterConfig)


class BrokerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    adapter: Literal["mock", "paper", "mt5", "oanda", "ig"] = "paper"
    symbol: str = "XAUUSD.s"
    initial_equity: float = Field(default=10300.0, ge=10.0)
    leverage: int = Field(default=1000, ge=1, le=2000)
    account_currency: str = "USD"
    execution_mode: Literal["quote_replay", "live"] = "quote_replay"
    commission_per_lot: float = Field(default=7.0, ge=0.0)
    spread_source: Literal["data", "estimate", "broker"] = "data"
    min_lot_size: float = Field(default=0.01, ge=0.001, le=1.0)
    lot_step: float = Field(default=0.01, ge=0.001, le=1.0)
    slippage_pips_mean: float = Field(default=0.5, ge=0.0, le=10.0)
    slippage_pips_std: float = Field(default=0.3, ge=0.0, le=5.0)


class PlatformConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    name: str = "multitf-platform"
    environment: Literal["research", "paper", "live"] = "paper"
    canonical_timezone: str = "UTC"
    reporting_timezone: str = "Europe/Lisbon"
    risk_reset_timezone: str = "UTC"
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk_wrapper: RiskWrapperConfig = Field(default_factory=RiskWrapperConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
