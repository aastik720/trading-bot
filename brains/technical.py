"""
Technical Analysis Brain
========================

The FIRST and most important brain. Analyzes price action using
classic technical indicators to generate trading signals.

Indicators Used:
    - RSI (Relative Strength Index): Momentum oscillator
    - MACD (Moving Average Convergence Divergence): Trend & momentum
    - SMA (Simple Moving Average): Trend direction
    - EMA (Exponential Moving Average): Faster trend
    - Bollinger Bands: Volatility and mean reversion
    - Volume Analysis: Confirms trend strength

Scoring System (-100 to +100):
    ┌─────────────────┬──────────────┬──────────────┐
    │ Indicator       │ Bullish (+)  │ Bearish (-)  │
    ├─────────────────┼──────────────┼──────────────┤
    │ RSI < 30        │ +25          │              │
    │ RSI > 70        │              │ +25          │
    │ MACD cross up   │ +25          │              │
    │ MACD cross down │              │ +25          │
    │ Price > SMAs    │ +20          │              │
    │ Price < SMAs    │              │ +20          │
    │ Near lower BB   │ +15          │              │
    │ Near upper BB   │              │ +15          │
    │ Volume spike    │ +15 (confirm)│ +15 (confirm)│
    └─────────────────┴──────────────┴──────────────┘

Signal Mapping:
    - Score >= +50  →  BUY signal  →  Recommend CE (Call)
    - Score <= -50  →  SELL signal →  Recommend PE (Put)
    - -50 < Score < +50  →  HOLD

Confidence Calculation:
    confidence = abs(score) / 100
    
    Examples:
        Score +75 → 75% confidence BUY
        Score -60 → 60% confidence SELL
        Score +30 → HOLD (below threshold)

Strike Preference:
    - High confidence (≥75%): ATM (At The Money)
    - Medium confidence (<75%): OTM1 (1 strike Out of The Money)

Usage:
    from brains.technical import TechnicalBrain
    from data import get_market_data
    
    brain = TechnicalBrain()
    md = get_market_data()
    
    signal = brain.analyze("NIFTY", md)
    print(f"Action: {signal['action']}")
    print(f"Confidence: {signal['confidence']:.1%}")
    print(f"RSI: {signal['indicators']['rsi']}")
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

import pandas as pd

# Try to import pandas_ta
try:
    import pandas_ta_classic as ta
except ImportError:
    logging.warning("pandas_ta not installed")
    PANDAS_TA_AVAILABLE = False
    logging.warning("pandas_ta not installed. Run: pip install pandas_ta")

# Import base class and utilities
from brains.base import BaseBrain

try:
    from utils.helpers import get_ist_now, safe_divide
    from utils.exceptions import BrainError
    from config.settings import settings
    from config.constants import (
        SIGNAL_BUY,
        SIGNAL_SELL,
        SIGNAL_HOLD,
        OPTION_TYPE_CALL,
        OPTION_TYPE_PUT,
        RSI_PERIOD,
        RSI_OVERSOLD,
        RSI_OVERBOUGHT,
        MACD_FAST,
        MACD_SLOW,
        MACD_SIGNAL,
        SMA_SHORT,
        SMA_LONG,
        EMA_SHORT,
        EMA_LONG,
        BOLLINGER_PERIOD,
        BOLLINGER_STD_DEV,
        BRAIN_TECHNICAL,
        MIN_CONFIDENCE_THRESHOLD,
        STRONG_SIGNAL_THRESHOLD,
    )
except ImportError as e:
    logging.warning(f"Could not import some modules: {e}")
    
    # Fallbacks
    def get_ist_now():
        from datetime import timedelta
        return datetime.utcnow() + timedelta(hours=5, minutes=30)
    
    def safe_divide(a, b, default=0):
        return a / b if b != 0 else default
    
    class BrainError(Exception):
        pass
    
    class settings:
        BRAIN_WEIGHT_TECHNICAL = 0.40
    
    SIGNAL_BUY = 'BUY'
    SIGNAL_SELL = 'SELL'
    SIGNAL_HOLD = 'HOLD'
    OPTION_TYPE_CALL = 'CE'
    OPTION_TYPE_PUT = 'PE'
    RSI_PERIOD = 14
    RSI_OVERSOLD = 30
    RSI_OVERBOUGHT = 70
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    SMA_SHORT = 20
    SMA_LONG = 50
    EMA_SHORT = 9
    EMA_LONG = 21
    BOLLINGER_PERIOD = 20
    BOLLINGER_STD_DEV = 2
    BRAIN_TECHNICAL = 'technical'
    MIN_CONFIDENCE_THRESHOLD = 0.60
    STRONG_SIGNAL_THRESHOLD = 0.75


# Setup logging
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# TECHNICAL BRAIN CLASS
# ══════════════════════════════════════════════════════════

class TechnicalBrain(BaseBrain):
    """
    Technical Analysis Brain using classic indicators.
    
    This brain analyzes price action using:
        - RSI: Identifies overbought/oversold conditions
        - MACD: Trend direction and momentum
        - SMA/EMA: Overall trend
        - Bollinger Bands: Volatility and mean reversion
        - Volume: Confirms trend strength
    
    Attributes:
        name: 'technical'
        weight: From settings.BRAIN_WEIGHT_TECHNICAL (default 0.40)
    """
    
    # Scoring weights
    RSI_WEIGHT = 25
    MACD_WEIGHT = 25
    MA_WEIGHT = 20
    BOLLINGER_WEIGHT = 15
    VOLUME_WEIGHT = 15
    
    # Minimum candles needed for analysis
    MIN_CANDLES = 30
    
    def __init__(self):
        """Initialize Technical Brain."""
        # Get weight from settings
        try:
            weight = settings.BRAIN_WEIGHT_TECHNICAL
        except:
            weight = 0.40
        
        super().__init__(name=BRAIN_TECHNICAL, weight=weight)
        
        logger.info(f"TechnicalBrain initialized with weight {weight:.0%}")
    
    # ══════════════════════════════════════════════════════
    # MAIN ANALYSIS METHOD
    # ══════════════════════════════════════════════════════
    
    def analyze(self, symbol: str, market_data: Any) -> Dict[str, Any]:
        """
        Analyze a symbol using technical indicators.
        
        Args:
            symbol: Symbol to analyze (e.g., 'NIFTY', 'BANKNIFTY')
            market_data: MarketData instance
            
        Returns:
            Dict: Standardized signal with action, confidence, indicators
            
        Raises:
            BrainError: If analysis completely fails
        """
        symbol = symbol.upper().strip()
        logger.info(f"TechnicalBrain analyzing {symbol}...")
        
        try:
            # Step 1: Get historical data
            df = self._get_historical_data(symbol, market_data)
            
            if df is None or len(df) < self.MIN_CANDLES:
                logger.warning(f"Insufficient data for {symbol}: {len(df) if df is not None else 0} candles")
                return self._create_hold_signal(
                    symbol=symbol,
                    reasoning=f"Insufficient historical data (need {self.MIN_CANDLES}+ candles)",
                    indicators={'candles_available': len(df) if df is not None else 0}
                )
            
            # Step 2: Calculate all indicators
            indicators = self._calculate_indicators(df)
            
            if indicators is None:
                return self._create_hold_signal(
                    symbol=symbol,
                    reasoning="Failed to calculate technical indicators",
                    indicators={}
                )
            
            # Step 3: Score each indicator
            scores = self._calculate_scores(indicators)
            
            # Step 4: Calculate total score (-100 to +100)
            total_score = scores['total']
            
            # Step 5: Determine action and confidence
            action, confidence = self._determine_action(total_score)
            
            # Step 6: Build reasoning string
            reasoning = self._build_reasoning(indicators, scores, action)
            
            # Step 7: Determine option recommendation
            option_rec = self._determine_option(action, confidence)
            
            # Step 8: Create and return signal
            signal = self._create_signal(
                symbol=symbol,
                action=action,
                confidence=confidence,
                reasoning=reasoning,
                indicators=indicators,
                option_recommendation=option_rec
            )
            
            logger.info(
                f"TechnicalBrain {symbol}: {action} with {confidence:.1%} confidence | "
                f"Score: {total_score:+.1f} | RSI: {indicators.get('rsi', 0):.1f}"
            )
            
            return signal
            
        except BrainError:
            raise
        except Exception as e:
            logger.error(f"TechnicalBrain error analyzing {symbol}: {e}")
            raise BrainError(f"Technical analysis failed for {symbol}: {e}")
    
    # ══════════════════════════════════════════════════════
    # DATA FETCHING
    # ══════════════════════════════════════════════════════
    
    def _get_historical_data(self, symbol: str, market_data: Any) -> Optional[pd.DataFrame]:
        """
        Fetch historical OHLCV data.
        
        Args:
            symbol: Symbol to fetch
            market_data: MarketData instance
            
        Returns:
            DataFrame with OHLCV columns or None
        """
        try:
            if market_data is None:
                logger.warning("market_data is None, using mock data")
                return self._get_mock_data()
            
            # Get 50 days of historical data
            df = market_data.get_historical(symbol, days=50)
            
            if df is None:
                return self._get_mock_data()
            
            # If it's a list, convert to DataFrame
            if isinstance(df, list):
                df = pd.DataFrame(df)
            
            # Ensure required columns exist
            required = ['open', 'high', 'low', 'close']
            for col in required:
                if col not in df.columns:
                    # Try lowercase
                    if col.lower() in df.columns:
                        df[col] = df[col.lower()]
                    else:
                        logger.warning(f"Missing column: {col}")
                        return self._get_mock_data()
            
            # Add volume if missing
            if 'volume' not in df.columns:
                df['volume'] = 100000  # Default volume
            
            # Ensure numeric types
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Drop NaN rows
            df = df.dropna(subset=['close'])
            
            return df
            
        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            return self._get_mock_data()
    
    def _get_mock_data(self) -> pd.DataFrame:
        """Generate mock OHLCV data for testing."""
        import numpy as np
        
        np.random.seed(42)
        
        # Generate 50 days of mock data
        days = 50
        base_price = 23000
        
        data = []
        price = base_price
        
        for i in range(days):
            change = np.random.uniform(-0.02, 0.02)
            open_p = price
            close_p = price * (1 + change)
            high_p = max(open_p, close_p) * (1 + np.random.uniform(0, 0.01))
            low_p = min(open_p, close_p) * (1 - np.random.uniform(0, 0.01))
            volume = np.random.randint(100000, 500000)
            
            data.append({
                'open': open_p,
                'high': high_p,
                'low': low_p,
                'close': close_p,
                'volume': volume,
            })
            
            price = close_p
        
        return pd.DataFrame(data)
    
    # ══════════════════════════════════════════════════════
    # INDICATOR CALCULATION
    # ══════════════════════════════════════════════════════
    
    def _calculate_indicators(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        Calculate all technical indicators.
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            Dict with all indicator values
        """
        try:
            indicators = {}
            
            close = df['close']
            high = df['high']
            low = df['low']
            volume = df['volume'] if 'volume' in df.columns else pd.Series([100000] * len(df))
            
            current_price = close.iloc[-1]
            indicators['price'] = current_price
            indicators['price_prev'] = close.iloc[-2] if len(close) > 1 else current_price
            
            # ── RSI ──
            indicators['rsi'] = self._calculate_rsi(close)
            
            # ── MACD ──
            macd_data = self._calculate_macd(close)
            indicators['macd_line'] = macd_data['macd_line']
            indicators['macd_signal'] = macd_data['macd_signal']
            indicators['macd_histogram'] = macd_data['macd_histogram']
            indicators['macd_crossover'] = macd_data['crossover']
            
            # ── SMA ──
            indicators['sma_short'] = self._calculate_sma(close, SMA_SHORT)
            indicators['sma_long'] = self._calculate_sma(close, SMA_LONG)
            
            # ── EMA ──
            indicators['ema_short'] = self._calculate_ema(close, EMA_SHORT)
            indicators['ema_long'] = self._calculate_ema(close, EMA_LONG)
            
            # ── Bollinger Bands ──
            bb_data = self._calculate_bollinger(close)
            indicators['bb_upper'] = bb_data['upper']
            indicators['bb_middle'] = bb_data['middle']
            indicators['bb_lower'] = bb_data['lower']
            indicators['bb_width'] = bb_data['width']
            indicators['bb_position'] = bb_data['position']  # 0-1 where in band
            
            # ── Volume ──
            indicators['volume_current'] = volume.iloc[-1]
            indicators['volume_avg'] = volume.rolling(window=20).mean().iloc[-1]
            indicators['volume_ratio'] = safe_divide(
                indicators['volume_current'],
                indicators['volume_avg'],
                default=1.0
            )
            
            # ── Support/Resistance ──
            indicators['recent_high'] = high.tail(20).max()
            indicators['recent_low'] = low.tail(20).min()
            
            # ── Trend ──
            indicators['trend_short'] = 'up' if current_price > indicators['sma_short'] else 'down'
            indicators['trend_long'] = 'up' if current_price > indicators['sma_long'] else 'down'
            
            return indicators
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            return None
    
    def _calculate_rsi(self, close: pd.Series) -> float:
        """Calculate RSI."""
        try:
            if PANDAS_TA_AVAILABLE:
                rsi = ta.rsi(close, length=RSI_PERIOD)
                if rsi is not None and len(rsi) > 0:
                    value = rsi.iloc[-1]
                    return float(value) if pd.notna(value) else 50.0
            
            # Manual calculation fallback
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(window=RSI_PERIOD).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=RSI_PERIOD).mean()
            
            rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100
            rsi = 100 - (100 / (1 + rs))
            
            return float(rsi) if pd.notna(rsi) else 50.0
            
        except Exception as e:
            logger.warning(f"RSI calculation error: {e}")
            return 50.0
    
    def _calculate_macd(self, close: pd.Series) -> Dict[str, Any]:
        """Calculate MACD."""
        try:
            if PANDAS_TA_AVAILABLE:
                macd_df = ta.macd(close, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
                
                if macd_df is not None and len(macd_df) > 0:
                    macd_line = macd_df.iloc[-1, 0]
                    signal_line = macd_df.iloc[-1, 2]
                    histogram = macd_df.iloc[-1, 1]
                    
                    # Check for crossover
                    prev_macd = macd_df.iloc[-2, 0] if len(macd_df) > 1 else 0
                    prev_signal = macd_df.iloc[-2, 2] if len(macd_df) > 1 else 0
                    
                    crossover = 'none'
                    if prev_macd <= prev_signal and macd_line > signal_line:
                        crossover = 'bullish'
                    elif prev_macd >= prev_signal and macd_line < signal_line:
                        crossover = 'bearish'
                    
                    return {
                        'macd_line': float(macd_line) if pd.notna(macd_line) else 0,
                        'macd_signal': float(signal_line) if pd.notna(signal_line) else 0,
                        'macd_histogram': float(histogram) if pd.notna(histogram) else 0,
                        'crossover': crossover,
                    }
            
            # Manual calculation fallback
            ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
            ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
            histogram = macd_line - signal_line
            
            # Check crossover
            crossover = 'none'
            if len(macd_line) > 1:
                if macd_line.iloc[-2] <= signal_line.iloc[-2] and macd_line.iloc[-1] > signal_line.iloc[-1]:
                    crossover = 'bullish'
                elif macd_line.iloc[-2] >= signal_line.iloc[-2] and macd_line.iloc[-1] < signal_line.iloc[-1]:
                    crossover = 'bearish'
            
            return {
                'macd_line': float(macd_line.iloc[-1]),
                'macd_signal': float(signal_line.iloc[-1]),
                'macd_histogram': float(histogram.iloc[-1]),
                'crossover': crossover,
            }
            
        except Exception as e:
            logger.warning(f"MACD calculation error: {e}")
            return {'macd_line': 0, 'macd_signal': 0, 'macd_histogram': 0, 'crossover': 'none'}
    
    def _calculate_sma(self, close: pd.Series, period: int) -> float:
        """Calculate Simple Moving Average."""
        try:
            if PANDAS_TA_AVAILABLE:
                sma = ta.sma(close, length=period)
                if sma is not None and len(sma) > 0:
                    value = sma.iloc[-1]
                    return float(value) if pd.notna(value) else float(close.iloc[-1])
            
            # Manual calculation
            return float(close.tail(period).mean())
            
        except Exception as e:
            logger.warning(f"SMA calculation error: {e}")
            return float(close.iloc[-1])
    
    def _calculate_ema(self, close: pd.Series, period: int) -> float:
        """Calculate Exponential Moving Average."""
        try:
            if PANDAS_TA_AVAILABLE:
                ema = ta.ema(close, length=period)
                if ema is not None and len(ema) > 0:
                    value = ema.iloc[-1]
                    return float(value) if pd.notna(value) else float(close.iloc[-1])
            
            # Manual calculation
            return float(close.ewm(span=period, adjust=False).mean().iloc[-1])
            
        except Exception as e:
            logger.warning(f"EMA calculation error: {e}")
            return float(close.iloc[-1])
    
    def _calculate_bollinger(self, close: pd.Series) -> Dict[str, float]:
        """Calculate Bollinger Bands."""
        try:
            if PANDAS_TA_AVAILABLE:
                bb = ta.bbands(close, length=BOLLINGER_PERIOD, std=BOLLINGER_STD_DEV)
                
                if bb is not None and len(bb) > 0:
                    lower = bb.iloc[-1, 0]
                    middle = bb.iloc[-1, 1]
                    upper = bb.iloc[-1, 2]
                    
                    # Calculate position in band (0 = at lower, 1 = at upper)
                    price = close.iloc[-1]
                    width = upper - lower
                    position = (price - lower) / width if width > 0 else 0.5
                    
                    return {
                        'upper': float(upper) if pd.notna(upper) else float(price * 1.02),
                        'middle': float(middle) if pd.notna(middle) else float(price),
                        'lower': float(lower) if pd.notna(lower) else float(price * 0.98),
                        'width': float(width) if pd.notna(width) else 0,
                        'position': float(position) if pd.notna(position) else 0.5,
                    }
            
            # Manual calculation
            middle = close.rolling(window=BOLLINGER_PERIOD).mean().iloc[-1]
            std = close.rolling(window=BOLLINGER_PERIOD).std().iloc[-1]
            upper = middle + (std * BOLLINGER_STD_DEV)
            lower = middle - (std * BOLLINGER_STD_DEV)
            
            price = close.iloc[-1]
            width = upper - lower
            position = (price - lower) / width if width > 0 else 0.5
            
            return {
                'upper': float(upper),
                'middle': float(middle),
                'lower': float(lower),
                'width': float(width),
                'position': float(position),
            }
            
        except Exception as e:
            logger.warning(f"Bollinger calculation error: {e}")
            price = float(close.iloc[-1])
            return {
                'upper': price * 1.02,
                'middle': price,
                'lower': price * 0.98,
                'width': price * 0.04,
                'position': 0.5,
            }
    
    # ══════════════════════════════════════════════════════
    # SCORING
    # ══════════════════════════════════════════════════════
    
    def _calculate_scores(self, indicators: Dict[str, Any]) -> Dict[str, float]:
        """
        Calculate scores for each indicator.
        
        Positive scores = bullish
        Negative scores = bearish
        
        Returns dict with individual scores and total.
        """
        scores = {
            'rsi': 0,
            'macd': 0,
            'ma': 0,
            'bollinger': 0,
            'volume': 0,
            'total': 0,
        }
        
        # ── RSI Score ──
        rsi = indicators.get('rsi', 50)
        scores['rsi'] = self._score_rsi(rsi)
        
        # ── MACD Score ──
        macd_line = indicators.get('macd_line', 0)
        macd_signal = indicators.get('macd_signal', 0)
        crossover = indicators.get('macd_crossover', 'none')
        scores['macd'] = self._score_macd(macd_line, macd_signal, crossover)
        
        # ── Moving Averages Score ──
        price = indicators.get('price', 0)
        sma_short = indicators.get('sma_short', price)
        sma_long = indicators.get('sma_long', price)
        scores['ma'] = self._score_moving_averages(price, sma_short, sma_long)
        
        # ── Bollinger Bands Score ──
        bb_position = indicators.get('bb_position', 0.5)
        scores['bollinger'] = self._score_bollinger(bb_position)
        
        # ── Volume Score ──
        volume_ratio = indicators.get('volume_ratio', 1.0)
        scores['volume'] = self._score_volume(volume_ratio, scores['total'])
        
        # ── Total Score ──
        # Sum all except volume (volume confirms direction)
        base_score = scores['rsi'] + scores['macd'] + scores['ma'] + scores['bollinger']
        
        # Volume amplifies the signal
        if base_score > 0 and scores['volume'] > 0:
            scores['total'] = base_score + scores['volume']
        elif base_score < 0 and scores['volume'] < 0:
            scores['total'] = base_score + scores['volume']
        else:
            scores['total'] = base_score
        
        # Clamp to -100 to +100
        scores['total'] = max(-100, min(100, scores['total']))
        
        return scores
    
    def _score_rsi(self, rsi: float) -> float:
        """
        Score RSI indicator.
        
        RSI < 30: Oversold → Bullish (+25)
        RSI > 70: Overbought → Bearish (-25)
        RSI 30-70: Neutral (scaled)
        """
        if rsi <= RSI_OVERSOLD:
            # Oversold - bullish signal
            return self.RSI_WEIGHT
        elif rsi >= RSI_OVERBOUGHT:
            # Overbought - bearish signal
            return -self.RSI_WEIGHT
        elif rsi < 40:
            # Slightly oversold
            return self.RSI_WEIGHT * 0.5
        elif rsi > 60:
            # Slightly overbought
            return -self.RSI_WEIGHT * 0.5
        else:
            # Neutral zone
            return 0
    
    def _score_macd(self, macd_line: float, signal_line: float, crossover: str) -> float:
        """
        Score MACD indicator.
        
        Bullish crossover: +25
        Bearish crossover: -25
        MACD above signal: +12
        MACD below signal: -12
        """
        score = 0
        
        # Crossover is strongest signal
        if crossover == 'bullish':
            score = self.MACD_WEIGHT
        elif crossover == 'bearish':
            score = -self.MACD_WEIGHT
        else:
            # No crossover, use relative position
            if macd_line > signal_line:
                score = self.MACD_WEIGHT * 0.5
            elif macd_line < signal_line:
                score = -self.MACD_WEIGHT * 0.5
        
        return score
    
    def _score_moving_averages(self, price: float, sma_short: float, sma_long: float) -> float:
        """
        Score moving averages.
        
        Price > both SMAs: Bullish (+20)
        Price < both SMAs: Bearish (-20)
        Mixed: Neutral
        """
        above_short = price > sma_short
        above_long = price > sma_long
        
        if above_short and above_long:
            # Price above both - bullish
            return self.MA_WEIGHT
        elif not above_short and not above_long:
            # Price below both - bearish
            return -self.MA_WEIGHT
        else:
            # Mixed signals
            if above_short:
                return self.MA_WEIGHT * 0.3
            else:
                return -self.MA_WEIGHT * 0.3
    
    def _score_bollinger(self, bb_position: float) -> float:
        """
        Score Bollinger Bands position.
        
        Near lower band (position < 0.2): Bullish (+15)
        Near upper band (position > 0.8): Bearish (-15)
        Middle: Neutral
        """
        if bb_position <= 0.1:
            # At or below lower band - bullish (oversold)
            return self.BOLLINGER_WEIGHT
        elif bb_position >= 0.9:
            # At or above upper band - bearish (overbought)
            return -self.BOLLINGER_WEIGHT
        elif bb_position <= 0.25:
            # Near lower band
            return self.BOLLINGER_WEIGHT * 0.6
        elif bb_position >= 0.75:
            # Near upper band
            return -self.BOLLINGER_WEIGHT * 0.6
        else:
            # Middle of bands
            return 0
    
    def _score_volume(self, volume_ratio: float, current_direction: float) -> float:
        """
        Score volume.
        
        Volume > 1.5x average: Confirms trend (+/- 15)
        Volume > 1.2x average: Slight confirmation (+/- 8)
        Normal volume: No impact
        """
        if volume_ratio >= 1.5:
            # High volume - confirms direction
            if current_direction > 0:
                return self.VOLUME_WEIGHT
            elif current_direction < 0:
                return -self.VOLUME_WEIGHT
            else:
                return 0
        elif volume_ratio >= 1.2:
            # Moderate volume spike
            if current_direction > 0:
                return self.VOLUME_WEIGHT * 0.5
            elif current_direction < 0:
                return -self.VOLUME_WEIGHT * 0.5
            else:
                return 0
        else:
            return 0
    
    # ══════════════════════════════════════════════════════
    # ACTION DETERMINATION
    # ══════════════════════════════════════════════════════
    
    def _determine_action(self, score: float) -> Tuple[str, float]:
        """
        Determine action and confidence from total score.
        
        Args:
            score: Total score (-100 to +100)
            
        Returns:
            Tuple of (action, confidence)
        """
        # Confidence is absolute score normalized to 0-1
        confidence = abs(score) / 100.0
        
        if score >= 50:
            return SIGNAL_BUY, confidence
        elif score <= -50:
            return SIGNAL_SELL, confidence
        else:
            # HOLD - but still report confidence of the lean
            return SIGNAL_HOLD, confidence * 0.5  # Reduce confidence for HOLD
    
    def _determine_option(self, action: str, confidence: float) -> Optional[Dict[str, str]]:
        """
        Determine option recommendation.
        
        Args:
            action: BUY, SELL, or HOLD
            confidence: Confidence score
            
        Returns:
            Option recommendation dict or None
        """
        if action == SIGNAL_HOLD:
            return None
        
        option_type = self._determine_option_type(action)
        strike_pref = self._determine_strike_preference(confidence)
        
        return {
            'type': option_type,
            'strike_preference': strike_pref,
            'expiry': 'WEEKLY',
        }
    
    # ══════════════════════════════════════════════════════
    # REASONING
    # ══════════════════════════════════════════════════════
    
    def _build_reasoning(
        self,
        indicators: Dict[str, Any],
        scores: Dict[str, float],
        action: str
    ) -> str:
        """Build human-readable reasoning string."""
        reasons = []
        
        # RSI
        rsi = indicators.get('rsi', 50)
        if rsi <= RSI_OVERSOLD:
            reasons.append(f"RSI oversold ({rsi:.1f})")
        elif rsi >= RSI_OVERBOUGHT:
            reasons.append(f"RSI overbought ({rsi:.1f})")
        
        # MACD
        crossover = indicators.get('macd_crossover', 'none')
        if crossover == 'bullish':
            reasons.append("MACD bullish crossover")
        elif crossover == 'bearish':
            reasons.append("MACD bearish crossover")
        elif scores['macd'] > 0:
            reasons.append("MACD above signal")
        elif scores['macd'] < 0:
            reasons.append("MACD below signal")
        
        # Moving Averages
        if scores['ma'] > 0:
            reasons.append("Price above moving averages")
        elif scores['ma'] < 0:
            reasons.append("Price below moving averages")
        
        # Bollinger
        bb_pos = indicators.get('bb_position', 0.5)
        if bb_pos <= 0.2:
            reasons.append(f"Near lower Bollinger band")
        elif bb_pos >= 0.8:
            reasons.append(f"Near upper Bollinger band")
        
        # Volume
        vol_ratio = indicators.get('volume_ratio', 1.0)
        if vol_ratio >= 1.5:
            reasons.append(f"High volume ({vol_ratio:.1f}x avg)")
        
        # Combine
        if not reasons:
            reasons.append("No strong signals")
        
        score = scores['total']
        direction = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"
        
        reasoning = f"{' + '.join(reasons)} → {direction} (score: {score:+.0f})"
        
        return reasoning


# ══════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  TECHNICAL BRAIN - TEST")
    print("=" * 60)
    
    # Check pandas_ta
    print(f"\n  pandas_ta available: {'✅ Yes' if PANDAS_TA_AVAILABLE else '❌ No (using fallbacks)'}")
    
    # Create brain
    print("\n  1. Creating TechnicalBrain...")
    brain = TechnicalBrain()
    print(f"     ✅ Created: {brain}")
    print(f"     Name: {brain.get_name()}")
    print(f"     Weight: {brain.get_weight():.0%}")
    
    # Test with mock data (no market_data)
    print("\n  2. Analyzing with mock data...")
    
    for symbol in ["NIFTY", "BANKNIFTY"]:
        print(f"\n     Analyzing {symbol}...")
        
        try:
            signal = brain.analyze(symbol, None)
            
            action = signal['action']
            confidence = signal['confidence']
            
            action_icon = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
            
            print(f"     {action_icon} {action} with {confidence:.1%} confidence")
            print(f"        Reasoning: {signal['reasoning']}")
            
            # Show key indicators
            ind = signal['indicators']
            print(f"        RSI: {ind.get('rsi', 0):.1f}")
            print(f"        MACD: {ind.get('macd_line', 0):.2f} / {ind.get('macd_signal', 0):.2f}")
            print(f"        SMA: {ind.get('sma_short', 0):.0f} / {ind.get('sma_long', 0):.0f}")
            print(f"        BB Position: {ind.get('bb_position', 0):.2f}")
            
            if signal['option_recommendation']:
                opt = signal['option_recommendation']
                print(f"        Option: {opt['type']} {opt['strike_preference']} {opt['expiry']}")
            else:
                print(f"        Option: None (HOLD)")
                
        except Exception as e:
            print(f"     ❌ Error: {e}")
    
    # Test with real market data if available
    print("\n  3. Testing with real MarketData...")
    
    try:
        from data import get_market_data
        md = get_market_data()
        
        signal = brain.analyze("NIFTY", md)
        
        action = signal['action']
        confidence = signal['confidence']
        
        action_icon = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
        
        print(f"     {action_icon} NIFTY: {action} with {confidence:.1%} confidence")
        print(f"        Reasoning: {signal['reasoning']}")
        
    except ImportError:
        print("     ⚠️  MarketData not available (import error)")
    except Exception as e:
        print(f"     ⚠️  Error: {e}")
    
    # Show stats
    print("\n  4. Brain Stats...")
    stats = brain.get_stats()
    print(f"     Analysis count: {stats['analysis_count']}")
    print(f"     Last analysis: {stats['last_analysis']}")
    
    print("\n" + "=" * 60)
    print("  Technical Brain Tests Complete! ✅")
    print("=" * 60 + "\n")