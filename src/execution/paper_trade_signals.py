"""
Paper Trading Signal Generator for MultiTF v1.0.0
Connects to MT5 demo/live, generates signals, logs everything.
Run this script every hour to check for signal changes.
"""
import sys, os, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict
import time

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    print("WARNING: MetaTrader5 module not installed. Running in offline mode.")

# ============================================================
# FROZEN MULTITF v1.0.0
# ============================================================
class MultiTF_v1:
    VERSION = "1.0.0"
    
    @staticmethod
    def generate_signals(df: pd.DataFrame) -> pd.Series:
        h1_mom = df["close"].pct_change(100)
        h4_close = df["close"].resample("4h").last().dropna()
        h4_mom = h4_close.pct_change(50)
        h4_mom_h1 = h4_mom.reindex(df.index, method="ffill")
        long = (h1_mom > 0) & (h4_mom_h1 > 0)
        short = (h1_mom < 0) & (h4_mom_h1 < 0)
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=df.index)

# ============================================================
# MT5 CONNECTION
# ============================================================
class MT5PaperTrader:
    def __init__(self, symbol="XAUUSD.s", timeframe=mt5.TIMEFRAME_H1 if MT5_AVAILABLE else None,
                 lookback_bars=5000, demo_mode=True):
        self.symbol = symbol
        self.timeframe = timeframe
        self.lookback_bars = lookback_bars
        self.demo_mode = demo_mode
        self.connected = False
        
    def connect(self) -> bool:
        if not MT5_AVAILABLE:
            print("MT5 not available. Cannot connect.")
            return False
        
        if not mt5.initialize():
            print("MT5 initialize failed, error code:", mt5.last_error())
            return False
        
        account_info = mt5.account_info()
        if account_info is None:
            print("Failed to get account info")
            return False
        
        self.connected = True
        print("Connected to MT5")
        print("  Account: %s" % account_info.login)
        print("  Server: %s" % account_info.server)
        print("  Balance: %.2f %s" % (account_info.balance, account_info.currency))
        print("  Equity: %.2f" % account_info.equity)
        print("  Demo: %s" % ("YES" if account_info.trade_mode == 4 else "NO"))
        
        if not self.demo_mode and account_info.trade_mode == 4:
            print("WARNING: Expected live account but connected to DEMO!")
        
        return True
    
    def disconnect(self):
        if MT5_AVAILABLE and self.connected:
            mt5.shutdown()
            self.connected = False
            print("Disconnected from MT5")
    
    def fetch_bars(self) -> Optional[pd.DataFrame]:
        if not MT5_AVAILABLE or not self.connected:
            return None
        
        rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, self.lookback_bars)
        if rates is None or len(rates) == 0:
            print("Failed to fetch bars for %s" % self.symbol)
            return None
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        return df
    
    def get_current_signal(self, df: pd.DataFrame) -> int:
        signals = MultiTF_v1.generate_signals(df)
        return int(signals.iloc[-1])
    
    def get_current_price(self) -> Optional[Dict]:
        if not MT5_AVAILABLE or not self.connected:
            return None
        
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return None
        
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "spread": (tick.ask - tick.bid) / 0.01,  # points for XAUUSD
            "time": pd.to_datetime(tick.time, unit='s'),
        }
    
    def get_symbol_info(self) -> Optional[Dict]:
        if not MT5_AVAILABLE or not self.connected:
            return None
        
        info = mt5.symbol_info(self.symbol)
        if info is None:
            return None
        
        return {
            "point": info.point,
            "digits": info.digits,
            "spread": info.spread,
            "trade_stops_level": info.trade_stops_level,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
        }
    
    def get_open_positions(self) -> list:
        if not MT5_AVAILABLE or not self.connected:
            return []
        
        positions = mt5.positions_get(symbol=self.symbol)
        if positions is None:
            return []
        
        return [{
            "ticket": p.ticket,
            "type": "BUY" if p.type == 0 else "SELL",
            "volume": p.volume,
            "open_price": p.price_open,
            "current_price": p.price_current,
            "profit": p.profit,
            "swap": p.swap,
        } for p in positions]

