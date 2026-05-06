"""JSONL audit logger for all platform decisions and executions.

Every signal, risk decision, fill, and state change is logged as a JSON line
to an append-only file for later analysis and regulatory compliance.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Any, Dict


class AuditLogger:
    """Append-only JSONL audit logger.
    
    Usage:
        logger = AuditLogger("logs/audit_2026-05-06.jsonl")
        logger.log_signal(timestamp, direction, features)
        logger.log_risk(timestamp, action, scale, reasons)
        logger.log_fill(timestamp, action, side, size, price, pnl)
        logger.log_state(timestamp, balance, equity, margin, position)
    """
    
    def __init__(self, path: Optional[Path] = None):
        if path is None:
            today = datetime.now().strftime("%Y%m%d")
            path = Path(__file__).parent.parent.parent.parent / "logs" / f"audit_{today}.jsonl"
        
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write header on first use
        if not self.path.exists():
            self._write({
                "event": "session_start",
                "timestamp": datetime.utcnow().isoformat() + "Z",
            })
    
    def _write(self, record: dict):
        """Append a JSON line to the audit log."""
        with open(self.path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    
    def log_signal(self, timestamp, direction: int, h1_mom: float,
                   h4_mom: float, valid: bool, blocked_reason: Optional[str] = None):
        """Log raw strategy signal."""
        self._write({
            "event": "signal",
            "timestamp": str(timestamp),
            "direction": direction,
            "h1_momentum": round(h1_mom, 6) if h1_mom is not None else None,
            "h4_momentum": round(h4_mom, 6) if h4_mom is not None else None,
            "valid": valid,
            "blocked_reason": blocked_reason,
        })
    
    def log_risk(self, timestamp, action: str, final_direction: int,
                 scale: float, reason: str, sub_reasons: list):
        """Log risk wrapper decision."""
        self._write({
            "event": "risk_decision",
            "timestamp": str(timestamp),
            "action": action,
            "final_direction": final_direction,
            "scale": round(scale, 4),
            "reason": reason,
            "sub_reasons": sub_reasons,
        })
    
    def log_fill(self, timestamp, action: str, side: str, size_lots: float,
                 fill_price: float, spread: float, slippage: float,
                 commission: float, realized_pnl: Optional[float],
                 balance_before: float, balance_after: float, reason: str):
        """Log broker fill execution."""
        self._write({
            "event": "fill",
            "timestamp": str(timestamp),
            "action": action,
            "side": side,
            "size_lots": round(size_lots, 4),
            "fill_price": round(fill_price, 5),
            "spread": round(spread, 5),
            "slippage": round(slippage, 5),
            "commission": round(commission, 4),
            "realized_pnl": round(realized_pnl, 4) if realized_pnl is not None else None,
            "balance_before": round(balance_before, 2),
            "balance_after": round(balance_after, 2),
            "reason": reason,
        })
    
    def log_state(self, timestamp, balance: float, equity: float,
                  margin_used: float, free_margin: float,
                  position_direction: int, position_size: float,
                  unrealized_pnl: float, daily_pnl: float):
        """Log periodic account state snapshot."""
        self._write({
            "event": "state_snapshot",
            "timestamp": str(timestamp),
            "balance": round(balance, 2),
            "equity": round(equity, 2),
            "margin_used": round(margin_used, 2),
            "free_margin": round(free_margin, 2),
            "position_direction": position_direction,
            "position_size": round(position_size, 4),
            "unrealized_pnl": round(unrealized_pnl, 4),
            "daily_pnl": round(daily_pnl, 4),
        })
    
    def log_kill_switch(self, timestamp: str, reason: str, equity: float):
        """Log kill switch activation."""
        self._write({
            "event": "kill_switch",
            "timestamp": str(timestamp),
            "reason": reason,
            "equity": round(equity, 2),
        })
    
    def log_error(self, timestamp: str, error_type: str, message: str):
        """Log error or exception."""
        self._write({
            "event": "error",
            "timestamp": str(timestamp),
            "error_type": error_type,
            "message": message,
        })
    
    def get_summary(self) -> Dict[str, Any]:
        """Return summary stats from audit log."""
        if not self.path.exists():
            return {}
        
        counts = {}
        with open(self.path, "r") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    evt = record.get("event", "unknown")
                    counts[evt] = counts.get(evt, 0) + 1
                except json.JSONDecodeError:
                    continue
        
        return {
            "path": str(self.path),
            "total_records": sum(counts.values()),
            "event_counts": counts,
        }
