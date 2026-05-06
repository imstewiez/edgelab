"""MetaTrader 5 adapter for live data and execution.

Wraps the MetaTrader5 Python module to provide:
- Historical bar data (H1, H4) formatted as DataFrames
- Current tick prices
- Symbol info (spread, min lot, etc.)
- Order execution (for future live trading)
"""
import pandas as pd
import numpy as np
from typing import Optional, Tuple
from datetime import datetime, timedelta


class MT5Adapter:
    """Adapter for MetaTrader 5 terminal integration.
    
    Usage:
        mt5 = MT5Adapter()
        mt5.connect()
        h1, h4 = mt5.get_data("XAUUSD", h1_bars=500, h4_bars=200)
        tick = mt5.get_tick("XAUUSD")
        mt5.disconnect()
    """
    
    def __init__(self):
        self._connected = False
        self._mt5 = None
    
    def connect(self, path: Optional[str] = None) -> bool:
        """Initialize connection to MT5 terminal.
        
        Args:
            path: Optional path to terminal64.exe. Auto-detected if None.
        
        Returns:
            True if connected successfully.
        """
        try:
            import MetaTrader5 as mt5
            self._mt5 = mt5
        except ImportError:
            raise ImportError("MetaTrader5 Python module not installed. "
                            "Install with: pip install MetaTrader5")
        
        kwargs = {}
        if path:
            kwargs["path"] = path
        
        if not self._mt5.initialize(**kwargs):
            error = self._mt5.last_error()
            raise ConnectionError(f"MT5 initialization failed: {error}")
        
        self._connected = True
        return True
    
    def disconnect(self):
        """Shutdown MT5 connection."""
        if self._connected and self._mt5:
            self._mt5.shutdown()
            self._connected = False
            self._mt5 = None
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    def get_account_info(self) -> dict:
        """Return account info as dict."""
        if not self._connected:
            raise RuntimeError("Not connected to MT5")
        
        info = self._mt5.account_info()
        if info is None:
            raise RuntimeError(f"Failed to get account info: {self._mt5.last_error()}")
        
        return {
            "login": info.login,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "leverage": info.leverage,
            "currency": info.currency,
            "name": info.name,
        }
    
    def get_data(self, symbol: str, h1_bars: int = 500, h4_bars: int = 200) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Pull historical H1 and H4 bars from MT5.
        
        Args:
            symbol: Trading symbol (e.g., "XAUUSD")
            h1_bars: Number of H1 bars to fetch
            h4_bars: Number of H4 bars to fetch
        
        Returns:
            (h1_df, h4_df) formatted identically to offline parquet data
        """
        if not self._connected:
            raise RuntimeError("Not connected to MT5")
        
        # Pull H1 bars
        h1_rates = self._mt5.copy_rates_from_pos(symbol, self._mt5.TIMEFRAME_H1, 0, h1_bars)
        if h1_rates is None or len(h1_rates) == 0:
            raise RuntimeError(f"Failed to get H1 bars for {symbol}: {self._mt5.last_error()}")
        
        h1 = pd.DataFrame(h1_rates)
        h1['time'] = pd.to_datetime(h1['time'], unit='s')
        h1.set_index('time', inplace=True)
        h1 = h1[['open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume']]
        
        # Pull H4 bars
        h4_rates = self._mt5.copy_rates_from_pos(symbol, self._mt5.TIMEFRAME_H4, 0, h4_bars)
        if h4_rates is None or len(h4_rates) == 0:
            raise RuntimeError(f"Failed to get H4 bars for {symbol}: {self._mt5.last_error()}")
        
        h4 = pd.DataFrame(h4_rates)
        h4['time'] = pd.to_datetime(h4['time'], unit='s')
        h4.set_index('time', inplace=True)
        h4 = h4[['open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume']]
        
        return h1, h4
    
    def get_tick(self, symbol: str) -> dict:
        """Get current tick for symbol.
        
        Returns:
            Dict with bid, ask, spread, time
        """
        if not self._connected:
            raise RuntimeError("Not connected to MT5")
        
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"Failed to get tick for {symbol}: {self._mt5.last_error()}")
        
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "spread": tick.ask - tick.bid,
            "time": pd.to_datetime(tick.time, unit='s'),
            "last": tick.last,
            "volume": tick.volume,
        }
    
    def get_symbol_info(self, symbol: str) -> dict:
        """Get symbol specifications.
        
        Returns:
            Dict with min lot, lot step, max lot, contract size, etc.
        """
        if not self._connected:
            raise RuntimeError("Not connected to MT5")
        
        info = self._mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Failed to get symbol info for {symbol}: {self._mt5.last_error()}")
        
        return {
            "name": info.name,
            "point": info.point,
            "trade_tick_size": info.trade_tick_size,
            "trade_contract_size": info.trade_contract_size,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "spread": info.spread,
            "trade_stops_level": info.trade_stops_level,
            "digits": info.digits,
        }
    
    def check_connection(self) -> bool:
        """Quick health check. Returns True if terminal is responsive."""
        if not self._connected or self._mt5 is None:
            return False
        try:
            info = self._mt5.terminal_info()
            return info is not None and info.connected
        except Exception:
            return False