# ============================================================
# LOGGING
# ============================================================
class SignalLogger:
    def __init__(self, log_dir="logs/paper_trading"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self.log_file = os.path.join(log_dir, "signals_%s.csv" % datetime.now().strftime("%Y%m%d"))
        
    def log(self, data: dict):
        df = pd.DataFrame([data])
        if os.path.exists(self.log_file):
            df.to_csv(self.log_file, mode='a', header=False, index=False)
        else:
            df.to_csv(self.log_file, index=False)
    
    def print_summary(self, history_file: str):
        if not os.path.exists(history_file):
            return
        
        df = pd.read_csv(history_file)
        if len(df) == 0:
            return
        
        print("\n--- Paper Trading Summary ---")
        print("Total checks: %d" % len(df))
        print("Signal changes: %d" % (df['signal_changed'].sum() if 'signal_changed' in df.columns else 0))
        
        if 'signal' in df.columns:
            print("Current signal: %s" % df['signal'].iloc[-1])
        
        if 'spread' in df.columns:
            print("Avg spread: %.1f points" % df['spread'].mean())
            print("Max spread: %.1f points" % df['spread'].max())

# ============================================================
# MAIN
# ============================================================
def run_signal_check():
    print("=" * 70)
    print("MultiTF v1.0.0 Paper Trading Signal Check")
    print("=" * 70)
    print("Time: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()
    
    trader = MT5PaperTrader(symbol="XAUUSD.s", demo_mode=True)
    logger = SignalLogger()
    
    # Connect to MT5
    if not trader.connect():
        print("\nCannot connect to MT5. Make sure MT5 is running.")
        print("If MT5 is not installed, you can still use this for offline analysis.")
        return
    
    try:
        # Get symbol info
        info = trader.get_symbol_info()
        if info:
            print("Symbol Info (XAUUSD.s):")
            print("  Point value: %.5f" % info["point"])
            print("  Digits: %d" % info["digits"])
            print("  Min volume: %.2f" % info["volume_min"])
            print("  Volume step: %.2f" % info["volume_step"])
            print()
        
        # Fetch bars
        df = trader.fetch_bars()
        if df is None or len(df) < 200:
            print("ERROR: Not enough bars fetched. Need 200+, got %d" % (len(df) if df is not None else 0))
            return
        
        print("Fetched %d H1 bars (from %s to %s)" % (len(df), df.index[0], df.index[-1]))
        
        # Generate signal
        signals = MultiTF_v1.generate_signals(df)
        current_signal = signals.iloc[-1]
        previous_signal = signals.iloc[-2] if len(signals) > 1 else 0
        
        signal_names = {1: "LONG", -1: "SHORT", 0: "FLAT"}
        print("\nSIGNAL:")
        print("  Current:    %s" % signal_names.get(current_signal, "UNKNOWN"))
        print("  Previous:   %s" % signal_names.get(previous_signal, "UNKNOWN"))
        print("  Changed:    %s" % ("YES - ACTION REQUIRED" if current_signal != previous_signal else "NO - HOLD POSITION"))
        
        # Get current price
        price = trader.get_current_price()
        if price:
            print("\nCURRENT PRICE:")
            print("  Bid:        %.2f" % price["bid"])
            print("  Ask:        %.2f" % price["ask"])
            print("  Spread:     %.1f points" % price["spread"])
            print("  Time:       %s" % price["time"])
        
        # Check open positions
        positions = trader.get_open_positions()
        print("\nOPEN POSITIONS:")
        if positions:
            for p in positions:
                print("  %s %.2f lots @ %.2f (P&L: %.2f)" % (
                    p["type"], p["volume"], p["open_price"], p["profit"]))
        else:
            print("  None")
        
        # Recommendation
        print("\nACTION:")
        if current_signal != previous_signal:
            if current_signal == 1:
                if positions and any(p["type"] == "SELL" for p in positions):
                    print("  CLOSE SHORT position(s), then OPEN LONG 0.01 lots")
                else:
                    print("  OPEN LONG 0.01 lots")
            elif current_signal == -1:
                if positions and any(p["type"] == "BUY" for p in positions):
                    print("  CLOSE LONG position(s), then OPEN SHORT 0.01 lots")
                else:
                    print("  OPEN SHORT 0.01 lots")
            else:
                if positions:
                    print("  CLOSE ALL POSITIONS (go flat)")
                else:
                    print("  STAY FLAT (no action)")
        else:
            if positions:
                print("  HOLD current position(s)")
            else:
                print("  STAY FLAT")
        
        # Risk check
        print("\nRISK CHECK:")
        account = mt5.account_info() if MT5_AVAILABLE else None
        if account:
            dd_pct = (account.equity - account.balance) / account.balance * 100 if account.balance > 0 else 0
            print("  Balance:    %.2f" % account.balance)
            print("  Equity:     %.2f" % account.equity)
            print("  Drawdown:   %.2f%%" % dd_pct)
            if abs(dd_pct) > 15:
                print("  *** CIRCUIT BREAKER TRIGGERED - STOP TRADING ***")
            elif abs(dd_pct) > 10:
                print("  WARNING: Approaching max drawdown limit")
            else:
                print("  OK: Within risk limits")
        
        # Log
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "bar_time": df.index[-1].isoformat(),
            "signal": signal_names.get(current_signal, "UNKNOWN"),
            "previous_signal": signal_names.get(previous_signal, "UNKNOWN"),
            "signal_changed": current_signal != previous_signal,
            "bid": price["bid"] if price else None,
            "ask": price["ask"] if price else None,
            "spread": price["spread"] if price else None,
            "num_positions": len(positions),
        }
        logger.log(log_entry)
        print("\nLogged to: %s" % logger.log_file)
        
    finally:
        trader.disconnect()
    
    print("\n" + "=" * 70)
    print("Next check: At the start of the next hour (H1 close)")
    print("=" * 70)

# ============================================================
# OFFLINE MODE - For when MT5 is not running
# ============================================================
def run_offline_analysis(data_path="data/raw/XAUUSD_H1.parquet"):
    print("=" * 70)
    print("MultiTF v1.0.0 Offline Signal Analysis")
    print("=" * 70)
    
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    path = os.path.join(base, data_path)
    
    if not os.path.exists(path):
        print("Data file not found: %s" % path)
        return
    
    df = pd.read_parquet(path)
    if "time" in df.columns:
        df.set_index("time", inplace=True)
    
    signals = MultiTF_v1.generate_signals(df)
    
    print("Loaded %d bars" % len(df))
    print("Latest bar: %s" % df.index[-1])
    print()
    
    # Show last 24 hours of signals
    recent = signals.tail(24)
    print("Last 24 hours of signals:")
    for t, s in recent.items():
        name = {1: "LONG", -1: "SHORT", 0: "FLAT"}.get(s, "?")
        print("  %s: %s" % (t.strftime("%Y-%m-%d %H:%M"), name))
    
    current = signals.iloc[-1]
    prev = signals.iloc[-2]
    print("\nCURRENT SIGNAL: %s" % {1: "LONG", -1: "SHORT", 0: "FLAT"}.get(current, "?"))
    print("CHANGED: %s" % ("YES" if current != prev else "NO"))

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="Run offline analysis without MT5")
    args = parser.parse_args()
    
    if args.offline or not MT5_AVAILABLE:
        run_offline_analysis()
    else:
        run_signal_check()
