"""Economic Calendar Integration.

Fetches high-impact economic events from public API.
Blocks new trades during major news releases (NFP, CPI, FOMC, etc.).

Uses ForexFactory public API as primary source with synthetic fallback.
"""
import json
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from urllib.request import urlopen, Request
from urllib.error import URLError


class EconomicCalendar:
    """Fetch and filter high-impact economic events."""
    
    HIGH_IMPACT_EVENTS = [
        "non-farm payrolls", "nfp", "unemployment rate",
        "consumer price index", "cpi", "inflation rate",
        "federal reserve", "fomc", "interest rate",
        "european central bank", "ecb",
        "bank of england", "boe",
        "gdp", "gross domestic product",
        "retail sales",
        "pmi", "ism",
        "crude oil inventories",
    ]
    
    # Block window: ±30 minutes around event
    BLOCK_WINDOW_MINUTES = 30
    
    def __init__(self):
        self._events: List[dict] = []
        self._last_fetch: Optional[datetime] = None
    
    def _fetch_api(self) -> List[dict]:
        """Try to fetch from ForexFactory public API."""
        try:
            # ForexFactory weekly calendar JSON (public endpoint)
            req = Request(
                "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            
            events = []
            for item in data:
                title = item.get("title", "").lower()
                impact = item.get("impact", "").lower()
                
                # Only high/medium impact events
                if impact not in ("high", "medium"):
                    continue
                
                # Parse time
                time_str = item.get("date", "") + " " + item.get("time", "00:00")
                try:
                    event_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
                
                events.append({
                    "title": item.get("title", ""),
                    "time": event_time.isoformat(),
                    "impact": impact,
                    "currency": item.get("country", ""),
                })
            
            self._events = events
            self._last_fetch = datetime.utcnow()
            return events
        
        except (URLError, json.JSONDecodeError, Exception):
            return []
    
    def _synthetic_events(self) -> List[dict]:
        """Generate synthetic high-impact events as fallback."""
        events = []
        now = datetime.utcnow()
        
        # NFP: First Friday of each month at 13:30 GMT
        for month_offset in range(-1, 3):
            month = now.month + month_offset
            year = now.year
            while month > 12:
                month -= 12
                year += 1
            while month < 1:
                month += 12
                year -= 1
            
            # Find first Friday
            first_day = datetime(year, month, 1)
            days_to_friday = (4 - first_day.weekday()) % 7
            nfp_date = first_day + timedelta(days=days_to_friday)
            nfp_time = nfp_date.replace(hour=13, minute=30)
            
            events.append({
                "title": "Non-Farm Payrolls",
                "time": nfp_time.isoformat(),
                "impact": "high",
                "currency": "USD",
                "source": "synthetic",
            })
        
        # FOMC: Every ~6 weeks (simplified: every 6th Wednesday)
        # Add a few recent and upcoming
        wednesday = now - timedelta(days=now.weekday() - 2)
        for week_offset in range(-8, 8):
            fomc = wednesday + timedelta(weeks=week_offset)
            if fomc.day <= 7 or (21 <= fomc.day <= 28):
                events.append({
                    "title": "FOMC Statement",
                    "time": fomc.replace(hour=19, minute=0).isoformat(),
                    "impact": "high",
                    "currency": "USD",
                    "source": "synthetic",
                })
        
        return events
    
    def get_events(self, force_refresh: bool = False) -> List[dict]:
        """Get high-impact economic events."""
        if force_refresh or not self._events or not self._last_fetch:
            api_events = self._fetch_api()
            if not api_events:
                self._events = self._synthetic_events()
                self._last_fetch = datetime.utcnow()
            return self._events
        
        # Refresh if older than 6 hours
        if (datetime.utcnow() - self._last_fetch).total_seconds() > 21600:
            api_events = self._fetch_api()
            if not api_events:
                self._events = self._synthetic_events()
                self._last_fetch = datetime.utcnow()
        
        return self._events
    
    def is_blocked(self, dt: Optional[datetime] = None) -> tuple[bool, str]:
        """Check if trading should be blocked due to upcoming high-impact news.
        
        Returns:
            (blocked: bool, reason: str)
        """
        if dt is None:
            dt = datetime.utcnow()
        
        events = self.get_events()
        
        for event in events:
            try:
                event_time = datetime.fromisoformat(event["time"])
            except ValueError:
                continue
            
            time_diff = abs((dt - event_time).total_seconds() / 60)
            
            if time_diff <= self.BLOCK_WINDOW_MINUTES:
                return True, f"News block: {event['title']} at {event['time'][:16]}"
        
        return False, "No high-impact news in window"
    
    def get_upcoming(self, hours_ahead: int = 24) -> List[dict]:
        """Get upcoming events within next N hours."""
        now = datetime.utcnow()
        events = self.get_events()
        upcoming = []
        
        for event in events:
            try:
                event_time = datetime.fromisoformat(event["time"])
            except ValueError:
                continue
            
            hours_until = (event_time - now).total_seconds() / 3600
            if 0 < hours_until <= hours_ahead:
                event["hours_until"] = round(hours_until, 1)
                upcoming.append(event)
        
        upcoming.sort(key=lambda x: x["time"])
        return upcoming[:10]
