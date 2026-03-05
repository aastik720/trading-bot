"""
Market Data Module
==================

Unified data interface combining Dhan and Finnhub data with caching.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try pandas import
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


# ══════════════════════════════════════════════════════════
# CACHE SETTINGS
# ══════════════════════════════════════════════════════════

CACHE_QUOTE_SECONDS = 5
CACHE_OPTION_CHAIN_SECONDS = 30
CACHE_HISTORICAL_SECONDS = 300
CACHE_NEWS_SECONDS = 300


# ══════════════════════════════════════════════════════════
# HELPER FUNCTIONS (with fallbacks)
# ══════════════════════════════════════════════════════════

def _get_ist_now():
    """Get current IST time."""
    try:
        from utils.helpers import get_ist_now
        return get_ist_now()
    except:
        return datetime.now()

def _get_atm_strike(price, step):
    """Calculate ATM strike."""
    try:
        from utils.helpers import get_atm_strike
        return get_atm_strike(price, step)
    except:
        return round(price / step) * step

def _get_weekly_expiry():
    """Get nearest weekly expiry."""
    try:
        from utils.indian_market import get_weekly_expiry
        return get_weekly_expiry()
    except:
        today = datetime.now()
        days_until_thursday = (3 - today.weekday()) % 7
        if days_until_thursday == 0 and today.hour >= 15:
            days_until_thursday = 7
        return today + timedelta(days=days_until_thursday)

def _is_market_open():
    """Check if market is open."""
    try:
        from utils.indian_market import is_market_open
        return is_market_open()
    except:
        return True


# ══════════════════════════════════════════════════════════
# SIMPLE CACHE CLASS
# ══════════════════════════════════════════════════════════

class DataCache:
    """In-memory cache with TTL support."""
    
    def __init__(self):
        self._cache: Dict[str, tuple] = {}
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            value, expiry = self._cache[key]
            if datetime.now() < expiry:
                self._hits += 1
                return value
            else:
                del self._cache[key]
        self._misses += 1
        return None
    
    def set(self, key: str, value: Any, ttl_seconds: int):
        expiry = datetime.now() + timedelta(seconds=ttl_seconds)
        self._cache[key] = (value, expiry)
    
    def clear(self):
        self._cache.clear()
        self._hits = 0
        self._misses = 0
    
    def stats(self) -> Dict:
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        return {
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': round(hit_rate, 1),
            'cached_items': len(self._cache),
        }


# ══════════════════════════════════════════════════════════
# MARKET DATA CLASS
# ══════════════════════════════════════════════════════════

class MarketData:
    """Unified market data interface."""
    
    def __init__(self, dhan_client=None, finnhub_client=None):
        self._cache = DataCache()
        self._last_update: Dict[str, datetime] = {}
        
        # Initialize Dhan client
        self._dhan = dhan_client
        if self._dhan is None:
            try:
                from data.dhan_client import get_dhan_client
                self._dhan = get_dhan_client()
            except Exception as e:
                logger.warning(f"Could not initialize Dhan: {e}")
                self._dhan = None
        
        # Initialize Finnhub client
        self._finnhub = finnhub_client
        if self._finnhub is None:
            try:
                from data.finnhub_client import get_finnhub_client
                self._finnhub = get_finnhub_client()
            except Exception as e:
                logger.warning(f"Could not initialize Finnhub: {e}")
                self._finnhub = None
    
    # ══════════════════════════════════════════════════════
    # SPOT PRICES
    # ══════════════════════════════════════════════════════
    
    def get_spot_price(self, symbol: str) -> float:
        """Get current spot price."""
        quote = self.get_quote(symbol)
        return quote.get('ltp', 0.0)
    
    def get_quote(self, symbol: str) -> Dict:
        """Get full quote for a symbol."""
        symbol = symbol.upper().strip()
        cache_key = f"quote_{symbol}"
        
        cached = self._cache.get(cache_key)
        if cached:
            return cached
        
        try:
            if self._dhan:
                quote = self._dhan.get_index_quote(symbol)
                quote['is_live'] = not quote.get('_mock', False)
                self._cache.set(cache_key, quote, CACHE_QUOTE_SECONDS)
                self._last_update[f"quote_{symbol}"] = datetime.now()
                return quote
        except Exception as e:
            logger.error(f"Error getting quote for {symbol}: {e}")
        
        return self._get_mock_quote(symbol)
    
    def _get_mock_quote(self, symbol: str) -> Dict:
        mock_prices = {"NIFTY": 23250.50, "BANKNIFTY": 48750.25, "FINNIFTY": 21500.75}
        price = mock_prices.get(symbol, 20000.0)
        return {
            'symbol': symbol,
            'ltp': price,
            'open': price - 50,
            'high': price + 70,
            'low': price - 80,
            'close': price - 20,
            'change': 20.0,
            'change_pct': 0.08,
            'timestamp': _get_ist_now(),
            'is_live': False,
        }
    
    # ══════════════════════════════════════════════════════
    # OPTION CHAIN
    # ══════════════════════════════════════════════════════
    
    def get_option_chain(self, symbol: str, expiry: Optional[str] = None) -> Dict:
        """Get option chain for a symbol."""
        symbol = symbol.upper().strip()
        
        if expiry is None:
            expiry = _get_weekly_expiry().strftime('%Y-%m-%d')
        
        cache_key = f"chain_{symbol}_{expiry}"
        
        cached = self._cache.get(cache_key)
        if cached:
            return cached
        
        try:
            if self._dhan:
                chain = self._dhan.get_option_chain(symbol, expiry)
                chain['is_live'] = not chain.get('_mock', False)
                self._cache.set(cache_key, chain, CACHE_OPTION_CHAIN_SECONDS)
                return chain
        except Exception as e:
            logger.error(f"Error getting option chain: {e}")
        
        return self._get_mock_option_chain(symbol, expiry)
    
    def get_option_quote(self, symbol: str, strike: float, option_type: str, expiry: Optional[str] = None) -> Dict:
        """Get quote for a specific option."""
        option_type = option_type.upper()
        
        if expiry is None:
            expiry = _get_weekly_expiry().strftime('%Y-%m-%d')
        
        chain = self.get_option_chain(symbol, expiry)
        options_list = chain['calls'] if option_type == 'CE' else chain['puts']
        
        for option in options_list:
            if option['strike'] == strike:
                return {
                    'symbol': symbol,
                    'strike': strike,
                    'option_type': option_type,
                    'expiry': expiry,
                    'ltp': option['ltp'],
                    'oi': option.get('oi', 0),
                    'volume': option.get('volume', 0),
                    'iv': option.get('iv', 0),
                    'is_live': chain.get('is_live', False),
                }
        
        raise ValueError(f"Strike {strike} not found")
    
    def _get_mock_option_chain(self, symbol: str, expiry: str) -> Dict:
        spot = 23250 if symbol == "NIFTY" else 48750
        strike_step = 50 if symbol == "NIFTY" else 100
        atm = _get_atm_strike(spot, strike_step)
        
        calls, puts = [], []
        
        for i in range(-10, 11):
            strike = atm + (i * strike_step)
            dist = abs(i)
            ce_prem = max(150 - dist * 15 + max(spot - strike, 0) * 0.5, 5)
            pe_prem = max(150 - dist * 15 + max(strike - spot, 0) * 0.5, 5)
            
            calls.append({
                'strike': strike, 
                'ltp': round(ce_prem, 2), 
                'oi': 100000, 
                'volume': 5000, 
                'iv': 12 + dist * 0.5,
                'bid': round(ce_prem - 0.5, 2),
                'ask': round(ce_prem + 0.5, 2),
            })
            puts.append({
                'strike': strike, 
                'ltp': round(pe_prem, 2), 
                'oi': 100000, 
                'volume': 5000, 
                'iv': 12 + dist * 0.5,
                'bid': round(pe_prem - 0.5, 2),
                'ask': round(pe_prem + 0.5, 2),
            })
        
        return {
            'symbol': symbol, 
            'spot_price': spot, 
            'expiry': expiry, 
            'atm_strike': atm,
            'calls': calls, 
            'puts': puts, 
            'timestamp': _get_ist_now(), 
            'is_live': False,
        }
    
    # ══════════════════════════════════════════════════════
    # HISTORICAL DATA
    # ══════════════════════════════════════════════════════
    
    def get_historical(self, symbol: str, days: int = 50) -> Union[Any, List[Dict]]:
        """Get historical OHLCV data."""
        symbol = symbol.upper().strip()
        cache_key = f"historical_{symbol}_{days}"
        
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        
        to_date = datetime.now().strftime('%Y-%m-%d')
        from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        candles = []
        try:
            if self._dhan:
                candles = self._dhan.get_historical(symbol, from_date, to_date)
        except Exception as e:
            logger.error(f"Error getting historical: {e}")
        
        if not candles:
            candles = self._get_mock_historical(symbol, days)
        
        if PANDAS_AVAILABLE and candles:
            df = pd.DataFrame(candles)
            self._cache.set(cache_key, df, CACHE_HISTORICAL_SECONDS)
            return df
        
        self._cache.set(cache_key, candles, CACHE_HISTORICAL_SECONDS)
        return candles
    
    def _get_mock_historical(self, symbol: str, days: int) -> List[Dict]:
        import random
        base = {"NIFTY": 23000, "BANKNIFTY": 48000}.get(symbol, 20000)
        candles = []
        price = base
        
        for i in range(days):
            date = datetime.now() - timedelta(days=days-i)
            if date.weekday() < 5:
                change = random.uniform(-0.015, 0.015)
                o, c = price, price * (1 + change)
                h, l = max(o, c) * 1.005, min(o, c) * 0.995
                candles.append({
                    'timestamp': date.strftime('%Y-%m-%d'), 
                    'open': round(o, 2), 
                    'high': round(h, 2), 
                    'low': round(l, 2), 
                    'close': round(c, 2), 
                    'volume': random.randint(100000, 500000)
                })
                price = c
        
        return candles
    
    # ══════════════════════════════════════════════════════
    # NEWS
    # ══════════════════════════════════════════════════════
    
    def get_news(self, symbol: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """Get market news."""
        cache_key = f"news_{symbol or 'market'}_{limit}"
        
        cached = self._cache.get(cache_key)
        if cached:
            return cached
        
        news = []
        try:
            if self._finnhub and self._finnhub.is_configured():
                if symbol:
                    news = self._finnhub.get_company_news(symbol)
                else:
                    news = self._finnhub.get_market_news()
                news = news[:limit]
        except Exception as e:
            logger.error(f"Error getting news: {e}")
        
        if not news:
            news = [{
                'headline': 'Markets steady amid global cues', 
                'summary': 'Indian markets remain stable.',
                'source': 'Mock News', 
                'datetime': datetime.now(), 
                'url': '#',
                '_mock': True
            }]
        
        self._cache.set(cache_key, news, CACHE_NEWS_SECONDS)
        return news
    
    def get_sentiment(self, symbol: str = "MARKET") -> Dict:
        """Get sentiment."""
        try:
            if self._finnhub and self._finnhub.is_configured():
                return self._finnhub.get_sentiment(symbol)
        except:
            pass
        return {
            'symbol': symbol, 
            'bullish_percent': 50.0, 
            'bearish_percent': 50.0, 
            'sentiment_score': 0.0
        }
    
    # ══════════════════════════════════════════════════════
    # UTILITIES
    # ══════════════════════════════════════════════════════
    
    def is_data_fresh(self, symbol: str, max_age: int = 60) -> bool:
        """Check if data is fresh."""
        key = f"quote_{symbol.upper()}"
        if key not in self._last_update:
            return False
        return (datetime.now() - self._last_update[key]).total_seconds() < max_age
    
    def get_data_age(self, symbol: str) -> Optional[float]:
        """Get data age in seconds."""
        key = f"quote_{symbol.upper()}"
        if key not in self._last_update:
            return None
        return (datetime.now() - self._last_update[key]).total_seconds()
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics."""
        return self._cache.stats()
    
    def clear_cache(self):
        """Clear all cache."""
        self._cache.clear()
        self._last_update.clear()
    
    def get_status(self) -> Dict:
        """Get connection status."""
        dhan_ok = self._dhan.is_connected() if self._dhan else False
        finnhub_ok = self._finnhub.is_configured() if self._finnhub else False
        return {
            'dhan_connected': dhan_ok,
            'finnhub_configured': finnhub_ok,
            'cache_stats': self._cache.stats(),
            'market_open': _is_market_open(),
            'timestamp': _get_ist_now(),
        }


