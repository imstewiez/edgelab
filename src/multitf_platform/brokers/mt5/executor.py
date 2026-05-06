"""Real MT5 order execution via MetaTrader5 Python API.

Places market orders and tracks positions.
"""
import numpy as np
import pandas as pd
from typing import Optional, Dict
from enum import Enum


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class MT5Executor:
    """Executes real trades in MT5.
    
    Handles:
    - Opening positions (market orders)
    - Closing positions
    - Flipping direction (close + open)
    - Position sizing based on allocated equity
    """
    
    def __init__(self, mt5_module):
        self.mt5 = mt5_module
    
    def get_position(self, symbol: str) -> Optional[dict]:
        """Check if we have an open position for symbol."""
        positions = self.mt5.positions_get(symbol=symbol)
        if positions and len(positions) > 0:
            p = positions[0]
            return {
                "ticket": p.ticket,
                "type": p.type,  # 0=Buy, 1=Sell
                "volume": p.volume,
                "price_open": p.price_open,
                "price_current": p.price_current,
                "profit": p.profit,
                "swap": p.swap,
                "symbol": p.symbol,
            }
        return None
    
    def _get_filling_mode(self, symbol: str) -> int:
        """Get supported filling mode for symbol."""
        info = self.mt5.symbol_info(symbol)
        if info is None:
            return self.mt5.ORDER_FILLING_IOC
        
        mode = info.filling_mode
        
        # Try RETURN first (most compatible with ECN/STP brokers)
        if hasattr(self.mt5, 'ORDER_FILLING_RETURN') and (mode & 0x00000002):
            return self.mt5.ORDER_FILLING_RETURN
        if mode & 0x00000001:
            return self.mt5.ORDER_FILLING_FOK
        if mode & 0x00000002:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_FOK
    
    def close_position(self, symbol: str) -> dict:
        """Close all positions for symbol."""
        pos = self.get_position(symbol)
        if not pos:
            return {"success": True, "message": "No position to close"}
        
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"success": False, "error": f"Cannot get tick for {symbol}"}
        
        # Determine close price based on position type
        if pos["type"] == 0:  # Buy position -> close at bid
            price = tick.bid
            order_type = self.mt5.ORDER_TYPE_SELL
        else:  # Sell position -> close at ask
            price = tick.ask
            order_type = self.mt5.ORDER_TYPE_BUY
        
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos["volume"],
            "type": order_type,
            "price": price,
            "deviation": 10,
            "magic": 234000,
            "comment": "MultiTF close",
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
            "position": pos["ticket"],
        }
        
        result = self.mt5.order_send(request)
        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            return {"success": False, "error": f"Close failed: {result.retcode} {result.comment}"}
        
        return {
            "success": True,
            "ticket": getattr(result, 'order', 0),
            "price": getattr(result, 'price', 0.0),
            "volume": getattr(result, 'volume', pos["volume"]),
            "profit": pos["profit"],
        }
    
    def _calculate_sl_tp(self, symbol: str, direction: int, entry_price: float, h4_bars: pd.DataFrame = None) -> tuple:
        """Calculate stop loss and take profit based on recent H4 structure.
        
        Uses recent H4 swing low/high for SL, 2:1 R/R for TP.
        Falls back to ATR-based if no H4 data.
        """
        tick = self.mt5.symbol_info_tick(symbol)
        point = self.mt5.symbol_info(symbol).point
        
        if h4_bars is not None and len(h4_bars) >= 5:
            recent = h4_bars.tail(5)
            if direction == 1:  # LONG
                sl = recent["low"].min()
                risk = entry_price - sl
                tp = entry_price + risk * 2.0
            else:  # SHORT
                sl = recent["high"].max()
                risk = sl - entry_price
                tp = entry_price - risk * 2.0
        else:
            # Fallback: 50 pips/points SL based on asset type
            if "XAU" in symbol or "NAS" in symbol or "GER" in symbol or "US30" in symbol:
                sl_distance = 50.0 * point  # 50 points for indices/metals
            else:
                sl_distance = 0.0050  # 50 pips for FX
            
            if direction == 1:
                sl = entry_price - sl_distance
                tp = entry_price + sl_distance * 2.0
            else:
                sl = entry_price + sl_distance
                tp = entry_price - sl_distance * 2.0
        
        # Ensure SL/TP are valid (minimum distance from price)
        min_distance = 10 * point
        if direction == 1:
            sl = min(sl, entry_price - min_distance)
            tp = max(tp, entry_price + min_distance)
        else:
            sl = max(sl, entry_price + min_distance)
            tp = min(tp, entry_price - min_distance)
        
        return sl, tp
    
    def open_position(self, symbol: str, direction: int, size_lots: float, h4_bars: pd.DataFrame = None) -> dict:
        """Open a market order with SL/TP.
        
        Args:
            symbol: MT5 symbol (e.g., "XAUUSD")
            direction: 1=LONG, -1=SHORT
            size_lots: Lot size (e.g., 0.01)
            h4_bars: Optional H4 DataFrame for structure-based SL/TP
        """
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"success": False, "error": f"Cannot get tick for {symbol}"}
        
        if direction == 1:
            order_type = self.mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = self.mt5.ORDER_TYPE_SELL
            price = tick.bid
        
        # Calculate SL/TP
        sl, tp = self._calculate_sl_tp(symbol, direction, price, h4_bars)
        
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": round(size_lots, 2),
            "type": order_type,
            "price": price,
            "sl": round(sl, self.mt5.symbol_info(symbol).digits),
            "tp": round(tp, self.mt5.symbol_info(symbol).digits),
            "deviation": 10,
            "magic": 234000,
            "comment": "MultiTF open",
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
        }
        
        result = self.mt5.order_send(request)
        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            return {"success": False, "error": f"Open failed: {result.retcode} {result.comment}"}
        
        return {
            "success": True,
            "ticket": getattr(result, 'order', 0),
            "price": getattr(result, 'price', price),
            "volume": getattr(result, 'volume', size_lots),
            "sl": sl,
            "tp": tp,
            "direction": direction,
        }
    
    def trail_stop(self, symbol: str) -> dict:
        """Trail stop loss on existing position to lock in profits.
        
        Logic:
        - If profit > 1x risk distance -> move SL to breakeven
        - If profit > 1.5x risk distance -> trail SL at 50% of profit
        """
        pos = self.get_position(symbol)
        if not pos:
            return {"success": True, "message": "No position to trail"}
        
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"success": False, "error": "Cannot get tick"}
        
        entry = pos["price_open"]
        current_sl = self.mt5.positions_get(symbol=symbol)[0].sl
        
        # Calculate risk distance from original SL or estimate
        info = self.mt5.symbol_info(symbol)
        point = info.point if info else 0.00001
        
        if current_sl > 0:
            risk_distance = abs(entry - current_sl)
        else:
            # Fallback: 50 pips/points risk
            risk_distance = 50 * point if "XAU" not in symbol and "NAS" not in symbol else 500 * point
        
        direction = 1 if pos["type"] == 0 else -1
        current_price = tick.ask if direction == 1 else tick.bid
        
        profit_distance = (current_price - entry) * direction
        
        if profit_distance <= 0:
            return {"success": True, "message": "Position not in profit"}
        
        new_sl = None
        
        # Breakeven: profit > 1x risk
        if profit_distance >= risk_distance and (current_sl == 0 or abs(entry - current_sl) > point * 2):
            new_sl = entry
            reason = "breakeven"
        
        # Trail: profit > 1.5x risk -> lock in 50% of profit
        if profit_distance >= risk_distance * 1.5:
            trail_target = entry + (profit_distance * 0.5) * direction
            if new_sl is None or abs(trail_target - entry) > abs(new_sl - entry):
                new_sl = trail_target
                reason = "trail"
        
        if new_sl is None:
            return {"success": True, "message": "No trail adjustment needed"}
        
        # Ensure minimum distance from price
        min_dist = 10 * point
        if direction == 1 and new_sl > current_price - min_dist:
            new_sl = current_price - min_dist
        if direction == -1 and new_sl < current_price + min_dist:
            new_sl = current_price + min_dist
        
        # Round to symbol digits
        digits = info.digits if info else 5
        new_sl = round(new_sl, digits)
        
        request = {
            "action": self.mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": pos["ticket"],
            "sl": new_sl,
            "tp": self.mt5.positions_get(symbol=symbol)[0].tp,
        }
        
        result = self.mt5.order_send(request)
        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            return {"success": False, "error": f"Trail failed: {result.retcode} {result.comment}"}
        
        return {"success": True, "ticket": pos["ticket"], "new_sl": new_sl, "reason": reason, "profit_locked": abs(new_sl - entry) / risk_distance}
    
    def modify_position(self, symbol: str, sl: float, tp: float) -> dict:
        """Modify SL/TP on existing position."""
        pos = self.get_position(symbol)
        if not pos:
            return {"success": True, "message": "No position to modify"}
        
        request = {
            "action": self.mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": pos["ticket"],
            "sl": round(sl, self.mt5.symbol_info(symbol).digits),
            "tp": round(tp, self.mt5.symbol_info(symbol).digits),
        }
        
        result = self.mt5.order_send(request)
        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            return {"success": False, "error": f"Modify failed: {result.retcode} {result.comment}"}
        
        return {"success": True, "ticket": pos["ticket"], "sl": sl, "tp": tp}
    
    def execute(self, symbol: str, target_direction: int, size_lots: float, h4_bars: pd.DataFrame = None) -> dict:
        """Execute target position: close if needed, then open if needed.
        
        Args:
            symbol: MT5 symbol
            target_direction: 1=LONG, -1=SHORT, 0=FLAT
            size_lots: Desired lot size for new position
        """
        current = self.get_position(symbol)
        current_direction = 0
        if current:
            current_direction = 1 if current["type"] == 0 else -1
        
        # No change needed
        if target_direction == current_direction:
            if target_direction == 0:
                return {"success": True, "action": "none", "message": "Already flat"}
            return {"success": True, "action": "hold", "message": f"Holding {current_direction}"}
        
        results = []
        
        # Close existing if any
        if current_direction != 0:
            close_result = self.close_position(symbol)
            results.append({"action": "close", **close_result})
            if not close_result["success"]:
                return {"success": False, "results": results}
        
        # Open new if target is non-zero
        if target_direction != 0:
            open_result = self.open_position(symbol, target_direction, size_lots, h4_bars)
            results.append({"action": "open", **open_result})
            if not open_result["success"]:
                return {"success": False, "results": results}
        
        return {"success": True, "results": results}
    
    def calculate_lot_size(self, symbol: str, equity: float, scale: float = 1.0) -> float:
        """Calculate lot size based on allocated equity and scale.
        
        Uses MT5 symbol info for contract size and lot constraints.
        """
        info = self.mt5.symbol_info(symbol)
        if info is None:
            return 0.01
        
        min_lot = info.volume_min
        max_lot = info.volume_max
        lot_step = info.volume_step
        
        # Base: proportional to equity, 1.0 lot per $100k
        base = equity / 100000.0
        raw = base * scale
        
        # Round to lot step
        lots = round(raw / lot_step) * lot_step
        lots = max(min_lot, min(max_lot, lots))
        
        return lots
