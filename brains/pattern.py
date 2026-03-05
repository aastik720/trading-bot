"""
Chart Pattern Recognition Brain for Options Trading Bot.

This brain analyzes price action and chart patterns to predict market direction.
It detects support/resistance, trends, breakouts, and candlestick patterns.

Author: Trading Bot
Phase: 8 - Additional Brains
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import pandas as pd
import numpy as np

from brains.base import BaseBrain
from config.settings import settings
from config.constants import (
    SIGNAL_BUY,
    SIGNAL_SELL,
    SIGNAL_HOLD,
    BRAIN_PATTERN,
    OPTION_TYPE_CALL,
    OPTION_TYPE_PUT,
    SMA_SHORT,
    SMA_LONG,
    BOLLINGER_PERIOD
)
from utils.exceptions import BrainError
from utils.helpers import get_ist_now

logger = logging.getLogger(__name__)


class PatternBrain(BaseBrain):
    """
    Chart Pattern Recognition Brain that analyzes price action for signals.
    
    This brain detects:
    1. Support and Resistance levels
    2. Trend direction (uptrend/downtrend)
    3. Breakouts (above resistance / below support)
    4. Candlestick patterns (engulfing, hammer, doji, etc.)
    5. Price patterns (double top/bottom)
    6. Volume patterns (accumulation/distribution)
    
    Attributes:
        name: Brain identifier ('pattern')
        weight: Voting weight in coordinator (0.25)
        
    Example:
        >>> brain = PatternBrain()
        >>> signal = brain.analyze('NIFTY', market_data)
        >>> print(signal['action'])  # 'BUY', 'SELL', or 'HOLD'
        >>> print(signal['indicators']['patterns_found'])
    """
    
    # Minimum candles required for analysis
    MIN_CANDLES_REQUIRED = 20
    OPTIMAL_CANDLES = 50
    
    # Score thresholds
    BULLISH_THRESHOLD = 35
    BEARISH_THRESHOLD = -35
    
    # Maximum theoretical score for normalization
    MAX_SCORE = 130  # 20 + 25 + 30 + 20 + 25 + 10
    
    # Support/Resistance proximity threshold
    SR_PROXIMITY_PERCENT = 0.5  # 0.5% of price
    
    # Volume spike threshold
    VOLUME_SPIKE_MULTIPLIER = 1.5
    
    # Double top/bottom tolerance
    DOUBLE_PATTERN_TOLERANCE = 0.01  # 1% tolerance
    
    # ══════════════════════════════════════════════════════════
    # FIX 1: Corrected __init__ method
    # ══════════════════════════════════════════════════════════
    
    def __init__(self):
        """Initialize the Pattern Brain."""
        # Get weight from settings
        weight = getattr(settings, 'BRAIN_WEIGHT_PATTERN', 0.25)
        
        # FIX: Pass name and weight to parent class
        super().__init__(name=BRAIN_PATTERN, weight=weight)
        
        logger.info(f"PatternBrain initialized with weight: {self._weight}")
    
    # ══════════════════════════════════════════════════════════
    # MAIN ANALYZE METHOD
    # ══════════════════════════════════════════════════════════
    
    def analyze(self, symbol: str, market_data: Any) -> Dict:
        """
        Analyze chart patterns for a symbol and generate trading signal.
        
        This method:
        1. Fetches historical price data
        2. Identifies support and resistance levels
        3. Detects trend direction
        4. Checks for breakouts
        5. Identifies candlestick patterns
        6. Detects price patterns (double top/bottom)
        7. Analyzes volume patterns
        8. Combines all scores for final signal
        
        Args:
            symbol: Trading symbol (e.g., 'NIFTY', 'BANKNIFTY')
            market_data: MarketData instance for fetching historical data
            
        Returns:
            dict: Signal with keys:
                - signal_id: Unique identifier
                - symbol: Trading symbol
                - action: 'BUY', 'SELL', or 'HOLD'
                - confidence: 0.0 to 1.0
                - brain: 'pattern'
                - reasoning: Human-readable explanation
                - indicators: Dict of pattern metrics
                - option_recommendation: CE/PE recommendation or None
                - timestamp: Signal generation time
                
        Raises:
            BrainError: If analysis fails critically
        """
        logger.info(f"PatternBrain analyzing {symbol}")
        
        try:
            # Step 1: Fetch historical data
            df = self._fetch_historical_data(symbol, market_data)
            
            if df is None or len(df) < self.MIN_CANDLES_REQUIRED:
                candle_count = len(df) if df is not None else 0
                logger.warning(
                    f"Insufficient data for {symbol}: {candle_count} candles "
                    f"(need {self.MIN_CANDLES_REQUIRED})"
                )
                # FIX 2: Use correct parameter name 'option_recommendation'
                return self._create_signal(
                    symbol=symbol,
                    action=SIGNAL_HOLD,
                    confidence=0.3,
                    reasoning=f"Insufficient historical data ({candle_count} candles)",
                    indicators={
                        'data_points': candle_count,
                        'trend': 'unknown',
                        'support_levels': [],
                        'resistance_levels': [],
                        'breakout': None,
                        'candle_patterns_found': [],
                        'price_patterns_found': [],
                        'volume_signal': 'unknown',
                        'total_score': 0
                    },
                    option_recommendation=None  # FIX: Correct parameter name
                )
            
            # Standardize column names
            df = self._standardize_columns(df)
            
            # Get current price
            current_price = float(df['close'].iloc[-1])
            
            # Step 2: Find Support and Resistance
            support_levels, resistance_levels = self._find_support_resistance(df)
            sr_score, sr_detail = self._score_support_resistance(
                current_price, support_levels, resistance_levels
            )
            
            # Step 3: Detect Trend
            trend, trend_score, trend_detail = self._detect_trend(df)
            
            # Step 4: Detect Breakout
            breakout, breakout_score, breakout_detail = self._detect_breakout(
                df, support_levels, resistance_levels
            )
            
            # Step 5: Detect Candlestick Patterns
            candle_patterns, candle_score, candle_detail = self._detect_candle_patterns(df)
            
            # Step 6: Detect Price Patterns
            price_patterns, price_score, price_detail = self._detect_price_patterns(df)
            
            # Step 7: Analyze Volume
            volume_signal, volume_score, volume_detail = self._analyze_volume_pattern(df)
            
            # Step 8: Calculate total score
            raw_score = (
                sr_score + 
                trend_score + 
                breakout_score + 
                candle_score + 
                price_score + 
                volume_score
            )
            
            # Normalize score to -100 to +100 range
            normalized_score = self._normalize_total_score(raw_score)
            
            # Step 9: Generate signal
            action, confidence, option_rec = self._determine_signal(normalized_score)
            
            # Step 10: Build reasoning
            reasoning = self._build_reasoning(
                trend=trend,
                trend_detail=trend_detail,
                sr_detail=sr_detail,
                breakout_detail=breakout_detail,
                candle_detail=candle_detail,
                price_detail=price_detail,
                volume_detail=volume_detail,
                total_score=normalized_score
            )
            
            # Step 11: Create and return signal
            # FIX 2: Use correct parameter name 'option_recommendation'
            signal = self._create_signal(
                symbol=symbol,
                action=action,
                confidence=confidence,
                reasoning=reasoning,
                indicators={
                    'data_points': len(df),
                    'current_price': current_price,
                    'trend': trend,
                    'trend_score': trend_score,
                    'support_levels': [round(s, 2) for s in support_levels[:3]],
                    'resistance_levels': [round(r, 2) for r in resistance_levels[:3]],
                    'sr_score': sr_score,
                    'breakout': breakout,
                    'breakout_score': breakout_score,
                    'candle_patterns_found': candle_patterns,
                    'candle_score': candle_score,
                    'price_patterns_found': price_patterns,
                    'price_score': price_score,
                    'volume_signal': volume_signal,
                    'volume_score': volume_score,
                    'raw_score': raw_score,
                    'total_score': round(normalized_score, 2)
                },
                option_recommendation=option_rec  # FIX: Correct parameter name
            )
            
            logger.info(
                f"PatternBrain signal for {symbol}: "
                f"{action} with confidence {confidence:.2%}, "
                f"score: {normalized_score:.2f}"
            )
            
            return signal
            
        except BrainError:
            raise
        except Exception as e:
            logger.error(f"PatternBrain analysis failed for {symbol}: {e}")
            raise BrainError(f"Pattern analysis failed: {str(e)}")
    
    # ══════════════════════════════════════════════════════════
    # DATA METHODS
    # ══════════════════════════════════════════════════════════
    
    def _fetch_historical_data(
        self, 
        symbol: str, 
        market_data: Any
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical OHLCV data from market data source.
        
        Args:
            symbol: Trading symbol
            market_data: MarketData instance
            
        Returns:
            DataFrame with OHLCV data or None if unavailable
        """
        try:
            df = market_data.get_historical(symbol, days=self.OPTIMAL_CANDLES)
            
            if df is None or df.empty:
                return None
            
            # Ensure we have required columns
            required_columns = ['open', 'high', 'low', 'close', 'volume']
            df_columns_lower = [col.lower() for col in df.columns]
            
            # Check if all required columns exist (case-insensitive)
            for col in required_columns:
                if col not in df_columns_lower:
                    logger.warning(f"Missing column {col} in historical data")
                    return None
            
            return df
            
        except Exception as e:
            logger.warning(f"Failed to fetch historical data for {symbol}: {e}")
            return None
    
    def _standardize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize DataFrame column names to lowercase.
        
        Args:
            df: Input DataFrame
            
        Returns:
            DataFrame with lowercase column names
        """
        df = df.copy()
        df.columns = [col.lower() for col in df.columns]
        
        # FIX 3: Updated fillna syntax (deprecated method='ffill')
        df = df.ffill().bfill()
        
        # Ensure numeric types
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Drop any remaining NaN rows
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        
        return df
        # ══════════════════════════════════════════════════════════
    # SUPPORT & RESISTANCE METHODS
    # ══════════════════════════════════════════════════════════
    
    def _find_support_resistance(
        self, 
        df: pd.DataFrame, 
        window: int = 10
    ) -> Tuple[List[float], List[float]]:
        """
        Find support and resistance levels from price data.
        
        Support: Local minimums where price bounced up at least 2 times
        Resistance: Local maximums where price was rejected at least 2 times
        
        Args:
            df: OHLCV DataFrame
            window: Rolling window for finding local extremes
            
        Returns:
            Tuple of (support_levels, resistance_levels)
        """
        support_levels = []
        resistance_levels = []
        
        try:
            lows = df['low'].values
            highs = df['high'].values
            closes = df['close'].values
            
            # Find local minimums (potential support)
            for i in range(window, len(lows) - window):
                # Check if this is a local minimum
                if lows[i] == min(lows[i-window:i+window+1]):
                    support_levels.append(float(lows[i]))
            
            # Find local maximums (potential resistance)
            for i in range(window, len(highs) - window):
                # Check if this is a local maximum
                if highs[i] == max(highs[i-window:i+window+1]):
                    resistance_levels.append(float(highs[i]))
            
            # Cluster nearby levels (within 0.5% of each other)
            support_levels = self._cluster_levels(support_levels)
            resistance_levels = self._cluster_levels(resistance_levels)
            
            # Sort levels
            support_levels = sorted(support_levels, reverse=True)  # Highest first
            resistance_levels = sorted(resistance_levels)  # Lowest first
            
            logger.debug(
                f"Found {len(support_levels)} support levels, "
                f"{len(resistance_levels)} resistance levels"
            )
            
        except Exception as e:
            logger.warning(f"Error finding support/resistance: {e}")
        
        return support_levels, resistance_levels
    
    def _cluster_levels(
        self, 
        levels: List[float], 
        tolerance: float = 0.005
    ) -> List[float]:
        """
        Cluster nearby price levels together.
        
        Levels within tolerance % of each other are merged.
        Only levels with 2+ occurrences are kept.
        
        Args:
            levels: List of price levels
            tolerance: Percentage tolerance for clustering
            
        Returns:
            List of clustered levels with at least 2 touches
        """
        if not levels:
            return []
        
        sorted_levels = sorted(levels)
        clusters = []
        current_cluster = [sorted_levels[0]]
        
        for level in sorted_levels[1:]:
            # Check if level is within tolerance of cluster average
            cluster_avg = sum(current_cluster) / len(current_cluster)
            if abs(level - cluster_avg) / cluster_avg <= tolerance:
                current_cluster.append(level)
            else:
                # Save current cluster if it has 2+ levels
                if len(current_cluster) >= 2:
                    clusters.append(sum(current_cluster) / len(current_cluster))
                current_cluster = [level]
        
        # Don't forget last cluster
        if len(current_cluster) >= 2:
            clusters.append(sum(current_cluster) / len(current_cluster))
        
        return clusters
    
    def _score_support_resistance(
        self, 
        current_price: float, 
        support_levels: List[float], 
        resistance_levels: List[float]
    ) -> Tuple[int, str]:
        """
        Score based on price proximity to support/resistance.
        
        Near support = bullish (+20)
        Near resistance = bearish (-20)
        
        Args:
            current_price: Current price
            support_levels: List of support levels
            resistance_levels: List of resistance levels
            
        Returns:
            Tuple of (score, detail_string)
        """
        score = 0
        detail = "No significant S/R levels nearby"
        
        proximity_threshold = current_price * (self.SR_PROXIMITY_PERCENT / 100)
        
        # Check proximity to support
        for support in support_levels:
            if abs(current_price - support) <= proximity_threshold:
                score = 20  # Bullish - price near support
                detail = f"Price near support at {support:.2f} (bullish bounce likely)"
                break
        
        # Check proximity to resistance (overrides support if both present)
        for resistance in resistance_levels:
            if abs(current_price - resistance) <= proximity_threshold:
                score = -20  # Bearish - price near resistance
                detail = f"Price near resistance at {resistance:.2f} (bearish rejection likely)"
                break
        
        return score, detail
    
    # ══════════════════════════════════════════════════════════
    # TREND DETECTION METHODS
    # ══════════════════════════════════════════════════════════
    
    def _detect_trend(self, df: pd.DataFrame) -> Tuple[str, int, str]:
        """
        Detect current trend using SMA crossover and price action.
        
        Methods:
        1. SMA20 vs SMA50 crossover
        2. Higher highs/higher lows vs Lower lows/lower highs
        
        Args:
            df: OHLCV DataFrame
            
        Returns:
            Tuple of (trend_string, score, detail_string)
        """
        trend = "sideways"
        score = 0
        detail = "No clear trend"
        
        try:
            closes = df['close']
            highs = df['high']
            lows = df['low']
            
            # Calculate SMAs
            sma_short = SMA_SHORT if len(df) >= SMA_SHORT else len(df) // 2
            sma_long = SMA_LONG if len(df) >= SMA_LONG else len(df)
            
            sma20 = closes.rolling(window=sma_short).mean()
            sma50 = closes.rolling(window=sma_long).mean()
            
            current_sma20 = sma20.iloc[-1] if not pd.isna(sma20.iloc[-1]) else closes.iloc[-1]
            current_sma50 = sma50.iloc[-1] if not pd.isna(sma50.iloc[-1]) else closes.iloc[-1]
            
            # SMA crossover analysis
            sma_bullish = current_sma20 > current_sma50
            sma_bearish = current_sma20 < current_sma50
            
            # Price action analysis (last 10 candles)
            recent_highs = highs.tail(10).values
            recent_lows = lows.tail(10).values
            
            # Count higher highs and higher lows
            hh_count = sum(1 for i in range(1, len(recent_highs)) 
                         if recent_highs[i] > recent_highs[i-1])
            hl_count = sum(1 for i in range(1, len(recent_lows)) 
                         if recent_lows[i] > recent_lows[i-1])
            
            # Count lower lows and lower highs
            ll_count = sum(1 for i in range(1, len(recent_lows)) 
                         if recent_lows[i] < recent_lows[i-1])
            lh_count = sum(1 for i in range(1, len(recent_highs)) 
                         if recent_highs[i] < recent_highs[i-1])
            
            # Determine trend strength
            bullish_signals = (1 if sma_bullish else 0) + (1 if hh_count > 5 else 0) + (1 if hl_count > 5 else 0)
            bearish_signals = (1 if sma_bearish else 0) + (1 if ll_count > 5 else 0) + (1 if lh_count > 5 else 0)
            
            if bullish_signals >= 2:
                if bullish_signals == 3:
                    trend = "strong_uptrend"
                    score = 25
                    detail = "Strong uptrend: SMA20 > SMA50, higher highs and higher lows"
                else:
                    trend = "uptrend"
                    score = 10
                    detail = "Uptrend detected with some confirmation"
            elif bearish_signals >= 2:
                if bearish_signals == 3:
                    trend = "strong_downtrend"
                    score = -25
                    detail = "Strong downtrend: SMA20 < SMA50, lower lows and lower highs"
                else:
                    trend = "downtrend"
                    score = -10
                    detail = "Downtrend detected with some confirmation"
            else:
                trend = "sideways"
                score = 0
                detail = "Sideways/consolidation - no clear trend"
            
            logger.debug(f"Trend: {trend}, score: {score}")
            
        except Exception as e:
            logger.warning(f"Error detecting trend: {e}")
        
        return trend, score, detail
    
    # ══════════════════════════════════════════════════════════
    # BREAKOUT DETECTION METHODS
    # ══════════════════════════════════════════════════════════
    
    def _detect_breakout(
        self, 
        df: pd.DataFrame, 
        support_levels: List[float], 
        resistance_levels: List[float]
    ) -> Tuple[Optional[str], int, str]:
        """
        Detect price breakout above resistance or below support.
        
        Breakout confirmed with volume > 1.5x average.
        
        Args:
            df: OHLCV DataFrame
            support_levels: List of support levels
            resistance_levels: List of resistance levels
            
        Returns:
            Tuple of (breakout_type, score, detail_string)
        """
        breakout = None
        score = 0
        detail = "No breakout detected"
        
        try:
            current_price = df['close'].iloc[-1]
            current_volume = df['volume'].iloc[-1]
            avg_volume = df['volume'].tail(20).mean()
            
            volume_confirmed = current_volume > (avg_volume * self.VOLUME_SPIKE_MULTIPLIER)
            
            # Check breakout above resistance
            if resistance_levels:
                highest_resistance = max(resistance_levels)
                if current_price > highest_resistance:
                    breakout = "breakout_up"
                    if volume_confirmed:
                        score = 30
                        detail = f"BREAKOUT UP above {highest_resistance:.2f} with volume confirmation!"
                    else:
                        score = 15
                        detail = f"Breakout above {highest_resistance:.2f} (low volume - unconfirmed)"
            
            # Check breakdown below support
            if support_levels and breakout is None:
                lowest_support = min(support_levels)
                if current_price < lowest_support:
                    breakout = "breakdown"
                    if volume_confirmed:
                        score = -30
                        detail = f"BREAKDOWN below {lowest_support:.2f} with volume confirmation!"
                    else:
                        score = -15
                        detail = f"Breakdown below {lowest_support:.2f} (low volume - unconfirmed)"
            
            logger.debug(f"Breakout: {breakout}, score: {score}")
            
        except Exception as e:
            logger.warning(f"Error detecting breakout: {e}")
        
        return breakout, score, detail
    
    # ══════════════════════════════════════════════════════════
    # CANDLESTICK PATTERN METHODS
    # ══════════════════════════════════════════════════════════
    
    def _detect_candle_patterns(
        self, 
        df: pd.DataFrame
    ) -> Tuple[List[str], int, str]:
        """
        Detect candlestick patterns in recent candles.
        
        Patterns detected:
        - Bullish/Bearish Engulfing
        - Hammer/Shooting Star
        - Doji
        - Morning Star/Evening Star
        
        Args:
            df: OHLCV DataFrame
            
        Returns:
            Tuple of (patterns_list, total_score, detail_string)
        """
        patterns = []
        total_score = 0
        details = []
        
        try:
            # Need at least 3 candles
            if len(df) < 3:
                return patterns, total_score, "Insufficient data for pattern detection"
            
            # Get last 3 candles
            candles = []
            for i in range(-3, 0):
                candles.append({
                    'open': float(df['open'].iloc[i]),
                    'high': float(df['high'].iloc[i]),
                    'low': float(df['low'].iloc[i]),
                    'close': float(df['close'].iloc[i])
                })
            
            c1, c2, c3 = candles  # c3 is the most recent
            
            # Check for Bullish Engulfing
            if self._is_bullish_engulfing(c2, c3):
                patterns.append("Bullish Engulfing")
                total_score += 15
                details.append("Bullish Engulfing pattern (reversal)")
            
            # Check for Bearish Engulfing
            if self._is_bearish_engulfing(c2, c3):
                patterns.append("Bearish Engulfing")
                total_score -= 15
                details.append("Bearish Engulfing pattern (reversal)")
            
            # Check for Hammer
            if self._is_hammer(c3):
                patterns.append("Hammer")
                total_score += 15
                details.append("Hammer pattern (bullish reversal)")
            
            # Check for Shooting Star
            if self._is_shooting_star(c3):
                patterns.append("Shooting Star")
                total_score -= 15
                details.append("Shooting Star pattern (bearish reversal)")
            
            # Check for Doji
            if self._is_doji(c3):
                patterns.append("Doji")
                # Doji alone is neutral
                details.append("Doji pattern (indecision)")
            
            # Check for Morning Star
            if self._is_morning_star(c1, c2, c3):
                patterns.append("Morning Star")
                total_score += 20
                details.append("Morning Star pattern (strong bullish reversal)")
            
            # Check for Evening Star
            if self._is_evening_star(c1, c2, c3):
                patterns.append("Evening Star")
                total_score -= 20
                details.append("Evening Star pattern (strong bearish reversal)")
            
            # Limit score to max single pattern score
            total_score = max(-20, min(20, total_score))
            
            logger.debug(f"Candle patterns: {patterns}, score: {total_score}")
            
        except Exception as e:
            logger.warning(f"Error detecting candle patterns: {e}")
        
        detail = " | ".join(details) if details else "No significant candle patterns"
        return patterns, total_score, detail
    
    # ══════════════════════════════════════════════════════════
    # CANDLESTICK HELPER METHODS
    # ══════════════════════════════════════════════════════════
    
    def _is_green(self, candle: Dict) -> bool:
        """Check if candle is bullish (green)."""
        return candle['close'] > candle['open']
    
    def _is_red(self, candle: Dict) -> bool:
        """Check if candle is bearish (red)."""
        return candle['close'] < candle['open']
    
    def _body_size(self, candle: Dict) -> float:
        """Calculate candle body size."""
        return abs(candle['close'] - candle['open'])
    
    def _upper_wick(self, candle: Dict) -> float:
        """Calculate upper wick size."""
        return candle['high'] - max(candle['open'], candle['close'])
    
    def _lower_wick(self, candle: Dict) -> float:
        """Calculate lower wick size."""
        return min(candle['open'], candle['close']) - candle['low']
    
    def _candle_range(self, candle: Dict) -> float:
        """Calculate total candle range."""
        return candle['high'] - candle['low']
    
    def _is_bullish_engulfing(self, prev: Dict, curr: Dict) -> bool:
        """
        Check for Bullish Engulfing pattern.
        Current green candle body fully covers previous red candle body.
        """
        if not self._is_red(prev) or not self._is_green(curr):
            return False
        
        # Current body engulfs previous body
        return (curr['open'] <= prev['close'] and 
                curr['close'] >= prev['open'])
    
    def _is_bearish_engulfing(self, prev: Dict, curr: Dict) -> bool:
        """
        Check for Bearish Engulfing pattern.
        Current red candle body fully covers previous green candle body.
        """
        if not self._is_green(prev) or not self._is_red(curr):
            return False
        
        # Current body engulfs previous body
        return (curr['open'] >= prev['close'] and 
                curr['close'] <= prev['open'])
    
    def _is_hammer(self, candle: Dict) -> bool:
        """
        Check for Hammer pattern.
        Small body at top, long lower wick (>2x body).
        """
        body = self._body_size(candle)
        lower_wick = self._lower_wick(candle)
        upper_wick = self._upper_wick(candle)
        
        if body == 0:
            return False
        
        return (lower_wick >= 2 * body and 
                upper_wick <= body * 0.5)
    
    def _is_shooting_star(self, candle: Dict) -> bool:
        """
        Check for Shooting Star pattern.
        Small body at bottom, long upper wick (>2x body).
        """
        body = self._body_size(candle)
        lower_wick = self._lower_wick(candle)
        upper_wick = self._upper_wick(candle)
        
        if body == 0:
            return False
        
        return (upper_wick >= 2 * body and 
                lower_wick <= body * 0.5)
    
    def _is_doji(self, candle: Dict) -> bool:
        """
        Check for Doji pattern.
        Open and close very close (<0.1% of range).
        """
        body = self._body_size(candle)
        range_size = self._candle_range(candle)
        
        if range_size == 0:
            return True  # Flat candle is technically a doji
        
        return body / range_size < 0.1
    
    def _is_morning_star(self, c1: Dict, c2: Dict, c3: Dict) -> bool:
        """
        Check for Morning Star pattern (3 candles).
        Red candle -> Small body (star) -> Green candle
        """
        if not self._is_red(c1) or not self._is_green(c3):
            return False
        
        c1_body = self._body_size(c1)
        c2_body = self._body_size(c2)
        c3_body = self._body_size(c3)
        
        # Middle candle should be small
        if c2_body >= c1_body * 0.5:
            return False
        
        # Third candle should close above midpoint of first candle
        c1_midpoint = (c1['open'] + c1['close']) / 2
        return c3['close'] > c1_midpoint
    
    def _is_evening_star(self, c1: Dict, c2: Dict, c3: Dict) -> bool:
        """
        Check for Evening Star pattern (3 candles).
        Green candle -> Small body (star) -> Red candle
        """
        if not self._is_green(c1) or not self._is_red(c3):
            return False
        
        c1_body = self._body_size(c1)
        c2_body = self._body_size(c2)
        c3_body = self._body_size(c3)
        
        # Middle candle should be small
        if c2_body >= c1_body * 0.5:
            return False
        
        # Third candle should close below midpoint of first candle
        c1_midpoint = (c1['open'] + c1['close']) / 2
        return c3['close'] < c1_midpoint
        # ══════════════════════════════════════════════════════════
    # PRICE PATTERN METHODS
    # ══════════════════════════════════════════════════════════
    
    def _detect_price_patterns(
        self, 
        df: pd.DataFrame
    ) -> Tuple[List[str], int, str]:
        """
        Detect price action patterns like Double Top/Bottom.
        
        Args:
            df: OHLCV DataFrame
            
        Returns:
            Tuple of (patterns_list, total_score, detail_string)
        """
        patterns = []
        total_score = 0
        details = []
        
        try:
            # Check for Double Bottom (bullish)
            double_bottom = self._detect_double_bottom(df)
            if double_bottom:
                patterns.append("Double Bottom")
                total_score += 25
                details.append(f"Double Bottom at {double_bottom:.2f} (bullish reversal)")
            
            # Check for Double Top (bearish)
            double_top = self._detect_double_top(df)
            if double_top:
                patterns.append("Double Top")
                total_score -= 25
                details.append(f"Double Top at {double_top:.2f} (bearish reversal)")
            
            logger.debug(f"Price patterns: {patterns}, score: {total_score}")
            
        except Exception as e:
            logger.warning(f"Error detecting price patterns: {e}")
        
        detail = " | ".join(details) if details else "No significant price patterns"
        return patterns, total_score, detail
    
    def _detect_double_bottom(self, df: pd.DataFrame) -> Optional[float]:
        """
        Detect Double Bottom pattern.
        Two roughly equal lows with a peak between them.
        
        Args:
            df: OHLCV DataFrame
            
        Returns:
            Bottom price level if found, None otherwise
        """
        try:
            # Look at last 20 candles
            recent = df.tail(20)
            if len(recent) < 10:
                return None
            
            lows = recent['low'].values
            highs = recent['high'].values
            
            # Find two lowest points
            sorted_indices = np.argsort(lows)
            low1_idx = sorted_indices[0]
            
            # Second low must be at least 3 candles away
            low2_idx = None
            for idx in sorted_indices[1:]:
                if abs(idx - low1_idx) >= 3:
                    low2_idx = idx
                    break
            
            if low2_idx is None:
                return None
            
            low1 = lows[low1_idx]
            low2 = lows[low2_idx]
            
            # Check if lows are roughly equal (within tolerance)
            avg_low = (low1 + low2) / 2
            if abs(low1 - low2) / avg_low > self.DOUBLE_PATTERN_TOLERANCE:
                return None
            
            # Check for peak between the two lows
            start = min(low1_idx, low2_idx)
            end = max(low1_idx, low2_idx)
            
            if end - start < 2:
                return None
            
            peak_between = max(highs[start:end+1])
            
            # Peak should be significantly higher than lows
            if peak_between > avg_low * 1.02:  # At least 2% higher
                return avg_low
            
            return None
            
        except Exception as e:
            logger.warning(f"Error detecting double bottom: {e}")
            return None
    
    def _detect_double_top(self, df: pd.DataFrame) -> Optional[float]:
        """
        Detect Double Top pattern.
        Two roughly equal highs with a valley between them.
        
        Args:
            df: OHLCV DataFrame
            
        Returns:
            Top price level if found, None otherwise
        """
        try:
            # Look at last 20 candles
            recent = df.tail(20)
            if len(recent) < 10:
                return None
            
            highs = recent['high'].values
            lows = recent['low'].values
            
            # Find two highest points
            sorted_indices = np.argsort(highs)[::-1]  # Descending
            high1_idx = sorted_indices[0]
            
            # Second high must be at least 3 candles away
            high2_idx = None
            for idx in sorted_indices[1:]:
                if abs(idx - high1_idx) >= 3:
                    high2_idx = idx
                    break
            
            if high2_idx is None:
                return None
            
            high1 = highs[high1_idx]
            high2 = highs[high2_idx]
            
            # Check if highs are roughly equal (within tolerance)
            avg_high = (high1 + high2) / 2
            if abs(high1 - high2) / avg_high > self.DOUBLE_PATTERN_TOLERANCE:
                return None
            
            # Check for valley between the two highs
            start = min(high1_idx, high2_idx)
            end = max(high1_idx, high2_idx)
            
            if end - start < 2:
                return None
            
            valley_between = min(lows[start:end+1])
            
            # Valley should be significantly lower than highs
            if valley_between < avg_high * 0.98:  # At least 2% lower
                return avg_high
            
            return None
            
        except Exception as e:
            logger.warning(f"Error detecting double top: {e}")
            return None
    
    # ══════════════════════════════════════════════════════════
    # VOLUME ANALYSIS METHODS
    # ══════════════════════════════════════════════════════════
    
    def _analyze_volume_pattern(
        self, 
        df: pd.DataFrame
    ) -> Tuple[str, int, str]:
        """
        Analyze volume patterns for accumulation/distribution.
        
        Bullish: Increasing volume on up days, decreasing on down days
        Bearish: Increasing volume on down days, decreasing on up days
        
        Args:
            df: OHLCV DataFrame
            
        Returns:
            Tuple of (signal_type, score, detail_string)
        """
        signal = "neutral"
        score = 0
        detail = "Neutral volume pattern"
        
        try:
            recent = df.tail(10)
            if len(recent) < 5:
                return signal, score, detail
            
            # Separate up days and down days
            up_days_volume = []
            down_days_volume = []
            
            for i in range(len(recent)):
                if recent['close'].iloc[i] > recent['open'].iloc[i]:
                    up_days_volume.append(recent['volume'].iloc[i])
                else:
                    down_days_volume.append(recent['volume'].iloc[i])
            
            avg_volume = df['volume'].tail(20).mean()
            
            # Calculate average volume for up and down days
            avg_up_volume = np.mean(up_days_volume) if up_days_volume else 0
            avg_down_volume = np.mean(down_days_volume) if down_days_volume else 0
            
            # Check for volume spike on recent candle
            recent_volume = df['volume'].iloc[-1]
            volume_spike = recent_volume > avg_volume * self.VOLUME_SPIKE_MULTIPLIER
            recent_is_up = df['close'].iloc[-1] > df['open'].iloc[-1]
            
            # Determine pattern
            if avg_up_volume > avg_down_volume * 1.2:
                signal = "accumulation"
                score = 10
                detail = "Volume accumulation pattern (bullish)"
            elif avg_down_volume > avg_up_volume * 1.2:
                signal = "distribution"
                score = -10
                detail = "Volume distribution pattern (bearish)"
            
            # Volume spike confirmation
            if volume_spike:
                if recent_is_up:
                    score = max(score, 10)
                    if signal != "accumulation":
                        signal = "spike_bullish"
                        detail = "Bullish volume spike"
                else:
                    score = min(score, -10)
                    if signal != "distribution":
                        signal = "spike_bearish"
                        detail = "Bearish volume spike"
            
            logger.debug(f"Volume signal: {signal}, score: {score}")
            
        except Exception as e:
            logger.warning(f"Error analyzing volume: {e}")
        
        return signal, score, detail
    
    # ══════════════════════════════════════════════════════════
    # SIGNAL GENERATION METHODS
    # ══════════════════════════════════════════════════════════
    
    def _normalize_total_score(self, raw_score: float) -> float:
        """
        Normalize raw score to -100 to +100 range.
        
        Args:
            raw_score: Sum of all component scores
            
        Returns:
            Normalized score (-100 to +100)
        """
        # Scale based on max possible score
        normalized = (raw_score / self.MAX_SCORE) * 100
        
        # Clamp to range
        return max(-100, min(100, normalized))
    
    def _determine_signal(
        self, 
        score: float
    ) -> Tuple[str, float, Optional[Dict]]:
        """
        Determine trading signal from pattern score.
        
        Args:
            score: Normalized score (-100 to +100)
            
        Returns:
            Tuple of (action, confidence, option_recommendation)
        """
        # Calculate confidence
        raw_confidence = abs(score) / 100
        confidence = min(1.0, max(0.0, raw_confidence))
        
        # Determine action
        if score >= self.BULLISH_THRESHOLD:
            action = SIGNAL_BUY
            option_rec = {
                'type': OPTION_TYPE_CALL,
                'strike_preference': 'ATM' if confidence >= 0.70 else 'OTM1',
                'expiry': 'WEEKLY'
            }
        elif score <= self.BEARISH_THRESHOLD:
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
        trend: str,
        trend_detail: str,
        sr_detail: str,
        breakout_detail: str,
        candle_detail: str,
        price_detail: str,
        volume_detail: str,
        total_score: float
    ) -> str:
        """
        Build human-readable reasoning for the signal.
        
        Args:
            Various component details and scores
            
        Returns:
            Reasoning string
        """
        direction = "BULLISH" if total_score > 0 else "BEARISH" if total_score < 0 else "NEUTRAL"
        
        parts = [
            f"Pattern Analysis: {direction} (score: {total_score:.1f}/100)",
            f"Trend: {trend_detail}",
        ]
        
        # Add non-default details
        if "No significant" not in sr_detail and "nearby" not in sr_detail:
            parts.append(sr_detail)
        
        if "No breakout" not in breakout_detail:
            parts.append(breakout_detail)
        
        if "No significant candle" not in candle_detail:
            parts.append(candle_detail)
        
        if "No significant price" not in price_detail:
            parts.append(price_detail)
        
        if "Neutral" not in volume_detail:
            parts.append(volume_detail)
        
        return " | ".join(parts)


# ══════════════════════════════════════════════════════════
# TESTING
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    """
    Test the PatternBrain with mock data.
    
    Run with: python -m brains.pattern
    """
    import sys
    
    # Setup logging for testing
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 60)
    print("PATTERN BRAIN TEST")
    print("=" * 60)
    
    # Create mock market data with realistic price action
    class MockMarketData:
        """Mock market data for testing."""
        
        def get_historical(self, symbol: str, days: int = 50) -> pd.DataFrame:
            """Generate mock OHLCV data with patterns."""
            
            np.random.seed(42)  # For reproducibility
            
            # Generate base price series with uptrend
            dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
            base_price = 24000  # NIFTY-like
            
            # Create trending data with some patterns
            prices = [base_price]
            for i in range(1, days):
                # Add trend + noise
                trend = 5  # Slight upward trend
                noise = np.random.normal(0, 50)
                prices.append(prices[-1] + trend + noise)
            
            # Generate OHLCV
            data = []
            for i, price in enumerate(prices):
                volatility = 100
                open_price = price + np.random.normal(0, volatility * 0.3)
                high_price = max(open_price, price) + abs(np.random.normal(0, volatility))
                low_price = min(open_price, price) - abs(np.random.normal(0, volatility))
                close_price = price
                volume = int(1000000 + np.random.normal(0, 200000))
                
                data.append({
                    'date': dates[i],
                    'open': round(open_price, 2),
                    'high': round(high_price, 2),
                    'low': round(low_price, 2),
                    'close': round(close_price, 2),
                    'volume': abs(volume)
                })
            
            # Add a bullish engulfing pattern at the end
            data[-2]['open'] = data[-2]['close'] + 50  # Red candle
            data[-2]['close'] = data[-2]['open'] - 80
            data[-1]['open'] = data[-2]['close'] - 10  # Green engulfing
            data[-1]['close'] = data[-2]['open'] + 30
            data[-1]['volume'] = int(data[-1]['volume'] * 2)  # Volume spike
            
            df = pd.DataFrame(data)
            df.set_index('date', inplace=True)
            
            return df
    
    # Run test
    try:
        brain = PatternBrain()
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
    
    # Test edge cases
    print("\n" + "=" * 60)
    print("EDGE CASE TESTS")
    print("=" * 60)
    
    # Test 1: Insufficient data
    class InsufficientDataMarketData:
        def get_historical(self, symbol, days=50):
            # Return only 5 candles
            return pd.DataFrame({
                'open': [100, 101, 102, 103, 104],
                'high': [102, 103, 104, 105, 106],
                'low': [99, 100, 101, 102, 103],
                'close': [101, 102, 103, 104, 105],
                'volume': [1000, 1000, 1000, 1000, 1000]
            })
    
    try:
        signal = brain.analyze('TEST', InsufficientDataMarketData())
        assert signal['action'] == SIGNAL_HOLD
        assert signal['indicators']['data_points'] == 5
        print("✓ Insufficient data test passed")
    except Exception as e:
        print(f"✗ Insufficient data test failed: {e}")
    
    # Test 2: Empty data
    class EmptyDataMarketData:
        def get_historical(self, symbol, days=50):
            return pd.DataFrame()
    
    try:
        signal = brain.analyze('TEST', EmptyDataMarketData())
        assert signal['action'] == SIGNAL_HOLD
        print("✓ Empty data test passed")
    except Exception as e:
        print(f"✗ Empty data test failed: {e}")
    
    # Test 3: None data
    class NoneDataMarketData:
        def get_historical(self, symbol, days=50):
            return None
    
    try:
        signal = brain.analyze('TEST', NoneDataMarketData())
        assert signal['action'] == SIGNAL_HOLD
        print("✓ None data test passed")
    except Exception as e:
        print(f"✗ None data test failed: {e}")
    
    # Test 4: Bearish pattern
    class BearishPatternMarketData:
        def get_historical(self, symbol, days=50):
            # Create strong downtrend with bearish patterns
            data = []
            price = 25000
            for i in range(50):
                price = price - 20 + np.random.normal(0, 30)  # Downtrend
                data.append({
                    'open': price + 30,
                    'high': price + 50,
                    'low': price - 20,
                    'close': price,
                    'volume': 1000000
                })
            
            # Add bearish engulfing
            data[-2]['open'] = data[-2]['close'] - 50  # Green candle
            data[-2]['close'] = data[-2]['open'] + 80
            data[-1]['open'] = data[-2]['close'] + 10  # Red engulfing
            data[-1]['close'] = data[-2]['open'] - 30
            
            return pd.DataFrame(data)
    
    try:
        signal = brain.analyze('TEST', BearishPatternMarketData())
        # Should be bearish or at least not strongly bullish
        assert signal['indicators']['total_score'] <= 0 or signal['action'] in [SIGNAL_HOLD, SIGNAL_SELL]
        print("✓ Bearish pattern test passed")
    except Exception as e:
        print(f"✗ Bearish pattern test failed: {e}")
    
    # Test 5: Capitalized columns
    class CapitalizedColumnsMarketData:
        def get_historical(self, symbol, days=50):
            return pd.DataFrame({
                'Open': [100 + i for i in range(50)],
                'High': [102 + i for i in range(50)],
                'Low': [99 + i for i in range(50)],
                'Close': [101 + i for i in range(50)],
                'Volume': [1000000 for i in range(50)]
            })
    
    try:
        signal = brain.analyze('TEST', CapitalizedColumnsMarketData())
        assert signal is not None
        assert signal['indicators']['data_points'] == 50
        print("✓ Capitalized columns test passed")
    except Exception as e:
        print(f"✗ Capitalized columns test failed: {e}")
    
    # Test 6: Verify brain methods from BaseBrain
    print("\n" + "-" * 60)
    print("INHERITED METHOD TESTS")
    print("-" * 60)
    
    try:
        # Test get_name()
        assert brain.get_name() == 'pattern'
        print("✓ get_name() works")
        
        # Test get_weight()
        assert 0 <= brain.get_weight() <= 1
        print("✓ get_weight() works")
        
        # Test get_stats()
        stats = brain.get_stats()
        assert 'name' in stats
        assert 'weight' in stats
        assert 'analysis_count' in stats
        print("✓ get_stats() works")
        
        # Test is_above_threshold()
        assert brain.is_above_threshold(0.70) == True
        assert brain.is_above_threshold(0.50) == False
        print("✓ is_above_threshold() works")
        
        # Test is_strong_signal()
        assert brain.is_strong_signal(0.80) == True
        assert brain.is_strong_signal(0.60) == False
        print("✓ is_strong_signal() works")
        
    except Exception as e:
        print(f"✗ Inherited method test failed: {e}")
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED ✓")
    print("=" * 60)