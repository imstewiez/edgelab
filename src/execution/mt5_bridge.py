"""
MT5 execution bridge for XAUUSD H1 momentum strategy.
Handles order placement, position management, and risk controls.
"""
import os
import sys
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("mt5_bridge")


@dataclass
class ExecutionConfig:
    symbol: str = "XAUUSD.s"
    timeframe: int = mt5.TIMEFRAME_H1
    mom_lookback: int = 100
    base_lot_size: float = 0.005  # Conservative: 0.005 lot per $1000 equity (0.5x base size)
    max_daily_loss_pct: float = 2.0  # Stop trading if down 2% today
    max_spread_points: float = 30.0  # Don't trade if spread > 30 points
    slippage_points: int = 10
    magic_number: int = 9922550
    use_atr_stop: bool = False
    atr_stop_mult: float = 3.0  # ATR multiplier for stop loss
    atr_period: int = 20


class MT5Executor:
    """Execute momentum strategy on MT5."""
    
    def __init__(self, cfg: ExecutionConfig):
        self.cfg = cfg
        self.last_signal: Optional[int] = None
        self.last_trade_time: Optional[datetime] = None
        self.daily_pnl: float = 0.0
        self.today: Optional[datetime.date] = None
    
    def connect(self) -> bool:
        if not mt5.initialize():
            logger.error("MT5 initialize failed")
            return False
        
        info = mt5.account_info()
        if info is None:
            logger.error("Failed to get account info")
            return False
        
        logger.info(f"Connected | Account: {info.login} | Balance: {info.balance:.2f} | Equity: {info.equity:.2f}")
        
        # Ensure symbol is visible
        if not mt5.symbol_select(self.cfg.symbol, True):
            logger.error(f"Cannot select symbol {self.cfg.symbol}")
            return False
        
        sym_info = mt5.symbol_info(self.cfg.symbol)
        logger.info(f"Symbol: {self.cfg.symbol} | Bid: {sym_info.bid} | Ask: {sym_info.ask} | Spread: {sym_info.spread}pts")
        return True
    
    def disconnect(self):
        mt5.shutdown()
        logger.info("MT5 disconnected")
    
    def get_recent_bars(self, n_bars: int = 100) -> Optional[pd.DataFrame]:
        """Fetch recent H1 bars from MT5."""
        rates = mt5.copy_rates_from_pos(self.cfg.symbol, self.cfg.timeframe, 0, n_bars)
        if rates is None or len(rates) == 0:
            logger.error("Failed to copy rates")
            return None
        
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df.sort_values("time").reset_index(drop=True)
    
    def calculate_signal(self, df: pd.DataFrame) -> int:
        """Calculate momentum signal: 1=long, -1=short, 0=flat."""
        close = df["close"]
        mom = close.pct_change(self.cfg.mom_lookback).iloc[-1]
        
        if pd.isna(mom):
            return 0
        
        signal = 1 if mom > 0 else -1 if mom < 0 else 0
        logger.info(f"Momentum ({self.cfg.mom_lookback}bar): {mom:.4%} | Signal: {signal}")
        return signal
    
    def get_position(self) -> Optional[Dict]:
        """Get current position for the symbol."""
        positions = mt5.positions_get(symbol=self.cfg.symbol)
        if positions is None or len(positions) == 0:
            return None
        
        pos = positions[0]  # Assume single position per symbol
        return {
            "ticket": pos.ticket,
            "type": "buy" if pos.type == mt5.ORDER_TYPE_BUY else "sell",
            "volume": pos.volume,
            "open_price": pos.price_open,
            "profit": pos.profit,
            "swap": pos.swap,
        }
    
    def get_spread_points(self) -> float:
        sym = mt5.symbol_info(self.cfg.symbol)
        return sym.spread if sym else 999
    
    def check_risk_limits(self) -> bool:
        """Check if we should trade today."""
        info = mt5.account_info()
        if info is None:
            return False
        
        today = datetime.now().date()
        if self.today != today:
            self.today = today
            self.daily_pnl = 0.0
        
        # Calculate today's P&L from closed trades
        start_of_day = datetime.combine(today, datetime.min.time())
        deals = mt5.history_deals_get(start_of_day, datetime.now())
        if deals:
            today_pnl = sum(d.profit + d.swap + d.commission for d in deals)
            self.daily_pnl = today_pnl
        
        balance = info.balance
        daily_loss_pct = (self.daily_pnl / balance * 100) if balance > 0 else 0
        
        if daily_loss_pct <= -self.cfg.max_daily_loss_pct:
            logger.warning(f"Daily loss limit hit: {daily_loss_pct:.2f}%")
            return False
        
        # Check spread
        spread = self.get_spread_points()
        if spread > self.cfg.max_spread_points:
            logger.warning(f"Spread too wide: {spread}pts (max {self.cfg.max_spread_points})")
            return False
        
        return True
    
    def calculate_lot_size(self) -> float:
        """Dynamic lot sizing based on account equity."""
        info = mt5.account_info()
        if info is None or info.equity <= 0:
            return 0.0
        
        # Conservative: 0.01 lot per $1000 equity, rounded to 2 decimals
        lots = round((info.equity / 1000.0) * self.cfg.base_lot_size, 2)
        
        # Enforce broker limits
        sym = mt5.symbol_info(self.cfg.symbol)
        if sym:
            lots = max(sym.volume_min, min(lots, sym.volume_max))
            lots = round(lots / sym.volume_step) * sym.volume_step
        
        return lots
    
    def send_order(self, order_type: str, volume: float) -> Tuple[bool, Optional[int]]:
        """Send market order."""
        sym_info = mt5.symbol_info(self.cfg.symbol)
        if sym_info is None:
            return False, None
        
        price = sym_info.ask if order_type == "buy" else sym_info.bid
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.cfg.symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY if order_type == "buy" else mt5.ORDER_TYPE_SELL,
            "price": price,
            "slippage": self.cfg.slippage_points,
            "magic": self.cfg.magic_number,
            "comment": f"mom{self.cfg.mom_lookback}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        if result is None:
            logger.error(f"Order send failed: {mt5.last_error()}")
            return False, None
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Order failed: {result.retcode} - {result.comment}")
            return False, None
        
        logger.info(f"Order executed: {order_type} {volume} lots @ {price} | Ticket: {result.order}")
        return True, result.order
    
    def close_position(self, position: Dict) -> bool:
        """Close existing position."""
        order_type = "sell" if position["type"] == "buy" else "buy"
        sym_info = mt5.symbol_info(self.cfg.symbol)
        price = sym_info.bid if order_type == "sell" else sym_info.ask
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.cfg.symbol,
            "volume": position["volume"],
            "type": mt5.ORDER_TYPE_SELL if order_type == "sell" else mt5.ORDER_TYPE_BUY,
            "position": position["ticket"],
            "price": price,
            "slippage": self.cfg.slippage_points,
            "magic": self.cfg.magic_number,
            "comment": "close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Close failed: {result.retcode if result else 'None'} - {result.comment if result else ''}")
            return False
        
        logger.info(f"Position closed: {position['type']} {position['volume']} lots @ {price}")
        return True
    
    def run_once(self) -> Optional[int]:
        """Execute one trading cycle. Returns signal or None."""
        if not self.check_risk_limits():
            return None
        
        df = self.get_recent_bars(n_bars=self.cfg.mom_lookback + 5)
        if df is None or len(df) < self.cfg.mom_lookback:
            logger.error("Insufficient bars")
            return None
        
        signal = self.calculate_signal(df)
        position = self.get_position()
        
        lot_size = self.calculate_lot_size()
        if lot_size <= 0:
            logger.warning("Lot size is zero, skipping trade")
            return None
        
        if position is None:
            # No position — enter if signal is non-zero
            if signal != 0:
                order_type = "buy" if signal == 1 else "sell"
                success, ticket = self.send_order(order_type, lot_size)
                if success:
                    self.last_signal = signal
                    self.last_trade_time = datetime.now()
        else:
            # Have position — check if we need to flip or exit
            current_direction = 1 if position["type"] == "buy" else -1
            
            if signal == 0 or signal != current_direction:
                # Close current position
                self.close_position(position)
                self.last_signal = None
                
                # Re-enter if signal is opposite direction
                if signal != 0:
                    order_type = "buy" if signal == 1 else "sell"
                    success, ticket = self.send_order(order_type, lot_size)
                    if success:
                        self.last_signal = signal
                        self.last_trade_time = datetime.now()
            else:
                # Hold position
                logger.info(f"Holding {position['type']} position | Lots: {position['volume']} | P&L: {position['profit']:.2f}")
                self.last_signal = current_direction
        
        return signal
    
    def run_loop(self, interval_seconds: int = 60):
        """Run continuous trading loop."""
        logger.info(f"Starting trading loop for {self.cfg.symbol} | Interval: {interval_seconds}s")
        
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.exception(f"Error in trading cycle: {e}")
            
            time.sleep(interval_seconds)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    
    cfg = ExecutionConfig()
    executor = MT5Executor(cfg)
    
    if not executor.connect():
        sys.exit(1)
    
    try:
        # Run once immediately, then loop
        executor.run_once()
        executor.run_loop(interval_seconds=300)  # Check every 5 minutes
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        executor.disconnect()


if __name__ == "__main__":
    main()