# ══════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════

_market_data_instance: Optional[MarketData] = None

def get_market_data() -> MarketData:
    """Get singleton MarketData instance."""
    global _market_data_instance
    if _market_data_instance is None:
        _market_data_instance = MarketData()
    return _market_data_instance


# ══════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  MARKET DATA - TEST")
    print("=" * 60)
    
    md = get_market_data()
    
    # Status
    print("\n  Connection Status:")
    status = md.get_status()
    print(f"    Dhan:     {'✅ Connected' if status['dhan_connected'] else '⚠️  Not Connected'}")
    print(f"    Finnhub:  {'✅ Configured' if status['finnhub_configured'] else '⚠️  Not Configured'}")
    print(f"    Market:   {'✅ Open' if status['market_open'] else '🔴 Closed'}")
    
    # Prices
    print("\n" + "-" * 60)
    print("  Spot Prices:")
    for sym in ["NIFTY", "BANKNIFTY"]:
        quote = md.get_quote(sym)
        data_type = "LIVE" if quote.get('is_live') else "MOCK"
        print(f"    {sym}: ₹{quote['ltp']:,.2f} ({data_type})")
    
    # Option Chain
    print("\n" + "-" * 60)
    print("  Option Chain (NIFTY):")
    chain = md.get_option_chain("NIFTY")
    data_type = "LIVE" if chain.get('is_live') else "MOCK"
    print(f"    Spot:    ₹{chain['spot_price']:,.2f}")
    print(f"    ATM:     {chain['atm_strike']}")
    print(f"    Expiry:  {chain['expiry']}")
    print(f"    Strikes: {len(chain['calls'])} CE, {len(chain['puts'])} PE")
    print(f"    Data:    {data_type}")
    
    # ATM Option Quote
    atm = chain['atm_strike']
    for c in chain['calls']:
        if c['strike'] == atm:
            print(f"    ATM CE:  ₹{c['ltp']:.2f} (IV: {c['iv']:.1f}%)")
            break
    
    # Historical
    print("\n" + "-" * 60)
    print("  Historical Data (NIFTY, 10 days):")
    hist = md.get_historical("NIFTY", days=10)
    if PANDAS_AVAILABLE and hasattr(hist, 'shape'):
        print(f"    DataFrame: {hist.shape[0]} rows x {hist.shape[1]} columns")
        if len(hist) > 0:
            print(f"    Last Close: ₹{hist.iloc[-1]['close']:,.2f}")
    else:
        print(f"    List: {len(hist)} candles")
        if hist:
            print(f"    Last Close: ₹{hist[-1]['close']:,.2f}")
    
    # News
    print("\n" + "-" * 60)
    print("  Market News:")
    news = md.get_news(limit=3)
    print(f"    Fetched {len(news)} articles")
    for article in news[:2]:
        hl = article['headline']
        if len(hl) > 50:
            hl = hl[:50] + "..."
        mock = " (MOCK)" if article.get('_mock') else ""
        print(f"    • {hl}{mock}")
    
    # Cache Stats
    print("\n" + "-" * 60)
    print("  Cache Statistics:")
    stats = md.get_cache_stats()
    print(f"    Hits:     {stats['hits']}")
    print(f"    Misses:   {stats['misses']}")
    print(f"    Hit Rate: {stats['hit_rate']}%")
    print(f"    Cached:   {stats['cached_items']} items")
    
    print("\n" + "=" * 60)
    print("  Market Data Test Complete!")
    print("=" * 60 + "\n")