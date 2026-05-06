"""
Symbol discovery utility for MT5.
Run this to find exact symbol names available on your DPrime MT5 terminal.
"""
import json
import sys
from logger import setup_logger

logger = setup_logger("discover")


def discover(search_term: str = "", limit: int = 50):
    try:
        import MetaTrader5 as mt5
    except ImportError:
        logger.error("MetaTrader5 not installed. Run: pip install -r requirements.txt")
        sys.exit(1)
    
    if not mt5.initialize():
        logger.error("Failed to initialize MT5. Is the terminal running?")
        sys.exit(1)
    
    logger.info(f"Connected to MT5. Searching for symbols matching: '{search_term}'")
    
    all_symbols = mt5.symbols_get()
    if not all_symbols:
        logger.warning("No symbols returned. Make sure you're logged into your account.")
        mt5.shutdown()
        return
    
    matches = []
    search_lower = search_term.lower()
    
    for sym in all_symbols:
        name = sym.name
        desc = sym.description or ""
        if search_lower in name.lower() or search_lower in desc.lower():
            matches.append({
                "name": name,
                "description": desc,
                "spread": sym.spread,
                "digits": sym.digits,
                "trade_allowed": sym.trade_mode != 0,
                "currency_base": sym.currency_base,
                "currency_profit": sym.currency_profit,
            })
        if len(matches) >= limit:
            break
    
    if not matches:
        logger.info(f"No symbols found matching '{search_term}'. Showing first {limit} available:")
        for sym in all_symbols[:limit]:
            logger.info(f"  {sym.name}: {sym.description}")
    else:
        logger.info(f"Found {len(matches)} symbols:")
        for m in matches:
            logger.info(
                f"  {m['name']:12} | Spread: {m['spread']:6} | "
                f"Digits: {m['digits']} | Trade: {m['trade_allowed']} | {m['description']}"
            )
    
    mt5.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Discover MT5 symbols")
    parser.add_argument("--search", "-s", default="", help="Search term (e.g., EUR, XAU, NAS)")
    parser.add_argument("--limit", "-l", type=int, default=50, help="Max results")
    args = parser.parse_args()
    discover(args.search, args.limit)
