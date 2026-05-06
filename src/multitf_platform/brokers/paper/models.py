"""Data models for paper broker execution."""
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum
import pandas as pd


class TradeSide(Enum):
    BUY = "buy"
    SELL = "sell"


class TradeAction(Enum):
    OPEN = "open"
    CLOSE = "close"
    FLATTEN = "flatten"
    PARTIAL_CLOSE = "partial_close"


@dataclass
class Position:
    """Open position state."""
    direction: int  # 1=long, -1=short
    size_lots: float
    entry_price: float
    entry_time: pd.Timestamp
    entry_spread: float
    unrealized_pnl: float = 0.0
    commission_paid: float = 0.0
    
    @property
    def is_long(self) -> bool:
        return self.direction == 1
    
    @property
    def is_short(self) -> bool:
        return self.direction == -1
    
    @property
    def notional(self) -> float:
        """Position notional value in USD."""
        return self.size_lots * 100.0 * self.entry_price
    
    def update_unrealized_pnl(self, mark_price: float):
        """Update unrealized P&L at current mark price."""
        price_change = mark_price - self.entry_price
        self.unrealized_pnl = self.direction * self.size_lots * 100.0 * price_change


@dataclass
class FillEvent:
    """Record of a simulated fill."""
    timestamp: pd.Timestamp
    action: TradeAction
    side: TradeSide
    size_lots: float
    fill_price: float
    spread: float
    slippage: float
    commission: float
    realized_pnl: Optional[float] = None
    balance_before: float = 0.0
    balance_after: float = 0.0
    reason: str = ""


@dataclass
class TradeRecord:
    """Completed round-trip trade."""
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int
    size_lots: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    commission: float
    net_pnl: float
    holding_bars: int
    exit_reason: str


@dataclass
class BrokerState:
    """Snapshot of broker account state."""
    timestamp: pd.Timestamp
    balance: float
    equity: float
    margin_used: float
    free_margin: float
    margin_level_pct: float
    open_position: Optional[Position] = None
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    total_trades: int = 0
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "balance": self.balance,
            "equity": self.equity,
            "margin_used": self.margin_used,
            "free_margin": self.free_margin,
            "margin_level_pct": self.margin_level_pct,
            "position_direction": self.open_position.direction if self.open_position else 0,
            "position_size_lots": self.open_position.size_lots if self.open_position else 0.0,
            "position_upnl": self.open_position.unrealized_pnl if self.open_position else 0.0,
            "daily_pnl": self.daily_pnl,
            "weekly_pnl": self.weekly_pnl,
            "total_trades": self.total_trades,
        }
