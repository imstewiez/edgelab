"""Weekend / Gap Risk Filter.

Closes all positions before weekend market close to avoid gap risk.
XAUUSD and NAS100 are especially vulnerable to weekend gaps (1-3%).

Friday close: 22:00 GMT (forex), Sunday open: 22:00 GMT
"""
from datetime import datetime, time
from typing import Optional


class WeekendFilter:
    """Block new entries and optionally close positions before weekend."""
    
    # Friday 20:00 GMT = start of weekend risk window
    WEEKEND_START_HOUR = 20
    WEEKEND_START_DAY = 4  # Friday (0=Monday)
    
    # Sunday 22:00 GMT = end of weekend risk window
    WEEKEND_END_HOUR = 22
    WEEKEND_END_DAY = 6  # Sunday
    
    def __init__(self, close_before_weekend: bool = True, block_weekend: bool = True):
        self.close_before_weekend = close_before_weekend
        self.block_weekend = block_weekend
    
    def is_weekend_risk(self, dt: Optional[datetime] = None) -> bool:
        """Check if we're in the weekend risk window."""
        if dt is None:
            dt = datetime.utcnow()
        
        weekday = dt.weekday()
        hour = dt.hour
        
        # Friday after 20:00 GMT
        if weekday == self.WEEKEND_START_DAY and hour >= self.WEEKEND_START_HOUR:
            return True
        
        # Saturday
        if weekday == 5:
            return True
        
        # Sunday before 22:00 GMT
        if weekday == self.WEEKEND_END_DAY and hour < self.WEEKEND_END_HOUR:
            return True
        
        return False
    
    def should_close_positions(self, dt: Optional[datetime] = None) -> tuple[bool, str]:
        """Check if positions should be closed before weekend.
        
        Returns:
            (should_close: bool, reason: str)
        """
        if not self.close_before_weekend:
            return False, "Weekend close disabled"
        
        if self.is_weekend_risk(dt):
            return True, "Weekend gap risk — closing all positions"
        
        return False, "OK"
    
    def allow_new_trade(self, dt: Optional[datetime] = None) -> tuple[bool, str]:
        """Check if new trades should be allowed.
        
        Returns:
            (allow: bool, reason: str)
        """
        if not self.block_weekend:
            return True, "Weekend block disabled"
        
        if self.is_weekend_risk(dt):
            return False, "Weekend gap risk — new trades blocked"
        
        return True, "OK"
