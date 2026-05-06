"""Real MT5 order execution via MetaTrader5 Python API.

Places market orders and tracks positions.
Incorporates Kelly Criterion sizing, correlation risk checks, and regime adjustments.
"""
import numpy as np
import pandas as pd
from typing import Optional, Dict
from enum import Enum

from ...risk.v1_1.kelly import KellySizer
from ...risk.v1_1.correlation import CorrelationRiskChecker
from ...risk.v1_1.regime import RegimeDetector, MarketRegime
from ...risk.v1_1.slippage_monitor import SlippageMonitor
from ...risk.v1_1.mae_mfe_tracker import MAEMFETracker
from ...risk.v1_1.time_decay_exit import TimeDecayExit
from ...risk.v1_1.dynamic_leverage import DynamicLeverage
from ...risk.v1_1.weekend_filter import WeekendFilter


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
    - Kelly Criterion sizing
    - Correlation risk checks
    - Regime-based adjustments
    """
    
    def __init__(self, mt5_module, symbols: list = None):
        self.mt5 = mt5_module
        self.symbols = symbols or []
        self.kelly_sizer = KellySizer()
        self.correlation_checker = CorrelationRiskChecker()
        self.regime_detector = RegimeDetector()
        self.slippage_monitor = SlippageMonitor()
        self.mae_mfe = MAEMFETracker()
        self.time_decay = TimeDecayExit()
        self.dynamic_leverage = DynamicLeverage()
        self.weekend_filter = WeekendFilter()
    
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
        """Close ALL positions for symbol (handles partial TP splits)."""
        positions = self.mt5.positions_get(symbol=symbol)
        if not positions or len(positions) == 0:
            return {"success": True, "message": "No position to close"}
        
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"success": False, "error": f"Cannot get tick for {symbol}"}
        
        results = []
        total_profit = 0.0
        total_volume = 0.0
        
        for pos in positions:
            # Determine close price based on position type
            if pos.type == 0:  # Buy position -> close at bid
                price = tick.bid
                order_type = self.mt5.ORDER_TYPE_SELL
            else:  # Sell position -> close at ask
                price = tick.ask
                order_type = self.mt5.ORDER_TYPE_BUY
            
            request = {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": pos.volume,
                "type": order_type,
                "price": price,
                "deviation": 10,
                "magic": 234000,
                "comment": "MultiTF close",
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self._get_filling_mode(symbol),
                "position": pos.ticket,
            }
            
            result = self.mt5.order_send(request)
            if result.retcode != self.mt5.TRADE_RETCODE_DONE:
                results.append({"ticket": pos.ticket, "error": f"Close failed: {result.retcode} {result.comment}"})
                continue
            
            close_price = getattr(result, 'price', price)
            direction = 1 if pos.type == 0 else -1
            pnl = pos.profit + pos.swap
            total_profit += pnl
            total_volume += pos.volume
            
            # Record trade for MAE/MFE tracking
            self.mae_mfe.record_trade(
                symbol, direction, pos.price_open, close_price,
                sl=pos.sl if pos.sl > 0 else pos.price_open,
                tp=pos.tp if pos.tp > 0 else pos.price_open,
            )
            
            results.append({
                "ticket": pos.ticket,
                "price": close_price,
                "volume": pos.volume,
                "profit": pnl,
            })
        
        # Clear time decay tracking
        self.time_decay.record_exit(symbol)
        
        # Record combined P&L for expectancy filter
        if total_volume > 0:
            # We don't have per-trade expectancy here, but the wrapper handles it
            pass
        
        return {
            "success": len(results) > 0,
            "results": results,
            "total_profit": total_profit,
            "total_volume": total_volume,
            "positions_closed": len(results),
        }
    
    def _calculate_sl_tp(self, symbol: str, direction: int, entry_price: float,
                         h4_bars: pd.DataFrame = None,
                         sl_mult: float = 1.0, tp_mult: float = 2.0) -> tuple:
        """Calculate stop loss and take profit based on recent H4 structure.
        
        Uses recent H4 swing low/high for SL, adjustable R/R for TP.
        Falls back to ATR-based if no H4 data.
        
        Args:
            sl_mult: Multiplier for SL distance (regime-adjusted)
            tp_mult: Multiplier for TP distance (regime-adjusted)
        """
        info = self.mt5.symbol_info(symbol)
        point = info.point if info else 0.00001
        
        if h4_bars is not None and len(h4_bars) >= 5:
            recent = h4_bars.tail(5)
            if direction == 1:  # LONG
                sl = recent["low"].min()
                risk = entry_price - sl
                sl = entry_price - risk * sl_mult
                tp = entry_price + risk * tp_mult
            else:  # SHORT
                sl = recent["high"].max()
                risk = sl - entry_price
                sl = entry_price + risk * sl_mult
                tp = entry_price - risk * tp_mult
        else:
            # Fallback: 50 pips/points SL based on asset type
            if "XAU" in symbol or "NAS" in symbol or "GER" in symbol or "US30" in symbol:
                sl_distance = 50.0 * point  # 50 points for indices/metals
            else:
                sl_distance = 0.0050  # 50 pips for FX
            
            if direction == 1:
                sl = entry_price - sl_distance * sl_mult
                tp = entry_price + sl_distance * tp_mult
            else:
                sl = entry_price + sl_distance * sl_mult
                tp = entry_price - sl_distance * tp_mult
        
        # Ensure SL/TP are valid (minimum distance from price)
        min_distance = 10 * point
        if direction == 1:
            sl = min(sl, entry_price - min_distance)
            tp = max(tp, entry_price + min_distance)
        else:
            sl = max(sl, entry_price + min_distance)
            tp = min(tp, entry_price - min_distance)
        
        return sl, tp
    
    def open_position(self, symbol: str, direction: int, size_lots: float,
                      h4_bars: pd.DataFrame = None,
                      sl_mult: float = 1.0, tp_mult: float = 3.0,
                      comment: str = "MultiTF open",
                      sl: float = None, tp: float = None) -> dict:
        """Open a market order with SL/TP.
        
        Args:
            symbol: MT5 symbol (e.g., "XAUUSD")
            direction: 1=LONG, -1=SHORT
            size_lots: Lot size (e.g., 0.01)
            h4_bars: Optional H4 DataFrame for structure-based SL/TP
            sl_mult: SL distance multiplier (regime-adjusted)
            tp_mult: TP distance multiplier (regime-adjusted)
            comment: Order comment
            sl: Optional explicit SL price (overrides H4-based calc)
            tp: Optional explicit TP price (overrides H4-based calc)
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
        if sl is None or tp is None:
            calc_sl, calc_tp = self._calculate_sl_tp(symbol, direction, price, h4_bars, sl_mult, tp_mult)
            if sl is None:
                sl = calc_sl
            if tp is None:
                tp = calc_tp
        
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
            "comment": comment,
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
        }
        
        result = self.mt5.order_send(request)
        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            return {"success": False, "error": f"Open failed: {result.retcode} {result.comment}"}
        
        actual_price = getattr(result, 'price', price)
        actual_volume = getattr(result, 'volume', size_lots)
        
        # Record slippage
        slip = self.slippage_monitor.record_slippage(
            symbol, price, actual_price, direction
        )
        
        # Record entry for time decay tracking
        self.time_decay.record_entry(symbol, actual_price, sl)
        
        return {
            "success": True,
            "ticket": getattr(result, 'order', 0),
            "price": actual_price,
            "volume": actual_volume,
            "sl": sl,
            "tp": tp,
            "direction": direction,
            "slippage": slip["slippage"],
            "slippage_alert": slip["alert"],
        }
    
    def open_position_with_partial_tp(self, symbol: str, direction: int, size_lots: float,
                                      h4_bars: pd.DataFrame = None,
                                      regime: MarketRegime = None) -> dict:
        """Open two positions for partial take-profit strategy.
        
        Position 1 (50%): TP at 1R (quick profit, lock gains)
        Position 2 (50%): TP at regime-adjusted multiplier (trend capture)
        
        Returns combined result dict.
        """
        if size_lots < 0.02:
            # Too small to split, use single position
            return self.open_position(symbol, direction, size_lots, h4_bars,
                                      sl_mult=1.0, tp_mult=2.0)
        
        half = round(size_lots / 2, 2)
        info = self.mt5.symbol_info(symbol)
        min_lot = info.volume_min if info else 0.01
        if half < min_lot:
            half = min_lot
        
        # Get regime adjustments for TP multiplier
        adj = self.regime_detector.get_position_adjustments() if regime else \
              {"sl_mult": 1.0, "tp_mult": 2.0}
        tp_mult_2 = adj.get("tp_mult", 2.0)
        sl_mult = adj.get("sl_mult", 1.0)
        
        # Position 1: 50% size, TP at 1R
        result1 = self.open_position(symbol, direction, half, h4_bars,
                                     sl_mult=sl_mult, tp_mult=1.0,
                                     comment="MultiTF scalp")
        
        # Position 2: 50% size, TP at regime multiplier
        result2 = self.open_position(symbol, direction, half, h4_bars,
                                     sl_mult=sl_mult, tp_mult=tp_mult_2,
                                     comment="MultiTF swing")
        
        combined = {
            "success": result1["success"] or result2["success"],
            "partial_tp": True,
            "results": [result1, result2],
        }
        
        if result1["success"]:
            combined.update({
                "ticket": result1.get("ticket"),
                "price": result1.get("price"),
                "volume": result1.get("volume", 0) + result2.get("volume", 0),
                "sl": result1.get("sl"),
                "tp": result1.get("tp"),
                "direction": direction,
            })
        elif result2["success"]:
            combined.update({
                "ticket": result2.get("ticket"),
                "price": result2.get("price"),
                "volume": result2.get("volume", 0),
                "sl": result2.get("sl"),
                "tp": result2.get("tp"),
                "direction": direction,
            })
        
        return combined
    
    def calculate_position_risk(self, symbol: str, volume: float, sl_price: float,
                                entry_price: float = None) -> float:
        """Calculate dollar risk for a position.
        
        Uses MT5 symbol info for accurate contract sizing.
        """
        info = self.mt5.symbol_info(symbol)
        if info is None or sl_price <= 0:
            return 0.0
        
        if entry_price is None:
            # Try to get from open position
            pos = self.get_position(symbol)
            if pos:
                entry_price = pos["price_open"]
            else:
                tick = self.mt5.symbol_info_tick(symbol)
                entry_price = tick.ask if tick else 0
        
        if entry_price <= 0:
            return 0.0
        
        sl_distance = abs(entry_price - sl_price)
        
        # Use tick value for accurate dollar risk
        tick_size = info.trade_tick_size if info.trade_tick_size > 0 else info.point
        tick_value = info.trade_tick_value if info.trade_tick_value > 0 else info.point
        
        if tick_size > 0 and tick_value > 0:
            ticks_at_risk = sl_distance / tick_size
            risk = volume * ticks_at_risk * tick_value
        else:
            # Fallback: estimate based on symbol type
            if "XAU" in symbol:
                risk = volume * 100 * sl_distance  # 100 oz per lot
            elif "NAS" in symbol or "GER" in symbol or "US30" in symbol:
                risk = volume * sl_distance  # 1 contract per lot
            else:
                risk = volume * 100000 * sl_distance  # 100k units per lot
        
        return risk
    
    def get_portfolio_heat(self, equity: float) -> dict:
        """Calculate total portfolio heat (open risk) as % of equity.
        
        Returns dict with heat_pct and per-position breakdown.
        """
        positions = self.mt5.positions_get()
        total_risk = 0.0
        breakdown = {}
        
        for p in positions:
            risk = self.calculate_position_risk(p.symbol, p.volume, p.sl, p.price_open)
            total_risk += risk
            breakdown[p.symbol] = {
                "volume": p.volume,
                "risk": risk,
                "risk_pct": (risk / equity * 100) if equity > 0 else 0,
            }
        
        heat_pct = (total_risk / equity * 100) if equity > 0 else 0
        
        return {
            "heat_pct": heat_pct,
            "total_risk": total_risk,
            "breakdown": breakdown,
            "max_allowed_pct": 5.0,
        }
    
    def check_portfolio_heat(self, symbol: str, proposed_volume: float,
                             proposed_sl: float, equity: float,
                             max_heat_pct: float = 5.0) -> tuple[bool, float, str]:
        """Check if adding a new position would exceed portfolio heat cap.
        
        Returns:
            (allow: bool, scale: float, reason: str)
        """
        current_heat = self.get_portfolio_heat(equity)
        current_pct = current_heat["heat_pct"]
        
        if current_pct >= max_heat_pct:
            return False, 0.0, f"Portfolio heat {current_pct:.1f}% >= cap {max_heat_pct:.1f}%"
        
        # Calculate proposed trade risk
        tick = self.mt5.symbol_info_tick(symbol)
        entry = tick.ask if tick else 0
        proposed_risk = self.calculate_position_risk(symbol, proposed_volume, proposed_sl, entry)
        proposed_pct = (proposed_risk / equity * 100) if equity > 0 else 0
        
        new_total = current_pct + proposed_pct
        
        if new_total <= max_heat_pct:
            return True, 1.0, f"Heat {current_pct:.1f}% + {proposed_pct:.1f}% = {new_total:.1f}% <= {max_heat_pct:.1f}%"
        
        # Scale down to fit within cap
        available_pct = max_heat_pct - current_pct
        if available_pct <= 0:
            return False, 0.0, f"No heat available (current {current_pct:.1f}%)"
        
        scale = available_pct / proposed_pct if proposed_pct > 0 else 0.0
        scale = max(0.0, min(1.0, scale))
        
        return True, scale, f"Heat cap: scaled {scale:.0%} (current {current_pct:.1f}%)"
    
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
    
    def execute(self, symbol: str, target_direction: int, size_lots: float,
                h4_bars: pd.DataFrame = None, h1_bars: pd.DataFrame = None,
                equity: float = 10300.0, scale: float = 1.0) -> dict:
        """Execute target position: close if needed, then open if needed.
        
        Incorporates Kelly sizing, correlation checks, and regime adjustments.
        
        Args:
            symbol: MT5 symbol
            target_direction: 1=LONG, -1=SHORT, 0=FLAT
            size_lots: Desired lot size for new position (fallback)
            h4_bars: H4 bars for SL/TP calculation
            h1_bars: H1 bars for regime/correlation checks
            equity: Current account equity
            scale: Portfolio allocation scale
        """
        results = []
        current = self.get_position(symbol)
        current_direction = 0
        if current:
            current_direction = 1 if current["type"] == 0 else -1
        
        # Check time decay on existing positions
        if current_direction != 0 and current:
            tick = self.mt5.symbol_info_tick(symbol)
            if tick:
                current_price = tick.ask if current_direction == 1 else tick.bid
                td_exit, td_reason = self.time_decay.check_exit(symbol, current_price)
                if td_exit:
                    results.append({"action": "time_decay", "reason": td_reason})
                    close_result = self.close_position(symbol)
                    results.append({"action": "close", **close_result})
                    return {"success": True, "action": "time_decay", "results": results}
        
        # Check weekend gap risk — close positions before weekend
        if current_direction != 0:
            wc_close, wc_reason = self.weekend_filter.should_close_positions()
            if wc_close:
                results.append({"action": "weekend_close", "reason": wc_reason})
                close_result = self.close_position(symbol)
                results.append({"action": "close", **close_result})
                return {"success": True, "action": "weekend_close", "results": results}
        
        # No change needed
        if target_direction == current_direction:
            if target_direction == 0:
                return {"success": True, "action": "none", "message": "Already flat"}
            return {"success": True, "action": "hold", "message": f"Holding {current_direction}"}
        
        # Close existing if any
        if current_direction != 0:
            # Record trade result for Kelly before closing
            if current:
                self.add_trade_result(current.get("profit", 0.0))
            close_result = self.close_position(symbol)
            results.append({"action": "close", **close_result})
            if not close_result["success"]:
                return {"success": False, "results": results}
        
        # Open new if target is non-zero
        if target_direction != 0:
            # Get Kelly fraction
            kelly_frac = self.get_kelly_fraction()
            
            # Get regime
            regime = None
            if h1_bars is not None:
                regime = self.regime_detector.detect(h1_bars)
            
            # Update correlation prices
            if h1_bars is not None:
                self.update_correlation_prices(h1_bars, symbol)
            
            # Check correlation/portfolio risk
            portfolio_positions = self.get_portfolio_positions()
            allow, risk_scale, risk_reason = self._check_risk(
                symbol, target_direction, h1_bars, portfolio_positions
            )
            
            if not allow:
                results.append({"action": "block", "reason": risk_reason})
                return {"success": True, "action": "block", "results": results, "reason": risk_reason}
            
            # Calculate final lot size
            final_scale = scale * risk_scale
            final_lots = self.calculate_lot_size(
                symbol, equity, final_scale,
                kelly_fraction=kelly_frac, regime=regime
            )
            
            results.append({"action": "risk_check", "kelly": kelly_frac,
                           "regime": regime, "risk_scale": risk_scale,
                           "reason": risk_reason, "final_lots": final_lots})
            
            # Check portfolio heat cap
            tick = self.mt5.symbol_info_tick(symbol)
            entry = tick.ask if tick else 0
            sl, _ = self._calculate_sl_tp(symbol, target_direction, entry, h4_bars)
            heat_allow, heat_scale, heat_reason = self.check_portfolio_heat(
                symbol, final_lots, sl, equity, max_heat_pct=5.0
            )
            
            if not heat_allow:
                results.append({"action": "heat_block", "reason": heat_reason})
                return {"success": True, "action": "heat_block", "results": results, "reason": heat_reason}
            
            if heat_scale < 1.0:
                final_lots = round(final_lots * heat_scale, 2)
                results.append({"action": "heat_scale", "scale": heat_scale, "reason": heat_reason, "final_lots": final_lots})
            
            # Open with partial TP (split into scalp + swing)
            open_result = self.open_position_with_partial_tp(
                symbol, target_direction, final_lots, h4_bars, regime=regime
            )
            results.append({"action": "open", **open_result})
            if not open_result["success"]:
                return {"success": False, "results": results}
        
        return {"success": True, "results": results}
    
    def calculate_lot_size(self, symbol: str, equity: float, scale: float = 1.0,
                           kelly_fraction: float = None, regime: MarketRegime = None) -> float:
        """Calculate lot size based on allocated equity and scale.
        
        Uses MT5 symbol info for contract size and lot constraints.
        Integrates Kelly Criterion and regime adjustments.
        """
        info = self.mt5.symbol_info(symbol)
        if info is None:
            return 0.01
        
        min_lot = info.volume_min
        max_lot = info.volume_max
        lot_step = info.volume_step
        
        # Base: proportional to equity, 1.0 lot per $50k
        base = equity / 50000.0
        raw = base * scale
        
        # Apply Kelly fraction if available
        if kelly_fraction is not None:
            raw *= kelly_fraction
        
        # Apply regime adjustment
        if regime == MarketRegime.VOLATILE:
            raw *= 0.5  # 50% reduction in volatile markets
        elif regime == MarketRegime.RANGING:
            raw *= 0.7  # 30% reduction in ranging markets
        elif regime == MarketRegime.QUIET:
            raw *= 0.0  # Block in quiet markets
        
        # Apply dynamic leverage cap based on drawdown
        capped_raw, lev_reason = self.dynamic_leverage.get_position_size_cap(
            equity, raw, broker_leverage=1000
        )
        
        # Round to lot step
        lots = round(capped_raw / lot_step) * lot_step
        lots = max(min_lot, min(max_lot, lots))
        
        return lots
    
    def _check_risk(self, symbol: str, target_direction: int, h1_bars: pd.DataFrame = None,
                    portfolio_positions: dict = None) -> tuple[bool, float, str]:
        """Check correlation and regime risk before opening.
        
        Returns:
            (allow: bool, scale: float, reason: str)
        """
        # Regime check
        regime = MarketRegime.UNKNOWN
        if h1_bars is not None:
            regime = self.regime_detector.detect(h1_bars)
            if regime == MarketRegime.VOLATILE:
                return True, 0.5, "Volatile regime: 50% size"
            elif regime == MarketRegime.RANGING:
                return True, 0.7, "Ranging regime: 30% size"
            elif regime == MarketRegime.QUIET:
                return False, 0.0, "Quiet regime: blocked"
        
        # Correlation check
        if portfolio_positions is not None:
            corr_result = self.correlation_checker.check_correlation(
                symbol, target_direction, portfolio_positions
            )
            if not corr_result["allowed"]:
                return False, 0.0, corr_result["reason"]
            if corr_result["scale"] < 1.0:
                return True, corr_result["scale"], corr_result["reason"]
        
        return True, 1.0, "OK"
    
    def add_trade_result(self, profit: float):
        """Record trade result for Kelly Criterion updates."""
        self.kelly_sizer.add_trade(profit)
    
    def get_kelly_fraction(self, default: float = 0.02) -> float:
        """Get Kelly fraction based on trade history."""
        return self.kelly_sizer.calculate(min_trades=10)
    
    def get_portfolio_positions(self, symbols: list = None) -> dict:
        """Get current portfolio positions for correlation checking."""
        syms = symbols or self.symbols
        positions = {}
        for sym in syms:
            pos = self.get_position(sym)
            if pos:
                positions[sym] = 1 if pos["type"] == 0 else -1
        return positions
    
    def update_correlation_prices(self, bars: pd.DataFrame, symbol: str):
        """Feed latest price to correlation checker from H1 bars."""
        if bars is not None and len(bars) > 0:
            last_close = bars["close"].iloc[-1]
            last_time = bars.index[-1] if hasattr(bars.index[-1], "strftime") else pd.Timestamp.now()
            self.correlation_checker.update_price(symbol, last_close, last_time)
