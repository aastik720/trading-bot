"""
Finnhub Client Module
=====================

Wrapper around Finnhub API for news and sentiment data.

Finnhub API Documentation: https://finnhub.io/docs/api

Free Tier Limits:
    - 60 API calls per minute
    - Market news, company news, sentiment

Usage:
    from data.finnhub_client import FinnhubClient
    
    client = FinnhubClient(api_key)
    
    # Get market news
    news = client.get_market_news()
    for article in news[:5]:
        print(article['headline'])
    
    # Get sentiment
    sentiment = client.get_sentiment("AAPL")
    print(f"Bullish: {sentiment['bullish_percent']}%")
"""

import time
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from functools import lru_cache

# Setup logging
logger = logging.getLogger(__name__)

# Try to import our modules
try:
    from utils.exceptions import FinnhubAPIError
    from utils.helpers import get_ist_now
except ImportError:
    class FinnhubAPIError(Exception):
        pass
    def get_ist_now():
        return datetime.now()


# ══════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"

# Rate limiting
RATE_LIMIT_CALLS = 60      # Max calls per minute
RATE_LIMIT_WINDOW = 60     # Window in seconds

# Cache settings
CACHE_NEWS_SECONDS = 300       # 5 minutes for news
CACHE_SENTIMENT_SECONDS = 600  # 10 minutes for sentiment

# Retry settings
MAX_RETRIES = 3
RETRY_DELAY = 1


# ══════════════════════════════════════════════════════════
# SIMPLE CACHE CLASS
# ══════════════════════════════════════════════════════════

class SimpleCache:
    """Simple in-memory cache with TTL."""
    
    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # key -> (value, expiry_time)
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        if key in self._cache:
            value, expiry = self._cache[key]
            if datetime.now() < expiry:
                return value
            else:
                del self._cache[key]
        return None
    
    def set(self, key: str, value: Any, ttl_seconds: int):
        """Set value in cache with TTL."""
        expiry = datetime.now() + timedelta(seconds=ttl_seconds)
        self._cache[key] = (value, expiry)
    
    def clear(self):
        """Clear all cache."""
        self._cache.clear()
    
    def remove(self, key: str):
        """Remove specific key."""
        if key in self._cache:
            del self._cache[key]


# ══════════════════════════════════════════════════════════
# RATE LIMITER
# ══════════════════════════════════════════════════════════

class RateLimiter:
    """Simple rate limiter for API calls."""
    
    def __init__(self, max_calls: int, window_seconds: int):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.calls: List[float] = []
    
    def wait_if_needed(self):
        """Wait if rate limit would be exceeded."""
        now = time.time()
        
        # Remove old calls outside the window
        self.calls = [t for t in self.calls if now - t < self.window_seconds]
        
        if len(self.calls) >= self.max_calls:
            # Need to wait
            oldest_call = self.calls[0]
            wait_time = self.window_seconds - (now - oldest_call) + 0.1
            if wait_time > 0:
                logger.warning(f"Rate limit reached. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
        
        # Record this call
        self.calls.append(time.time())
    
    def remaining_calls(self) -> int:
        """Get remaining calls in current window."""
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.window_seconds]
        return max(0, self.max_calls - len(self.calls))


# ══════════════════════════════════════════════════════════
# FINNHUB CLIENT CLASS
# ══════════════════════════════════════════════════════════

