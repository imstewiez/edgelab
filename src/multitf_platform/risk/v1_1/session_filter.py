"""Trading session filter.

Blocks new entries outside optimal liquidity windows:
- Asian session (00:00-08:00 GMT): BLOCKED (low liquidity, chop)
- London session (08:00-17:00 GMT): ALLOWED
- London-NY overlap (13:00-17:00 GMT): ALLOWED (highest volatility)
- NY session (13:00-22:00 GMT): ALLOWED
"""
from datetime import datetime, time
from typing import Optional
from enum import Enum


class SessionStatus(Enum):
    ALLOWED = "allowed"
    REDUCED = "reduced"
    BLOCKED = "blocked"


class SessionFilter:
    """Filter trades based on forex trading session.
    
    London (08:00-17:00 GMT) and NY (13:00-22:00 GMT) are active.
    Asian session is blocked for trend strategies.
    """
    
    # GMT hours
    LONDON_OPEN = 8
    LONDON_CLOSE = 17
    NY_OPEN = 13
    NY_CLOSE = 22
    
    def __init__(self, block_asian: bool = True, reduce_london_open: bool = False):
        self.block_asian = block_asian
        self.reduce_london_open = reduce_london_open
    
    def check(self, dt: Optional[datetime] = None) -> tuple[SessionStatus, float, str]:
        """Check if trading is allowed at given time.
        
        Returns:
            (status, scale, reason)
        """
        if dt is None:
            dt = datetime.utcnow()
        
        hour = dt.hour
        
        # Asian session: 00:00 - 08:00 GMT
        if hour < self.LONDON_OPEN:
            if self.block_asian:
                return SessionStatus.BLOCKED, 0.0, f"Asian session blocked ({hour:02d}:00 GMT)"
            return SessionStatus.REDUCED, 0.5, f"Asian session reduced ({hour:02d}:00 GMT)"
        
        # London-NY overlap: 13:00 - 17:00 GMT (best)
        if self.NY_OPEN <= hour < self.LONDON_CLOSE:
            return SessionStatus.ALLOWED, 1.0, "London-NY overlap (prime)"
        
        # London only: 08:00 - 13:00 GMT
        if self.LONDON_OPEN <= hour < self.NY_OPEN:
            if self.reduce_london_open and hour == self.LONDON_OPEN:
                return SessionStatus.REDUCED, 0.75, "London open reduced (first hour)"
            return SessionStatus.ALLOWED, 1.0, "London session"
        
        # NY only: 17:00 - 22:00 GMT
        if self.LONDON_CLOSE <= hour < self.NY_CLOSE:
            return SessionStatus.ALLOWED, 1.0, "NY session"
        
        # Late NY / weekend: 22:00 - 00:00 GMT
        return SessionStatus.BLOCKED, 0.0, f"Late session blocked ({hour:02d}:00 GMT)"
