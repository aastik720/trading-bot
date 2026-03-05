"""
Base Brain Module
=================

Abstract base class that ALL brains must inherit from.
This defines the CONTRACT that every brain must follow.

Why an Abstract Base Class?
    - Ensures consistent signal format across all brains
    - Coordinator can work with any brain without knowing specifics
    - New brains can be added without changing existing code
    - Testable and maintainable architecture

Signal Format (MUST be returned by every brain):
    {
        'signal_id': 'SIG-20260305-001234',
        'symbol': 'NIFTY',
        'action': 'BUY',           # BUY / SELL / HOLD
        'confidence': 0.75,        # 0.0 to 1.0
        'brain': 'technical',      # brain name
        'reasoning': 'RSI oversold + MACD bullish crossover',
        'indicators': {            # raw values for audit
            'rsi': 28.5,
            'macd': 15.2,
            ...
        },
        'option_recommendation': { # None if HOLD
            'type': 'CE',          # CE for bullish, PE for bearish
            'strike_preference': 'ATM',  # ATM or OTM1
            'expiry': 'WEEKLY'
        },
        'timestamp': datetime
    }

Usage:
    from brains.base import BaseBrain
    
    class MyCustomBrain(BaseBrain):
        def __init__(self):
            super().__init__(name='custom', weight=0.25)
        
        def analyze(self, symbol, market_data):
            # Your analysis logic here
            return self._create_signal(
                symbol=symbol,
                action='BUY',
                confidence=0.8,
                reasoning='My custom analysis says buy',
                indicators={'my_indicator': 42},
                option_recommendation={'type': 'CE', 'strike_preference': 'ATM', 'expiry': 'WEEKLY'}
            )
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional, List

# Setup logging
logger = logging.getLogger(__name__)

# Import helpers
try:
    from utils.helpers import get_ist_now
    from utils.exceptions import BrainError
    from config.constants import (
        SIGNAL_BUY,
        SIGNAL_SELL,
        SIGNAL_HOLD,
        OPTION_TYPE_CALL,
        OPTION_TYPE_PUT,
        MIN_CONFIDENCE_THRESHOLD,
        STRONG_SIGNAL_THRESHOLD,
    )
except ImportError as e:
    logger.warning(f"Could not import some modules: {e}")
    
    # Fallbacks
    def get_ist_now():
        from datetime import timedelta
        return datetime.utcnow() + timedelta(hours=5, minutes=30)
    
    class BrainError(Exception):
        pass
    
    SIGNAL_BUY = 'BUY'
    SIGNAL_SELL = 'SELL'
    SIGNAL_HOLD = 'HOLD'
    OPTION_TYPE_CALL = 'CE'
    OPTION_TYPE_PUT = 'PE'
    MIN_CONFIDENCE_THRESHOLD = 0.60
    STRONG_SIGNAL_THRESHOLD = 0.75


# ══════════════════════════════════════════════════════════
# SIGNAL ID GENERATOR
# ══════════════════════════════════════════════════════════

_signal_counter = 0

def _generate_signal_id() -> str:
    """Generate unique signal ID."""
    global _signal_counter
    _signal_counter += 1
    
    now = get_ist_now()
    return f"SIG-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{_signal_counter:04d}"


# ══════════════════════════════════════════════════════════
# ABSTRACT BASE BRAIN CLASS
# ══════════════════════════════════════════════════════════

class BaseBrain(ABC):
    """
    Abstract base class for all trading brains.
    
    Every brain MUST:
        1. Inherit from this class
        2. Call super().__init__(name, weight) in __init__
        3. Implement the analyze() method
        4. Return signals in the standardized format
    
    Attributes:
        name: Unique identifier for this brain (e.g., 'technical')
        weight: Weight in consensus voting (0.0 to 1.0, typically sums to 1.0)
        
    Example:
        class TechnicalBrain(BaseBrain):
            def __init__(self):
                super().__init__(name='technical', weight=0.40)
            
            def analyze(self, symbol, market_data):
                # ... analysis logic ...
                return self._create_signal(...)
    """
    
    def __init__(self, name: str, weight: float):
        """
        Initialize base brain.
        
        Args:
            name: Unique name for this brain (e.g., 'technical', 'sentiment')
            weight: Weight in consensus voting (0.0 to 1.0)
                   - Technical: 0.40 (40%)
                   - Sentiment: 0.35 (35%)
                   - Pattern: 0.25 (25%)
        
        Raises:
            ValueError: If name is empty or weight is invalid
        """
        if not name or not isinstance(name, str):
            raise ValueError("Brain name must be a non-empty string")
        
        if not isinstance(weight, (int, float)) or weight < 0 or weight > 1:
            raise ValueError(f"Weight must be between 0.0 and 1.0, got {weight}")
        
        self._name = name.lower().strip()
        self._weight = float(weight)
        self._analysis_count = 0
        self._last_analysis_time: Optional[datetime] = None
        
        logger.info(f"Brain initialized: {self._name} (weight: {self._weight:.0%})")
    
    # ══════════════════════════════════════════════════════
    # ABSTRACT METHOD - MUST BE IMPLEMENTED
    # ══════════════════════════════════════════════════════
    
    @abstractmethod
    def analyze(self, symbol: str, market_data: Any) -> Dict[str, Any]:
        """
        Analyze a symbol and generate a trading signal.
        
        THIS METHOD MUST BE IMPLEMENTED BY EVERY BRAIN.
        
        Args:
            symbol: The symbol to analyze (e.g., 'NIFTY', 'BANKNIFTY')
            market_data: MarketData instance for fetching data
            
        Returns:
            Dict: Signal in standardized format:
                {
                    'signal_id': str,          # Unique ID
                    'symbol': str,             # Symbol analyzed
                    'action': str,             # 'BUY', 'SELL', or 'HOLD'
                    'confidence': float,       # 0.0 to 1.0
                    'brain': str,              # This brain's name
                    'reasoning': str,          # Human-readable explanation
                    'indicators': dict,        # Raw indicator values
                    'option_recommendation': { # None if HOLD
                        'type': 'CE' or 'PE',
                        'strike_preference': 'ATM' or 'OTM1',
                        'expiry': 'WEEKLY' or 'MONTHLY'
                    },
                    'timestamp': datetime
                }
        
        Raises:
            BrainError: If analysis completely fails
            
        Note:
            - Use self._create_signal() to build the return dict
            - Handle missing/NaN data gracefully
            - Return HOLD with low confidence if uncertain
        """
        pass
    
    # ══════════════════════════════════════════════════════
    # HELPER METHODS
    # ══════════════════════════════════════════════════════
    
    def _create_signal(
        self,
        symbol: str,
        action: str,
        confidence: float,
        reasoning: str,
        indicators: Dict[str, Any],
        option_recommendation: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Create a standardized signal dictionary.
        
        Use this method in your analyze() implementation to ensure
        the signal format is correct.
        
        Args:
            symbol: Symbol being analyzed
            action: 'BUY', 'SELL', or 'HOLD'
            confidence: Confidence score 0.0 to 1.0
            reasoning: Human-readable explanation of why this signal
            indicators: Dict of raw indicator values used in analysis
            option_recommendation: Dict with 'type', 'strike_preference', 'expiry'
                                   or None if action is HOLD
        
        Returns:
            Dict: Properly formatted signal
            
        Example:
            return self._create_signal(
                symbol='NIFTY',
                action='BUY',
                confidence=0.75,
                reasoning='RSI oversold at 28, MACD bullish crossover',
                indicators={'rsi': 28, 'macd': 15.2, 'signal': 12.1},
                option_recommendation={
                    'type': 'CE',
                    'strike_preference': 'ATM',
                    'expiry': 'WEEKLY'
                }
            )
        """
        # Validate action
        action = action.upper()
        if action not in [SIGNAL_BUY, SIGNAL_SELL, SIGNAL_HOLD]:
            logger.warning(f"Invalid action '{action}', defaulting to HOLD")
            action = SIGNAL_HOLD
        
        # Clamp confidence to 0-1
        confidence = max(0.0, min(1.0, float(confidence)))
        
        # If HOLD, no option recommendation
        if action == SIGNAL_HOLD:
            option_recommendation = None
        
        # Validate option_recommendation structure
        if option_recommendation is not None:
            if not isinstance(option_recommendation, dict):
                option_recommendation = None
            else:
                # Ensure required keys exist
                opt_type = option_recommendation.get('type', OPTION_TYPE_CALL)
                if opt_type not in [OPTION_TYPE_CALL, OPTION_TYPE_PUT]:
                    opt_type = OPTION_TYPE_CALL if action == SIGNAL_BUY else OPTION_TYPE_PUT
                
                option_recommendation = {
                    'type': opt_type,
                    'strike_preference': option_recommendation.get('strike_preference', 'ATM'),
                    'expiry': option_recommendation.get('expiry', 'WEEKLY'),
                }
        
        # Update stats
        self._analysis_count += 1
        self._last_analysis_time = get_ist_now()
        
        # Build signal
        signal = {
            'signal_id': _generate_signal_id(),
            'symbol': symbol.upper(),
            'action': action,
            'confidence': round(confidence, 4),
            'brain': self._name,
            'reasoning': reasoning,
            'indicators': indicators or {},
            'option_recommendation': option_recommendation,
            'timestamp': get_ist_now(),
        }
        
        logger.debug(
            f"Signal created: {self._name} → {symbol} {action} "
            f"(confidence: {confidence:.1%})"
        )
        
        return signal
    
    def _normalize_confidence(
        self,
        score: float,
        min_val: float,
        max_val: float
    ) -> float:
        """
        Normalize any score to 0.0-1.0 range.
        
        Useful when your scoring system uses a different range
        (e.g., -100 to +100) and needs to be converted to confidence.
        
        Args:
            score: The raw score to normalize
            min_val: Minimum possible score
            max_val: Maximum possible score
            
        Returns:
            float: Normalized score between 0.0 and 1.0
            
        Example:
            # Score of 75 on a -100 to +100 scale
            confidence = self._normalize_confidence(75, -100, 100)
            # Returns 0.875 (75 is 87.5% of the way from -100 to 100)
            
            # Score of 60 on a 0 to 100 scale
            confidence = self._normalize_confidence(60, 0, 100)
            # Returns 0.6
        """
        if max_val == min_val:
            return 0.5  # Avoid division by zero
        
        # Normalize to 0-1
        normalized = (score - min_val) / (max_val - min_val)
        
        # Clamp to 0-1
        return max(0.0, min(1.0, normalized))
    
    def _create_hold_signal(
        self,
        symbol: str,
        reasoning: str = "Insufficient signal strength",
        indicators: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a HOLD signal with zero confidence.
        
        Use when:
            - Data is insufficient
            - Signals are conflicting
            - Confidence is below threshold
        
        Args:
            symbol: Symbol being analyzed
            reasoning: Why we're holding
            indicators: Any indicator values (optional)
            
        Returns:
            Dict: HOLD signal
        """
        return self._create_signal(
            symbol=symbol,
            action=SIGNAL_HOLD,
            confidence=0.0,
            reasoning=reasoning,
            indicators=indicators or {},
            option_recommendation=None
        )
    
    def _determine_strike_preference(self, confidence: float) -> str:
        """
        Determine strike preference based on confidence.
        
        High confidence (≥ 0.75): ATM strikes - higher premium but safer
        Lower confidence: OTM1 strikes - cheaper but riskier
        
        Args:
            confidence: Confidence score 0.0 to 1.0
            
        Returns:
            str: 'ATM' or 'OTM1'
        """
        if confidence >= STRONG_SIGNAL_THRESHOLD:
            return 'ATM'
        else:
            return 'OTM1'
    
    def _determine_option_type(self, action: str) -> str:
        """
        Determine option type based on action.
        
        BUY signal → CE (Call) - profit when price goes up
        SELL signal → PE (Put) - profit when price goes down
        
        Args:
            action: 'BUY' or 'SELL'
            
        Returns:
            str: 'CE' or 'PE'
        """
        if action == SIGNAL_BUY:
            return OPTION_TYPE_CALL  # 'CE'
        elif action == SIGNAL_SELL:
            return OPTION_TYPE_PUT   # 'PE'
        else:
            return OPTION_TYPE_CALL  # Default
    
    # ══════════════════════════════════════════════════════
    # PROPERTIES
    # ══════════════════════════════════════════════════════
    
    def get_name(self) -> str:
        """Get the brain's name."""
        return self._name
    
    def get_weight(self) -> float:
        """Get the brain's weight in consensus voting."""
        return self._weight
    
    def set_weight(self, weight: float):
        """
        Update the brain's weight.
        
        Args:
            weight: New weight (0.0 to 1.0)
        """
        if not isinstance(weight, (int, float)) or weight < 0 or weight > 1:
            raise ValueError(f"Weight must be between 0.0 and 1.0, got {weight}")
        self._weight = float(weight)
        logger.info(f"Brain {self._name} weight updated to {self._weight:.0%}")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get brain statistics.
        
        Returns:
            Dict with analysis count and last analysis time
        """
        return {
            'name': self._name,
            'weight': self._weight,
            'analysis_count': self._analysis_count,
            'last_analysis': self._last_analysis_time,
        }
    
    def is_above_threshold(self, confidence: float) -> bool:
        """
        Check if confidence is above minimum threshold.
        
        Args:
            confidence: Confidence score to check
            
        Returns:
            bool: True if confidence >= MIN_CONFIDENCE_THRESHOLD
        """
        return confidence >= MIN_CONFIDENCE_THRESHOLD
    
    def is_strong_signal(self, confidence: float) -> bool:
        """
        Check if confidence indicates a strong signal.
        
        Args:
            confidence: Confidence score to check
            
        Returns:
            bool: True if confidence >= STRONG_SIGNAL_THRESHOLD
        """
        return confidence >= STRONG_SIGNAL_THRESHOLD
    
    # ══════════════════════════════════════════════════════
    # MAGIC METHODS
    # ══════════════════════════════════════════════════════
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self._name}', weight={self._weight:.0%})>"
    
    def __str__(self) -> str:
        return f"{self._name} brain ({self._weight:.0%})"


# ══════════════════════════════════════════════════════════
# EXAMPLE IMPLEMENTATION (for testing/documentation)
# ══════════════════════════════════════════════════════════

class DummyBrain(BaseBrain):
    """
    A simple dummy brain for testing purposes.
    
    Always returns a HOLD signal with random confidence.
    """
    
    def __init__(self):
        super().__init__(name='dummy', weight=0.10)
    
    def analyze(self, symbol: str, market_data: Any) -> Dict[str, Any]:
        """Generate a dummy signal."""
        import random
        
        # Random action
        actions = [SIGNAL_BUY, SIGNAL_SELL, SIGNAL_HOLD]
        action = random.choice(actions)
        
        # Random confidence
        confidence = random.uniform(0.3, 0.9)
        
        # Create signal
        if action == SIGNAL_HOLD:
            return self._create_hold_signal(
                symbol=symbol,
                reasoning="Dummy brain says hold",
                indicators={'random_value': random.random()}
            )
        else:
            return self._create_signal(
                symbol=symbol,
                action=action,
                confidence=confidence,
                reasoning=f"Dummy brain randomly chose {action}",
                indicators={'random_value': random.random()},
                option_recommendation={
                    'type': self._determine_option_type(action),
                    'strike_preference': self._determine_strike_preference(confidence),
                    'expiry': 'WEEKLY',
                }
            )


# ══════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  BASE BRAIN - TEST")
    print("=" * 60)
    
    # Test 1: Create dummy brain
    print("\n  1. Creating DummyBrain...")
    dummy = DummyBrain()
    print(f"     ✅ Created: {dummy}")
    print(f"     Name: {dummy.get_name()}")
    print(f"     Weight: {dummy.get_weight():.0%}")
    
    # Test 2: Generate signals
    print("\n  2. Generating test signals...")
    
    for i in range(3):
        signal = dummy.analyze("NIFTY", None)
        
        action = signal['action']
        conf = signal['confidence']
        
        action_icon = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
        
        print(f"     {action_icon} Signal {i+1}: {action} with {conf:.1%} confidence")
        print(f"        Reasoning: {signal['reasoning']}")
        
        if signal['option_recommendation']:
            opt = signal['option_recommendation']
            print(f"        Option: {opt['type']} {opt['strike_preference']} {opt['expiry']}")
    
    # Test 3: Test helper methods
    print("\n  3. Testing helper methods...")
    
    # Normalize confidence
    conf1 = dummy._normalize_confidence(75, -100, 100)
    print(f"     _normalize_confidence(75, -100, 100) = {conf1:.2f}")
    
    conf2 = dummy._normalize_confidence(60, 0, 100)
    print(f"     _normalize_confidence(60, 0, 100) = {conf2:.2f}")
    
    # Strike preference
    strike1 = dummy._determine_strike_preference(0.80)
    print(f"     _determine_strike_preference(0.80) = {strike1}")
    
    strike2 = dummy._determine_strike_preference(0.60)
    print(f"     _determine_strike_preference(0.60) = {strike2}")
    
    # Option type
    opt1 = dummy._determine_option_type("BUY")
    print(f"     _determine_option_type('BUY') = {opt1}")
    
    opt2 = dummy._determine_option_type("SELL")
    print(f"     _determine_option_type('SELL') = {opt2}")
    
    # Test 4: Test threshold checks
    print("\n  4. Testing threshold checks...")
    print(f"     is_above_threshold(0.65) = {dummy.is_above_threshold(0.65)}")
    print(f"     is_above_threshold(0.50) = {dummy.is_above_threshold(0.50)}")
    print(f"     is_strong_signal(0.80) = {dummy.is_strong_signal(0.80)}")
    print(f"     is_strong_signal(0.70) = {dummy.is_strong_signal(0.70)}")
    
    # Test 5: Stats
    print("\n  5. Brain stats...")
    stats = dummy.get_stats()
    print(f"     Analysis count: {stats['analysis_count']}")
    print(f"     Last analysis: {stats['last_analysis']}")
    
    # Test 6: Error handling
    print("\n  6. Testing error handling...")
    try:
        bad_brain = DummyBrain()
        bad_brain.set_weight(1.5)  # Invalid
    except ValueError as e:
        print(f"     ✅ Caught invalid weight: {e}")
    
    # Test 7: HOLD signal creation
    print("\n  7. Testing HOLD signal...")
    hold_signal = dummy._create_hold_signal(
        symbol="BANKNIFTY",
        reasoning="Testing hold signal",
        indicators={'test': 123}
    )
    print(f"     Action: {hold_signal['action']}")
    print(f"     Confidence: {hold_signal['confidence']}")
    print(f"     Option Rec: {hold_signal['option_recommendation']}")
    
    print("\n" + "=" * 60)
    print("  Base Brain Tests Complete! ✅")
    print("=" * 60 + "\n")