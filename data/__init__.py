"""
Data Layer Package
==================

This package provides data access for the trading bot:

- DhanClient: Broker API for market data and order execution
- FinnhubClient: News and sentiment data
- MarketData: Unified data interface with caching

Usage:
    from data import MarketData, DhanClient, FinnhubClient
    
    # Or get pre-configured instances
    from data import get_market_data, get_dhan_client, get_finnhub_client
"""

# Version
__version__ = "1.0.0"

# Import with error handling
_import_errors = []

try:
    from data.dhan_client import DhanClient, get_dhan_client
except ImportError as e:
    _import_errors.append(f"dhan_client: {e}")
    DhanClient = None
    get_dhan_client = None

try:
    from data.finnhub_client import FinnhubClient, get_finnhub_client
except ImportError as e:
    _import_errors.append(f"finnhub_client: {e}")
    FinnhubClient = None
    get_finnhub_client = None

try:
    from data.market_data import MarketData, get_market_data
except ImportError as e:
    _import_errors.append(f"market_data: {e}")
    MarketData = None
    get_market_data = None

# Export available items
__all__ = [
    "DhanClient",
    "FinnhubClient", 
    "MarketData",
    "get_dhan_client",
    "get_finnhub_client",
    "get_market_data",
]

# Filter out None values
__all__ = [name for name in __all__ if globals().get(name) is not None]


# Quick test
if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  DATA LAYER - Package Info")
    print("=" * 50)
    print(f"\n  Version: {__version__}")
    
    if _import_errors:
        print(f"\n  ⚠️  Import Errors:")
        for err in _import_errors:
            print(f"    - {err}")
    
    print(f"\n  Available Exports:")
    for name in __all__:
        print(f"    ✅ {name}")
    
    print("\n" + "=" * 50 + "\n")