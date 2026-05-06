"""
Strategy base class and example implementations.
"""
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np
import pandas as pd


class Strategy(ABC):
    """
    Abstract base class for trading strategies.
    
    Subclasses must implement generate_signals() which returns a Series
    of position targets: -1 (short), 0 (flat), 1 (long).
    """
    
    def __init__(self, name: str = "unnamed"):
        self.name = name
    
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        Generate trading signals from price data.
        
        Args:
            data: DataFrame with OHLCV columns, indexed by time
        
        Returns:
            Series of integers: -1, 0, 1 aligned with data index
        """
        pass
    
    def add_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Optional: Add technical indicators to data.
        Called before generate_signals.
        """
        return data
    
    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.name})"


class BuyAndHold(Strategy):
    """Baseline strategy: always long from the first bar."""
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=data.index)


class SMAStrategy(Strategy):
    """
    Simple Moving Average crossover strategy.
    Long when fast SMA > slow SMA, short when fast < slow.
    """
    
    def __init__(self, fast: int = 20, slow: int = 50, name: str = "SMA_XO"):
        super().__init__(name)
        self.fast = fast
        self.slow = slow
    
    def add_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        data = data.copy()
        data[f"sma_{self.fast}"] = data["close"].rolling(self.fast).mean()
        data[f"sma_{self.slow}"] = data["close"].rolling(self.slow).mean()
        return data
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        data = self.add_indicators(data)
        fast_col = f"sma_{self.fast}"
        slow_col = f"sma_{self.slow}"
        
        signals = pd.Series(0, index=data.index)
        signals[data[fast_col] > data[slow_col]] = 1
        signals[data[fast_col] < data[slow_col]] = -1
        return signals


class RSIStrategy(Strategy):
    """
    RSI mean-reversion strategy.
    Long when RSI < oversold, short when RSI > overbought.
    """
    
    def __init__(
        self,
        period: int = 14,
        oversold: float = 30,
        overbought: float = 70,
        name: str = "RSI_MR"
    ):
        super().__init__(name)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
    
    def add_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        data = data.copy()
        delta = data["close"].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(self.period).mean()
        avg_loss = loss.rolling(self.period).mean()
        
        rs = avg_gain / avg_loss
        data["rsi"] = 100 - (100 / (1 + rs))
        return data
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        data = self.add_indicators(data)
        signals = pd.Series(0, index=data.index)
        signals[data["rsi"] < self.oversold] = 1
        signals[data["rsi"] > self.overbought] = -1
        return signals


class MACDStrategy(Strategy):
    """
    MACD trend-following strategy.
    Long when MACD line > Signal line, short otherwise.
    """
    
    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        name: str = "MACD"
    ):
        super().__init__(name)
        self.fast = fast
        self.slow = slow
        self.signal = signal
    
    def add_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        data = data.copy()
        ema_fast = data["close"].ewm(span=self.fast, adjust=False).mean()
        ema_slow = data["close"].ewm(span=self.slow, adjust=False).mean()
        data["macd"] = ema_fast - ema_slow
        data["macd_signal"] = data["macd"].ewm(span=self.signal, adjust=False).mean()
        return data
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        data = self.add_indicators(data)
        signals = pd.Series(0, index=data.index)
        signals[data["macd"] > data["macd_signal"]] = 1
        signals[data["macd"] < data["macd_signal"]] = -1
        return signals


class BollingerStrategy(Strategy):
    """
    Bollinger Bands mean-reversion strategy.
    Long when price touches lower band, short when price touches upper band.
    """
    
    def __init__(
        self,
        period: int = 20,
        std_dev: float = 2.0,
        name: str = "BB_MR"
    ):
        super().__init__(name)
        self.period = period
        self.std_dev = std_dev
    
    def add_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        data = data.copy()
        data["bb_mid"] = data["close"].rolling(self.period).mean()
        data["bb_std"] = data["close"].rolling(self.period).std()
        data["bb_upper"] = data["bb_mid"] + self.std_dev * data["bb_std"]
        data["bb_lower"] = data["bb_mid"] - self.std_dev * data["bb_std"]
        return data
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        data = self.add_indicators(data)
        signals = pd.Series(0, index=data.index)
        signals[data["close"] < data["bb_lower"]] = 1
        signals[data["close"] > data["bb_upper"]] = -1
        return signals
