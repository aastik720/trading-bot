"""
Sentiment Analysis Brain for Options Trading Bot.

This brain analyzes news sentiment to determine market direction.
It uses keyword-based scoring combined with Finnhub API sentiment
to generate trading signals.

Author: Trading Bot
Phase: 8 - Additional Brains
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import re

from brains.base import BaseBrain
from config.settings import settings
from config.constants import (
    SIGNAL_BUY,
    SIGNAL_SELL,
    SIGNAL_HOLD,
    BRAIN_SENTIMENT,
    OPTION_TYPE_CALL,
    OPTION_TYPE_PUT
)
from utils.exceptions import BrainError
from utils.helpers import get_ist_now

logger = logging.getLogger(__name__)


class SentimentBrain(BaseBrain):
    """
    Sentiment Analysis Brain that analyzes news to determine market direction.
    
    This brain:
    1. Fetches recent news articles for a symbol
    2. Scores each headline/summary using keyword matching
    3. Applies recency weighting (newer = more important)
    4. Optionally blends with Finnhub API sentiment
    5. Generates BUY/SELL/HOLD signals based on overall sentiment
    
    Attributes:
        name: Brain identifier ('sentiment')
        weight: Voting weight in coordinator (0.35)
    """
    
    # ============== KEYWORD DICTIONARIES ==============
    
    # Strong Positive Keywords (+3)
    STRONG_POSITIVE = [
        'surge', 'soar', 'rally', 'breakout', 'record high', 'all time high',
        'all-time high', 'massive gains', 'boom', 'skyrocket', 'skyrocketing',
        'tremendous', 'exceptional', 'blockbuster', 'stellar'
    ]
    
    # Medium Positive Keywords (+2)
    MEDIUM_POSITIVE = [
        'rise', 'rising', 'gain', 'gains', 'growth', 'profit', 'profits',
        'beat', 'beats', 'beating', 'upgrade', 'upgraded', 'bullish',
        'strong', 'outperform', 'outperforming', 'recovery', 'recovering',
        'uptick', 'momentum', 'positive', 'upbeat', 'robust', 'solid',
        'impressive', 'exceeds', 'exceeded', 'surpass', 'surpasses'
    ]
    
    # Mild Positive Keywords (+1)
    MILD_POSITIVE = [
        'up', 'higher', 'improve', 'improves', 'improving', 'advance',
        'advancing', 'steady', 'stable', 'optimistic', 'confident',
        'confidence', 'support', 'supporting', 'buy', 'buying',
        'accumulate', 'accumulation', 'rebound', 'bounce'
    ]
    
    # Strong Negative Keywords (-3)
    STRONG_NEGATIVE = [
        'crash', 'crashing', 'plunge', 'plunging', 'collapse', 'collapsing',
        'crisis', 'panic', 'panicking', 'catastrophe', 'catastrophic',
        'devastating', 'devastation', 'freefall', 'free-fall', 'meltdown',
        'disaster', 'disastrous', 'bloodbath', 'carnage'
    ]
    
    # Medium Negative Keywords (-2)
    MEDIUM_NEGATIVE = [
        'fall', 'falling', 'drop', 'dropping', 'decline', 'declining',
        'loss', 'losses', 'miss', 'misses', 'missing', 'downgrade',
        'downgraded', 'bearish', 'weak', 'weakness', 'underperform',
        'underperforming', 'selloff', 'sell-off', 'correction',
        'negative', 'concern', 'concerns', 'fear', 'fears', 'worried',
        'slump', 'slumping', 'tumble', 'tumbling'
    ]
    
    # Mild Negative Keywords (-1)
    MILD_NEGATIVE = [
        'down', 'lower', 'slip', 'slipping', 'dip', 'dipping',
        'cautious', 'caution', 'uncertain', 'uncertainty', 'volatile',
        'volatility', 'risk', 'risks', 'risky', 'pressure', 'pressured',
        'sell', 'selling', 'retreat', 'retreating', 'ease', 'easing',
        'soften', 'softening', 'muted', 'subdued'
    ]
    
    # India-Specific Positive Keywords (+2)
    INDIA_POSITIVE = [
        'rbi rate cut', 'rbi cuts', 'rate cut', 'fii buying', 'fii inflow',
        'fpi buying', 'fpi inflow', 'gdp growth', 'reform', 'reforms',
        'disinvestment', 'nifty high', 'sensex high', 'nifty record',
        'sensex record', 'rupee strengthens', 'rupee gains', 'crude falls',
        'oil falls', 'monsoon normal', 'good monsoon', 'gst collection',
        'tax collection', 'infrastructure', 'make in india', 'fdi inflow'
    ]
    
    # India-Specific Negative Keywords (-2)
    INDIA_NEGATIVE = [
        'rbi rate hike', 'rbi hikes', 'rate hike', 'fii selling', 'fii outflow',
        'fpi selling', 'fpi outflow', 'inflation high', 'inflation rises',
        'rupee fall', 'rupee falls', 'rupee weakens', 'crude oil rise',
        'crude rises', 'oil rises', 'nifty fall', 'nifty falls', 'sensex fall',
        'sensex falls', 'current account deficit', 'fiscal deficit',
        'trade deficit', 'bad monsoon', 'drought', 'lockdown', 'shutdown'
    ]
    
    # Sentiment thresholds
    BULLISH_THRESHOLD = 30
    BEARISH_THRESHOLD = -30
    
    # Confidence calculation divisor
    CONFIDENCE_DIVISOR = 50
    
    # ══════════════════════════════════════════════════════════
    # FIX 1: Corrected __init__ method
    # ══════════════════════════════════════════════════════════
    
    def __init__(self):
        """Initialize the Sentiment Brain."""
        # Get weight from settings
        weight = getattr(settings, 'BRAIN_WEIGHT_SENTIMENT', 0.35)
        
        # FIX: Pass name and weight to parent class
        super().__init__(name=BRAIN_SENTIMENT, weight=weight)
        
        # Pre-compile regex patterns for better performance
        self._compile_patterns()
        
        logger.info(f"SentimentBrain initialized with weight: {self._weight}")
    
    def _compile_patterns(self) -> None:
        """
        Pre-compile regex patterns for keyword matching.
        Uses word boundaries for accurate matching.
        """
        self._positive_patterns = {}
        self._negative_patterns = {}
        
        # Compile strong positive patterns
        for keyword in self.STRONG_POSITIVE:
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            self._positive_patterns[keyword] = (pattern, 3)
        
        # Compile medium positive patterns
        for keyword in self.MEDIUM_POSITIVE:
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            self._positive_patterns[keyword] = (pattern, 2)
        
        # Compile mild positive patterns
        for keyword in self.MILD_POSITIVE:
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            self._positive_patterns[keyword] = (pattern, 1)
        
        # Compile India-specific positive patterns
        for keyword in self.INDIA_POSITIVE:
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            self._positive_patterns[keyword] = (pattern, 2)
        
        # Compile strong negative patterns
        for keyword in self.STRONG_NEGATIVE:
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            self._negative_patterns[keyword] = (pattern, -3)
        
        # Compile medium negative patterns
        for keyword in self.MEDIUM_NEGATIVE:
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            self._negative_patterns[keyword] = (pattern, -2)
        
        # Compile mild negative patterns
        for keyword in self.MILD_NEGATIVE:
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            self._negative_patterns[keyword] = (pattern, -1)
        
        # Compile India-specific negative patterns
        for keyword in self.INDIA_NEGATIVE:
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            self._negative_patterns[keyword] = (pattern, -2)
        
        logger.debug(f"Compiled {len(self._positive_patterns)} positive patterns")
        logger.debug(f"Compiled {len(self._negative_patterns)} negative patterns")
    
    # ══════════════════════════════════════════════════════════
    # MAIN ANALYZE METHOD
    # ══════════════════════════════════════════════════════════
    
    def analyze(self, symbol: str, market_data: Any) -> Dict:
        """
        Analyze news sentiment for a symbol and generate trading signal.
        
        Args:
            symbol: Trading symbol (e.g., 'NIFTY', 'BANKNIFTY')
            market_data: MarketData instance for fetching news
            
        Returns:
            dict: Signal with action, confidence, reasoning, indicators
            
        Raises:
            BrainError: If analysis fails critically
        """
        logger.info(f"SentimentBrain analyzing {symbol}")
        
        try:
            # Step 1: Fetch news articles
            articles = self._fetch_news(symbol, market_data)
            
            if not articles:
                logger.warning(f"No news articles found for {symbol}")
                # FIX 2: Use correct parameter name 'option_recommendation'
                return self._create_signal(
                    symbol=symbol,
                    action=SIGNAL_HOLD,
                    confidence=0.3,
                    reasoning="No recent news available for sentiment analysis",
                    indicators={
                        'sentiment_score': 0,
                        'positive_count': 0,
                        'negative_count': 0,
                        'total_articles': 0,
                        'top_headline': None,
                        'finnhub_sentiment': None
                    },
                    option_recommendation=None  # FIX: Correct parameter name
                )
            
            # Step 2 & 3: Score articles with recency weighting
            scored_articles = self._score_articles(articles)
            
            # Step 4: Calculate keyword-based sentiment
            keyword_sentiment = self._calculate_keyword_sentiment(scored_articles)
            
            # Step 5: Try to get Finnhub API sentiment
            api_sentiment = self._fetch_api_sentiment(symbol, market_data)
            
            # Step 6: Blend sentiments
            final_sentiment = self._blend_sentiments(keyword_sentiment, api_sentiment)
            
            # Step 7: Calculate metrics
            positive_count = sum(1 for a in scored_articles if a['score'] > 0)
            negative_count = sum(1 for a in scored_articles if a['score'] < 0)
            top_headlines = self._get_top_headlines(scored_articles, count=3)
            
            # Step 8: Generate signal
            action, confidence, option_rec = self._determine_signal(final_sentiment)
            
            # Step 9: Build reasoning
            reasoning = self._build_reasoning(
                final_sentiment, positive_count, negative_count,
                len(articles), top_headlines, api_sentiment
            )
            
            # Step 10: Create and return signal
            # FIX 2: Use correct parameter name 'option_recommendation'
            signal = self._create_signal(
                symbol=symbol,
                action=action,
                confidence=confidence,
                reasoning=reasoning,
                indicators={
                    'sentiment_score': round(final_sentiment, 2),
                    'keyword_sentiment': round(keyword_sentiment, 2),
                    'positive_count': positive_count,
                    'negative_count': negative_count,
                    'neutral_count': len(articles) - positive_count - negative_count,
                    'total_articles': len(articles),
                    'top_headline': top_headlines[0] if top_headlines else None,
                    'top_headlines': top_headlines,
                    'finnhub_sentiment': api_sentiment
                },
                option_recommendation=option_rec  # FIX: Correct parameter name
            )
            
            logger.info(
                f"SentimentBrain signal for {symbol}: "
                f"{action} with confidence {confidence:.2%}, "
                f"sentiment score: {final_sentiment:.2f}"
            )
            
            return signal
            
        except BrainError:
            raise
        except Exception as e:
            logger.error(f"SentimentBrain analysis failed for {symbol}: {e}")
            raise BrainError(f"Sentiment analysis failed: {str(e)}")
        # ══════════════════════════════════════════════════════════
    # NEWS FETCHING METHODS
    # ══════════════════════════════════════════════════════════
    
    def _fetch_news(self, symbol: str, market_data: Any) -> List[Dict]:
        """
        Fetch news articles from market data source.
        
        Args:
            symbol: Trading symbol
            market_data: MarketData instance
            
        Returns:
            List of article dictionaries with headline, summary, datetime, etc.
        """
        try:
            # Check if market_data has get_news method
            if not hasattr(market_data, 'get_news'):
                logger.debug("MarketData does not have get_news method")
                return []
            
            articles = market_data.get_news(symbol, limit=20)
            
            if articles is None:
                return []
            
            # Validate and clean articles
            cleaned_articles = []
            for article in articles:
                if not isinstance(article, dict):
                    continue
                
                # Extract fields with fallbacks
                headline = article.get('headline') or article.get('title') or ''
                summary = article.get('summary') or article.get('description') or ''
                
                # Skip empty articles
                if not headline and not summary:
                    continue
                
                # Parse datetime
                article_datetime = self._parse_article_datetime(article)
                
                cleaned_articles.append({
                    'headline': str(headline).strip(),
                    'summary': str(summary).strip(),
                    'source': article.get('source', 'unknown'),
                    'datetime': article_datetime,
                    'url': article.get('url', '')
                })
            
            logger.debug(f"Fetched {len(cleaned_articles)} valid articles for {symbol}")
            return cleaned_articles
            
        except Exception as e:
            logger.warning(f"Failed to fetch news for {symbol}: {e}")
            return []
    
    def _parse_article_datetime(self, article: Dict) -> datetime:
        """
        Parse article datetime from various formats.
        
        Args:
            article: Article dictionary
            
        Returns:
            datetime in IST timezone
        """
        now = get_ist_now()
        
        # Try various datetime fields
        dt_value = (
            article.get('datetime') or 
            article.get('published_at') or 
            article.get('publishedAt') or
            article.get('date') or
            article.get('timestamp')
        )
        
        if dt_value is None:
            return now
        
        # If already datetime object
        if isinstance(dt_value, datetime):
            return dt_value
        
        # If Unix timestamp (integer or float)
        if isinstance(dt_value, (int, float)):
            try:
                return datetime.fromtimestamp(dt_value)
            except (OSError, ValueError):
                return now
        
        # If string, try to parse
        if isinstance(dt_value, str):
            formats = [
                '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%dT%H:%M:%S.%fZ',
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d',
                '%d-%m-%Y %H:%M:%S',
                '%d/%m/%Y %H:%M:%S'
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(dt_value, fmt)
                except ValueError:
                    continue
        
        return now
    
    # ══════════════════════════════════════════════════════════
    # SCORING METHODS
    # ══════════════════════════════════════════════════════════
    
    def _score_articles(self, articles: List[Dict]) -> List[Dict]:
        """
        Score each article based on keyword sentiment and recency.
        
        Args:
            articles: List of article dictionaries
            
        Returns:
            List of articles with 'score' and 'recency_weight' added
        """
        scored_articles = []
        
        for article in articles:
            # Combine headline and summary for scoring
            text = f"{article['headline']} {article['summary']}"
            
            # Get keyword score
            keyword_score = self._score_text(text)
            
            # Get recency weight
            recency_weight = self._calculate_recency_weight(article['datetime'])
            
            # Calculate weighted score
            weighted_score = keyword_score * recency_weight
            
            scored_articles.append({
                **article,
                'raw_score': keyword_score,
                'recency_weight': recency_weight,
                'score': weighted_score
            })
        
        return scored_articles
    
    def _score_text(self, text: str) -> float:
        """
        Score text based on keyword matching.
        
        Args:
            text: Text to analyze
            
        Returns:
            Sentiment score (positive = bullish, negative = bearish)
        """
        if not text:
            return 0.0
        
        score = 0.0
        matched_keywords = []
        
        # Check positive patterns
        for keyword, (pattern, weight) in self._positive_patterns.items():
            matches = pattern.findall(text)
            if matches:
                score += weight * len(matches)
                matched_keywords.append((keyword, weight, len(matches)))
        
        # Check negative patterns
        for keyword, (pattern, weight) in self._negative_patterns.items():
            matches = pattern.findall(text)
            if matches:
                score += weight * len(matches)  # weight is already negative
                matched_keywords.append((keyword, weight, len(matches)))
        
        logger.debug(f"Text score: {score}, matched: {matched_keywords[:5]}")
        
        return score
    
    def _calculate_recency_weight(self, article_datetime: datetime) -> float:
        """
        Calculate recency weight for an article.
        
        More recent articles get higher weight:
        - Last 1 hour: 2.0x
        - Last 6 hours: 1.5x
        - Last 24 hours: 1.0x
        - Older: 0.5x
        
        Args:
            article_datetime: Article publish datetime
            
        Returns:
            Weight multiplier (0.5 to 2.0)
        """
        now = get_ist_now()
        
        # Handle timezone-naive datetimes
        if article_datetime.tzinfo is None:
            article_dt = article_datetime
            now_naive = now.replace(tzinfo=None) if now.tzinfo else now
        else:
            article_dt = article_datetime.replace(tzinfo=None)
            now_naive = now.replace(tzinfo=None) if now.tzinfo else now
        
        try:
            age = now_naive - article_dt
        except TypeError:
            return 1.0
        
        hours_old = age.total_seconds() / 3600
        
        if hours_old < 0:
            return 2.0
        elif hours_old <= 1:
            return 2.0
        elif hours_old <= 6:
            return 1.5
        elif hours_old <= 24:
            return 1.0
        else:
            return 0.5
    
    def _calculate_keyword_sentiment(self, scored_articles: List[Dict]) -> float:
        """
        Calculate overall keyword-based sentiment score.
        
        Args:
            scored_articles: List of scored article dictionaries
            
        Returns:
            Normalized sentiment score (-100 to +100)
        """
        if not scored_articles:
            return 0.0
        
        total_score = sum(article['score'] for article in scored_articles)
        article_count = len(scored_articles)
        normalized = self._normalize_score(total_score, article_count)
        
        logger.debug(
            f"Keyword sentiment: total={total_score:.2f}, "
            f"articles={article_count}, normalized={normalized:.2f}"
        )
        
        return normalized
    
    def _normalize_score(self, raw_score: float, article_count: int) -> float:
        """
        Normalize raw sentiment score to -100 to +100 range.
        
        Args:
            raw_score: Sum of all article scores
            article_count: Number of articles analyzed
            
        Returns:
            Normalized score (-100 to +100)
        """
        if article_count == 0:
            return 0.0
        
        avg_score = raw_score / article_count
        normalized = avg_score * 10
        
        return max(-100, min(100, normalized))
    
    # ══════════════════════════════════════════════════════════
    # API SENTIMENT METHODS
    # ══════════════════════════════════════════════════════════
    
    def _fetch_api_sentiment(self, symbol: str, market_data: Any) -> Optional[float]:
        """
        Fetch sentiment from Finnhub API.
        
        Args:
            symbol: Trading symbol
            market_data: MarketData instance
            
        Returns:
            Sentiment score (-100 to +100) or None if unavailable
        """
        try:
            if not hasattr(market_data, 'get_sentiment'):
                logger.debug("MarketData does not have get_sentiment method")
                return None
            
            sentiment_data = market_data.get_sentiment(symbol)
            
            if sentiment_data is None:
                return None
            
            if isinstance(sentiment_data, dict):
                sentiment = sentiment_data.get('sentiment', {})
                
                bullish = sentiment.get('bullishPercent', 0.5)
                bearish = sentiment.get('bearishPercent', 0.5)
                
                api_score = (bullish - bearish) * 100
                
                logger.debug(f"Finnhub sentiment for {symbol}: {api_score:.2f}")
                return api_score
            
            return None
            
        except Exception as e:
            logger.warning(f"Failed to fetch Finnhub sentiment for {symbol}: {e}")
            return None
    
    def _blend_sentiments(
        self, 
        keyword_score: float, 
        api_score: Optional[float]
    ) -> float:
        """
        Blend keyword-based and API-based sentiment scores.
        
        Args:
            keyword_score: Keyword-based sentiment (-100 to +100)
            api_score: API-based sentiment (-100 to +100) or None
            
        Returns:
            Blended sentiment score (-100 to +100)
        """
        if api_score is None:
            logger.debug("Using keyword sentiment only (no API data)")
            return keyword_score
        
        blended = (keyword_score * 0.5) + (api_score * 0.5)
        
        logger.debug(
            f"Blended sentiment: keyword={keyword_score:.2f}, "
            f"api={api_score:.2f}, blended={blended:.2f}"
        )
        
        return blended
    
    # ══════════════════════════════════════════════════════════
    # HELPER METHODS
    # ══════════════════════════════════════════════════════════
    
    def _get_top_headlines(
        self, 
        scored_articles: List[Dict], 
        count: int = 3
    ) -> List[str]:
        """
        Get the most influential headlines (highest absolute score).
        
        Args:
            scored_articles: List of scored article dictionaries
            count: Number of headlines to return
            
        Returns:
            List of headline strings
        """
        if not scored_articles:
            return []
        
        sorted_articles = sorted(
            scored_articles,
            key=lambda x: abs(x['score']),
            reverse=True
        )
        
        headlines = []
        for article in sorted_articles[:count]:
            headline = article.get('headline', '')
            if headline:
                if len(headline) > 100:
                    headline = headline[:97] + '...'
                headlines.append(headline)
        
        return headlines
    
    def _determine_signal(
        self, 
        sentiment_score: float
    ) -> Tuple[str, float, Optional[Dict]]:
        """
        Determine trading signal from sentiment score.
        
        Args:
            sentiment_score: Overall sentiment (-100 to +100)
            
        Returns:
            Tuple of (action, confidence, option_recommendation)
        """
        raw_confidence = abs(sentiment_score) / self.CONFIDENCE_DIVISOR
        confidence = min(1.0, max(0.0, raw_confidence))
        
        if sentiment_score >= self.BULLISH_THRESHOLD:
            action = SIGNAL_BUY
            option_rec = {
                'type': OPTION_TYPE_CALL,
                'strike_preference': 'ATM' if confidence >= 0.70 else 'OTM1',
                'expiry': 'WEEKLY'
            }
            
        elif sentiment_score <= self.BEARISH_THRESHOLD:
            action = SIGNAL_SELL
            option_rec = {
                'type': OPTION_TYPE_PUT,
                'strike_preference': 'ATM' if confidence >= 0.70 else 'OTM1',
                'expiry': 'WEEKLY'
            }
            
        else:
            action = SIGNAL_HOLD
            option_rec = None
            confidence = min(confidence, 0.5)
        
        return action, confidence, option_rec
    
    def _build_reasoning(
        self,
        sentiment_score: float,
        positive_count: int,
        negative_count: int,
        total_articles: int,
        top_headlines: List[str],
        api_sentiment: Optional[float]
    ) -> str:
        """
        Build human-readable reasoning for the signal.
        
        Args:
            sentiment_score: Overall sentiment score
            positive_count: Number of positive articles
            negative_count: Number of negative articles
            total_articles: Total articles analyzed
            top_headlines: Most influential headlines
            api_sentiment: API sentiment if available
            
        Returns:
            Reasoning string
        """
        if sentiment_score > 0:
            direction = "BULLISH"
        elif sentiment_score < 0:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"
        
        parts = [
            f"Sentiment Analysis: {direction} (score: {sentiment_score:.1f}/100)",
            f"Analyzed {total_articles} articles: {positive_count} positive, {negative_count} negative"
        ]
        
        if api_sentiment is not None:
            api_direction = "bullish" if api_sentiment > 0 else "bearish" if api_sentiment < 0 else "neutral"
            parts.append(f"Finnhub API: {api_direction} ({api_sentiment:.1f})")
        
        if top_headlines:
            parts.append(f"Top: {top_headlines[0]}")
        
        return " | ".join(parts)


# ══════════════════════════════════════════════════════════
# TESTING
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    """
    Test the SentimentBrain with mock data.
    
    Run with: python -m brains.sentiment
    """
    import sys
    
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 60)
    print("SENTIMENT BRAIN TEST")
    print("=" * 60)
    
    # Create mock market data
    class MockMarketData:
        """Mock market data for testing."""
        
        def get_news(self, symbol: str, limit: int = 20) -> List[Dict]:
            """Return mock news articles."""
            now = datetime.now()
            
            return [
                {
                    'headline': 'Nifty surges to record high as FII buying continues',
                    'summary': 'The index rallied strongly with massive gains across all sectors.',
                    'source': 'Economic Times',
                    'datetime': now - timedelta(hours=1),
                    'url': 'https://example.com/1'
                },
                {
                    'headline': 'RBI keeps rates unchanged, signals growth focus',
                    'summary': 'Central bank maintains accommodative stance, positive for markets.',
                    'source': 'Mint',
                    'datetime': now - timedelta(hours=3),
                    'url': 'https://example.com/2'
                },
                {
                    'headline': 'IT stocks rise on strong quarterly results',
                    'summary': 'Tech sector outperforms as companies beat estimates.',
                    'source': 'Moneycontrol',
                    'datetime': now - timedelta(hours=5),
                    'url': 'https://example.com/3'
                },
                {
                    'headline': 'Global markets cautious ahead of Fed decision',
                    'summary': 'Investors remain uncertain about rate trajectory.',
                    'source': 'Reuters',
                    'datetime': now - timedelta(hours=8),
                    'url': 'https://example.com/4'
                },
                {
                    'headline': 'Banking stocks slip on profit booking',
                    'summary': 'Some correction seen after recent rally.',
                    'source': 'Business Standard',
                    'datetime': now - timedelta(hours=12),
                    'url': 'https://example.com/5'
                },
                {
                    'headline': 'Oil prices decline, positive for Indian markets',
                    'summary': 'Crude falls below $80, easing inflation concerns.',
                    'source': 'CNBC',
                    'datetime': now - timedelta(hours=2),
                    'url': 'https://example.com/6'
                }
            ]
        
        def get_sentiment(self, symbol: str) -> Optional[Dict]:
            """Return mock Finnhub sentiment."""
            return {
                'buzz': {'articlesInLastWeek': 50},
                'sentiment': {
                    'bullishPercent': 0.65,
                    'bearishPercent': 0.35
                }
            }
    
    # Run test
    try:
        brain = SentimentBrain()
        mock_data = MockMarketData()
        
        print(f"\nBrain Name: {brain.get_name()}")
        print(f"Brain Weight: {brain.get_weight()}")
        print("-" * 60)
        
        # Test with mock data
        signal = brain.analyze('NIFTY', mock_data)
        
        print(f"\n{'='*60}")
        print("SIGNAL RESULT")
        print(f"{'='*60}")
        print(f"Symbol: {signal['symbol']}")
        print(f"Action: {signal['action']}")
        print(f"Confidence: {signal['confidence']:.2%}")
        print(f"Brain: {signal['brain']}")
        print(f"\nReasoning: {signal['reasoning']}")
        print(f"\nIndicators:")
        for key, value in signal['indicators'].items():
            if key != 'top_headlines':
                print(f"  {key}: {value}")
        
        if signal['option_recommendation']:
            print(f"\nOption Recommendation:")
            for key, value in signal['option_recommendation'].items():
                print(f"  {key}: {value}")
        
        print(f"\n{'='*60}")
        print("TEST PASSED ✓")
        print(f"{'='*60}")
        
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Edge case tests
    print("\n" + "=" * 60)
    print("EDGE CASE TESTS")
    print("=" * 60)
    
    # Test 1: No news
    class EmptyNewsMarketData:
        def get_news(self, symbol, limit=20):
            return []
        def get_sentiment(self, symbol):
            return None
    
    try:
        signal = brain.analyze('NIFTY', EmptyNewsMarketData())
        assert signal['action'] == SIGNAL_HOLD
        assert signal['indicators']['total_articles'] == 0
        print("✓ Empty news test passed")
    except Exception as e:
        print(f"✗ Empty news test failed: {e}")
    
    # Test 2: Very negative news
    class BearishNewsMarketData:
        def get_news(self, symbol, limit=20):
            return [
                {
                    'headline': 'Markets crash as panic selling intensifies',
                    'summary': 'Catastrophic collapse in indices, crisis deepens. Meltdown continues.',
                    'source': 'Test',
                    'datetime': datetime.now(),
                    'url': ''
                },
                {
                    'headline': 'FII selling triggers bloodbath in markets',
                    'summary': 'Devastating losses across sectors. Investors flee.',
                    'source': 'Test',
                    'datetime': datetime.now(),
                    'url': ''
                }
            ]
        def get_sentiment(self, symbol):
            return None
    
    try:
        signal = brain.analyze('NIFTY', BearishNewsMarketData())
        assert signal['action'] == SIGNAL_SELL
        assert signal['indicators']['sentiment_score'] < 0
        print("✓ Bearish news test passed")
    except Exception as e:
        print(f"✗ Bearish news test failed: {e}")
    
    # Test 3: Very bullish news
    class BullishNewsMarketData:
        def get_news(self, symbol, limit=20):
            return [
                {
                    'headline': 'Markets surge to all-time high with massive gains',
                    'summary': 'Record breaking rally continues. FII buying intensifies.',
                    'source': 'Test',
                    'datetime': datetime.now(),
                    'url': ''
                },
                {
                    'headline': 'Nifty soars as stellar results boost sentiment',
                    'summary': 'Exceptional performance. Bulls dominate trading.',
                    'source': 'Test',
                    'datetime': datetime.now(),
                    'url': ''
                }
            ]
        def get_sentiment(self, symbol):
            return None
    
    try:
        signal = brain.analyze('NIFTY', BullishNewsMarketData())
        assert signal['action'] == SIGNAL_BUY
        assert signal['indicators']['sentiment_score'] > 0
        print("✓ Bullish news test passed")
    except Exception as e:
        print(f"✗ Bullish news test failed: {e}")
    
    # Test 4: API failure
    class FailingAPIMarketData:
        def get_news(self, symbol, limit=20):
            return [
                {
                    'headline': 'Markets surge on positive news',
                    'summary': 'Strong rally continues',
                    'source': 'Test',
                    'datetime': datetime.now(),
                    'url': ''
                }
            ]
        def get_sentiment(self, symbol):
            raise Exception("API Error")
    
    try:
        signal = brain.analyze('NIFTY', FailingAPIMarketData())
        assert signal is not None
        print("✓ API failure test passed")
    except Exception as e:
        print(f"✗ API failure test failed: {e}")
    
    # Test 5: No get_news method
    class NoMethodsMarketData:
        pass
    
    try:
        signal = brain.analyze('NIFTY', NoMethodsMarketData())
        assert signal['action'] == SIGNAL_HOLD
        print("✓ No methods test passed")
    except Exception as e:
        print(f"✗ No methods test failed: {e}")
    
    # Test 6: Verify inherited methods work
    print("\n" + "-" * 60)
    print("INHERITED METHOD TESTS")
    print("-" * 60)
    
    try:
        assert brain.get_name() == 'sentiment'
        print("✓ get_name() works")
        
        assert 0 <= brain.get_weight() <= 1
        print("✓ get_weight() works")
        
        stats = brain.get_stats()
        assert 'name' in stats
        assert 'weight' in stats
        assert 'analysis_count' in stats
        print("✓ get_stats() works")
        
        assert brain.is_above_threshold(0.70) == True
        assert brain.is_above_threshold(0.50) == False
        print("✓ is_above_threshold() works")
        
        assert brain.is_strong_signal(0.80) == True
        assert brain.is_strong_signal(0.60) == False
        print("✓ is_strong_signal() works")
        
    except Exception as e:
        print(f"✗ Inherited method test failed: {e}")
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED ✓")
    print("=" * 60)    