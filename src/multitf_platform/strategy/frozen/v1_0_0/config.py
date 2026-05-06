"""Configuration models for frozen MultiTF v1.0.0."""
from pydantic import BaseModel, Field


class FrozenStrategyConfig(BaseModel):
    """Immutable configuration for MultiTF v1.0.0.
    
    Changing these parameters requires creating a new versioned strategy package.
    """
    symbol: str = "XAUUSD"
    entry_timeframe: str = "H1"
    confirmation_timeframe: str = "H4"
    h1_lookback: int = Field(default=100, ge=10, le=500)
    h4_lookback: int = Field(default=50, ge=10, le=500)
    min_h1_bars: int = Field(default=200, ge=100, le=1000)
    min_h4_bars: int = Field(default=100, ge=50, le=500)
    warmup_required: bool = True