class FinnhubClient:
    """
    Wrapper around Finnhub API for news and sentiment data.
    
    Features:
        - Market news and company news
        - Sentiment analysis
        - Automatic rate limiting (60 calls/min)
        - Response caching
        - Retry logic with exponential backoff
    """
    
    def __init__(self, api_key: str = ""):
        """
        Initialize Finnhub client.
        
        Args:
            api_key: Your Finnhub API key
        """
        self.api_key = api_key
        self.base_url = FINNHUB_BASE_URL
        self._cache = SimpleCache()
        self._rate_limiter = RateLimiter(RATE_LIMIT_CALLS, RATE_LIMIT_WINDOW)
        self._session = requests.Session()
        
        if not api_key:
            logger.warning("Finnhub API key not provided")
    
    def _make_request(
        self, 
        endpoint: str, 
        params: Optional[Dict] = None
    ) -> Dict:
        """
        Make API request with retry logic.
        
        Args:
            endpoint: API endpoint (e.g., '/news')
            params: Query parameters
            
        Returns:
            JSON response as dict
            
        Raises:
            FinnhubAPIError: If request fails after retries
        """
        if not self.api_key:
            raise FinnhubAPIError("Finnhub API key not configured")
        
        url = f"{self.base_url}{endpoint}"
        
        # Add API key to params
        if params is None:
            params = {}
        params['token'] = self.api_key
        
        last_error = None
        
        for attempt in range(MAX_RETRIES):
            try:
                # Wait if rate limited
                self._rate_limiter.wait_if_needed()
                
                # Make request
                response = self._session.get(url, params=params, timeout=10)
                
                # Check response
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    # Rate limited by server
                    wait_time = int(response.headers.get('Retry-After', 60))
                    logger.warning(f"Finnhub rate limited. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                elif response.status_code == 401:
                    raise FinnhubAPIError("Invalid Finnhub API key")
                elif response.status_code == 403:
                    raise FinnhubAPIError("Finnhub API access forbidden")
                else:
                    raise FinnhubAPIError(f"Finnhub API error: {response.status_code}")
                    
            except requests.exceptions.Timeout:
                last_error = "Request timeout"
            except requests.exceptions.ConnectionError:
                last_error = "Connection error"
            except FinnhubAPIError:
                raise
            except Exception as e:
                last_error = str(e)
            
            # Exponential backoff
            wait_time = RETRY_DELAY * (2 ** attempt)
            logger.warning(f"Finnhub request failed: {last_error}. Retry {attempt + 1}/{MAX_RETRIES} in {wait_time}s")
            time.sleep(wait_time)
        
        raise FinnhubAPIError(f"Failed after {MAX_RETRIES} retries: {last_error}")
    
    # ══════════════════════════════════════════════════════
    # NEWS METHODS
    # ══════════════════════════════════════════════════════
    
    def get_market_news(self, category: str = "general") -> List[Dict]:
        """
        Get general market news.
        
        Args:
            category: News category ('general', 'forex', 'crypto', 'merger')
            
        Returns:
            List of news articles:
            [
                {
                    'headline': 'Market rallies on...',
                    'summary': 'Stocks rose today...',
                    'source': 'Reuters',
                    'datetime': datetime object,
                    'url': 'https://...',
                    'image': 'https://...',
                    'category': 'general'
                },
                ...
            ]
        """
        # Check cache
        cache_key = f"market_news_{category}"
        cached = self._cache.get(cache_key)
        if cached:
            logger.debug(f"Returning cached market news for {category}")
            return cached
        
        try:
            data = self._make_request('/news', {'category': category})
            
            news = []
            for item in data:
                news.append({
                    'headline': item.get('headline', ''),
                    'summary': item.get('summary', ''),
                    'source': item.get('source', ''),
                    'datetime': datetime.fromtimestamp(item.get('datetime', 0)),
                    'url': item.get('url', ''),
                    'image': item.get('image', ''),
                    'category': category,
                    'id': item.get('id', ''),
                })
            
            # Cache the result
            self._cache.set(cache_key, news, CACHE_NEWS_SECONDS)
            
            logger.info(f"Fetched {len(news)} market news articles")
            return news
            
        except FinnhubAPIError:
            raise
        except Exception as e:
            logger.error(f"Error fetching market news: {e}")
            raise FinnhubAPIError(f"Failed to fetch market news: {e}")
    
    def get_company_news(
        self, 
        symbol: str, 
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> List[Dict]:
        """
        Get news for a specific company/symbol.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL', 'RELIANCE')
            from_date: Start date 'YYYY-MM-DD' (default: 7 days ago)
            to_date: End date 'YYYY-MM-DD' (default: today)
            
        Returns:
            List of news articles (same format as get_market_news)
        """
        # Default dates
        if to_date is None:
            to_date = datetime.now().strftime('%Y-%m-%d')
        if from_date is None:
            from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        # Check cache
        cache_key = f"company_news_{symbol}_{from_date}_{to_date}"
        cached = self._cache.get(cache_key)
        if cached:
            logger.debug(f"Returning cached news for {symbol}")
            return cached
        
        try:
            data = self._make_request('/company-news', {
                'symbol': symbol.upper(),
                'from': from_date,
                'to': to_date
            })
            
            news = []
            for item in data:
                news.append({
                    'headline': item.get('headline', ''),
                    'summary': item.get('summary', ''),
                    'source': item.get('source', ''),
                    'datetime': datetime.fromtimestamp(item.get('datetime', 0)),
                    'url': item.get('url', ''),
                    'image': item.get('image', ''),
                    'symbol': symbol.upper(),
                    'id': item.get('id', ''),
                })
            
            # Cache the result
            self._cache.set(cache_key, news, CACHE_NEWS_SECONDS)
            
            logger.info(f"Fetched {len(news)} news articles for {symbol}")
            return news
            
        except FinnhubAPIError:
            raise
        except Exception as e:
            logger.error(f"Error fetching company news for {symbol}: {e}")
            raise FinnhubAPIError(f"Failed to fetch company news: {e}")
    
    def get_indian_market_news(self, limit: int = 20) -> List[Dict]:
        """
        Get news relevant to Indian markets.
        
        This searches for India-related news in general market news.
        
        Args:
            limit: Maximum number of articles to return
            
        Returns:
            List of India-related news articles
        """
        try:
            # Get general market news
            all_news = self.get_market_news('general')
            
            # Filter for India-related keywords
            india_keywords = [
                'india', 'nifty', 'sensex', 'bse', 'nse', 'rbi', 
                'rupee', 'mumbai', 'reliance', 'tata', 'infosys',
                'hdfc', 'icici', 'bharti', 'adani', 'asian'
            ]
            
            india_news = []
            for article in all_news:
                text = (article.get('headline', '') + ' ' + article.get('summary', '')).lower()
                if any(keyword in text for keyword in india_keywords):
                    india_news.append(article)
                    if len(india_news) >= limit:
                        break
            
            return india_news
            
        except Exception as e:
            logger.error(f"Error fetching Indian market news: {e}")
            return []
    
    # ══════════════════════════════════════════════════════
    # SENTIMENT METHODS
    # ══════════════════════════════════════════════════════
    
    def get_sentiment(self, symbol: str) -> Dict:
        """
        Get news sentiment for a symbol.
        
        Note: This is available for US stocks. For Indian stocks,
        we analyze news headlines instead.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            {
                'symbol': 'AAPL',
                'bullish_percent': 65.5,
                'bearish_percent': 34.5,
                'articles_analyzed': 50,
                'sentiment_score': 0.31,  # -1 to 1
                'buzz': 0.8,  # Social media buzz
                'timestamp': datetime
            }
        """
        # Check cache
        cache_key = f"sentiment_{symbol}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached
        
        try:
            # Try to get official sentiment
            data = self._make_request('/news-sentiment', {'symbol': symbol.upper()})
            
            sentiment_data = data.get('sentiment', {})
            buzz_data = data.get('buzz', {})
            
            result = {
                'symbol': symbol.upper(),
                'bullish_percent': sentiment_data.get('bullishPercent', 50) * 100,
                'bearish_percent': sentiment_data.get('bearishPercent', 50) * 100,
                'articles_analyzed': data.get('companyNewsScore', 0),
                'sentiment_score': sentiment_data.get('score', 0),
                'buzz': buzz_data.get('buzz', 0),
                'timestamp': get_ist_now(),
            }
            
            # Cache the result
            self._cache.set(cache_key, result, CACHE_SENTIMENT_SECONDS)
            
            return result
            
        except FinnhubAPIError:
            # For symbols without sentiment, analyze news headlines
            return self._analyze_news_sentiment(symbol)
        except Exception as e:
            logger.error(f"Error fetching sentiment for {symbol}: {e}")
            return self._get_default_sentiment(symbol)
    
    def _analyze_news_sentiment(self, symbol: str) -> Dict:
        """
        Analyze sentiment from news headlines when official sentiment unavailable.
        
        Uses simple keyword-based sentiment analysis.
        """
        try:
            news = self.get_company_news(symbol)
            
            if not news:
                return self._get_default_sentiment(symbol)
            
            # Simple sentiment keywords
            bullish_words = [
                'surge', 'rally', 'gain', 'rise', 'jump', 'soar', 'high',
                'bullish', 'buy', 'upgrade', 'growth', 'profit', 'beat',
                'record', 'strong', 'positive', 'optimistic', 'boost'
            ]
            bearish_words = [
                'fall', 'drop', 'decline', 'slip', 'crash', 'plunge', 'low',
                'bearish', 'sell', 'downgrade', 'loss', 'miss', 'weak',
                'negative', 'concern', 'fear', 'risk', 'cut'
            ]
            
            bullish_count = 0
            bearish_count = 0
            
            for article in news:
                text = (article.get('headline', '') + ' ' + article.get('summary', '')).lower()
                
                for word in bullish_words:
                    if word in text:
                        bullish_count += 1
                        
                for word in bearish_words:
                    if word in text:
                        bearish_count += 1
            
            total = bullish_count + bearish_count
            if total == 0:
                return self._get_default_sentiment(symbol)
            
            bullish_pct = (bullish_count / total) * 100
            bearish_pct = (bearish_count / total) * 100
            
            # Score from -1 (very bearish) to 1 (very bullish)
            score = (bullish_count - bearish_count) / total
            
            return {
                'symbol': symbol.upper(),
                'bullish_percent': round(bullish_pct, 1),
                'bearish_percent': round(bearish_pct, 1),
                'articles_analyzed': len(news),
                'sentiment_score': round(score, 2),
                'buzz': min(len(news) / 10, 1.0),  # Normalize to 0-1
                'timestamp': get_ist_now(),
                '_analyzed': True,  # Flag that this was analyzed, not official
            }
            
        except Exception as e:
            logger.error(f"Error analyzing sentiment for {symbol}: {e}")
            return self._get_default_sentiment(symbol)
    
    def _get_default_sentiment(self, symbol: str) -> Dict:
        """Return neutral default sentiment."""
        return {
            'symbol': symbol.upper(),
            'bullish_percent': 50.0,
            'bearish_percent': 50.0,
            'articles_analyzed': 0,
            'sentiment_score': 0.0,
            'buzz': 0.0,
            'timestamp': get_ist_now(),
            '_default': True,
        }
    
    # ══════════════════════════════════════════════════════
    # UTILITY METHODS
    # ══════════════════════════════════════════════════════
    
    def get_rate_limit_status(self) -> Dict:
        """Get current rate limit status."""
        return {
            'remaining_calls': self._rate_limiter.remaining_calls(),
            'max_calls': RATE_LIMIT_CALLS,
            'window_seconds': RATE_LIMIT_WINDOW,
        }
    
    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        logger.info("Finnhub cache cleared")
    
    def is_configured(self) -> bool:
        """Check if API key is configured."""
        return bool(self.api_key)


# ══════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ══════════════════════════════════════════════════════════

_client_instance: Optional[FinnhubClient] = None


def get_finnhub_client() -> FinnhubClient:
    """Get singleton Finnhub client instance."""
    global _client_instance
    
    if _client_instance is None:
        try:
            from config.settings import settings
            _client_instance = FinnhubClient(api_key=settings.FINNHUB_API_KEY)
        except Exception as e:
            logger.warning(f"Could not load settings: {e}")
            _client_instance = FinnhubClient()
    
    return _client_instance


# ══════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  FINNHUB CLIENT - TEST")
    print("=" * 60)
    
    # Load settings
    try:
        from config.settings import settings
        api_key = settings.FINNHUB_API_KEY
    except Exception as e:
        print(f"\n  ⚠️  Could not load settings: {e}")
        api_key = ""
    
    client = FinnhubClient(api_key)
    
    print(f"\n  API Key:      {'✅ Set (' + api_key[:10] + '...)' if api_key else '❌ Not set'}")
    print(f"  Configured:   {'✅ Yes' if client.is_configured() else '❌ No'}")
    
    if not client.is_configured():
        print("\n  ⚠️  Finnhub API key required for testing")
        print("     Get free key at: https://finnhub.io/")
        print("\n" + "=" * 60 + "\n")
        exit()
    
    # Test market news
    print("\n" + "-" * 60)
    print("  Testing get_market_news()...")
    try:
        news = client.get_market_news()
        print(f"  ✅ Fetched {len(news)} articles")
        if news:
            print(f"\n  Latest Headlines:")
            for article in news[:3]:
                headline = article['headline'][:60] + "..." if len(article['headline']) > 60 else article['headline']
                print(f"    • {headline}")
                print(f"      Source: {article['source']} | {article['datetime'].strftime('%Y-%m-%d %H:%M')}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # Test Indian market news
    print("\n" + "-" * 60)
    print("  Testing get_indian_market_news()...")
    try:
        india_news = client.get_indian_market_news(limit=5)
        print(f"  ✅ Found {len(india_news)} India-related articles")
        for article in india_news[:2]:
            headline = article['headline'][:55] + "..." if len(article['headline']) > 55 else article['headline']
            print(f"    • {headline}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # Test company news (US stock for demo)
    print("\n" + "-" * 60)
    print("  Testing get_company_news('AAPL')...")
    try:
        company_news = client.get_company_news('AAPL')
        print(f"  ✅ Fetched {len(company_news)} articles for AAPL")
        if company_news:
            article = company_news[0]
            headline = article['headline'][:50] + "..." if len(article['headline']) > 50 else article['headline']
            print(f"    Latest: {headline}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # Test sentiment
    print("\n" + "-" * 60)
    print("  Testing get_sentiment('AAPL')...")
    try:
        sentiment = client.get_sentiment('AAPL')
        analyzed = " (analyzed)" if sentiment.get('_analyzed') else ""
        print(f"  ✅ Sentiment for AAPL{analyzed}:")
        print(f"     Bullish:  {sentiment['bullish_percent']:.1f}%")
        print(f"     Bearish:  {sentiment['bearish_percent']:.1f}%")
        print(f"     Score:    {sentiment['sentiment_score']:.2f}")
        print(f"     Articles: {sentiment['articles_analyzed']}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # Test rate limit status
    print("\n" + "-" * 60)
    print("  Rate Limit Status:")
    status = client.get_rate_limit_status()
    print(f"    Remaining: {status['remaining_calls']}/{status['max_calls']} calls")
    
    # Test cache
    print("\n" + "-" * 60)
    print("  Testing cache (second request should be instant)...")
    import time
    start = time.time()
    _ = client.get_market_news()
    elapsed = time.time() - start
    print(f"  ✅ Cached request took: {elapsed*1000:.1f}ms")
    
    print("\n" + "=" * 60)
    print("  Finnhub Client Test Complete!")
    print("=" * 60 + "\n")