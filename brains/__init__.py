"""
Brains Package
==============

The INTELLIGENCE of the trading bot. Multiple "brains" analyze market data
and generate trading signals with confidence scores.

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                    BrainCoordinator                         │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
    │  │ Technical   │  │ Sentiment   │  │ Pattern     │         │
    │  │ Brain (40%) │  │ Brain (35%) │  │ Brain (25%) │         │
    │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
    │         │                │                │                 │
    │         └────────────────┼────────────────┘                 │
    │                          ▼                                  │
    │              ┌─────────────────────┐                        │
    │              │ Weighted Aggregation │                       │
    │              │ (Consensus Signal)   │                       │
    │              └─────────────────────┘                        │
    └─────────────────────────────────────────────────────────────┘

Brains Available:
    - TechnicalBrain (40%): RSI, MACD, Bollinger, SMA, EMA, Volume
    - SentimentBrain (35%): News sentiment, keyword analysis, Finnhub API
    - PatternBrain (25%): Candlestick patterns, support/resistance, trends

Signal Format (standardized across ALL brains):
    {
        'signal_id': 'SIG-20260305-001',
        'symbol': 'NIFTY',
        'action': 'BUY',           # BUY / SELL / HOLD
        'confidence': 0.75,        # 0.0 to 1.0
        'brain': 'technical',
        'reasoning': 'RSI oversold + MACD bullish crossover',
        'indicators': {...},       # Raw values for audit
        'option_recommendation': {
            'type': 'CE',          # CE for BUY, PE for SELL
            'strike_preference': 'ATM',
            'expiry': 'WEEKLY'
        },
        'timestamp': datetime
    }

Usage:
    from brains import get_coordinator, TechnicalBrain, PatternBrain, SentimentBrain
    
    # Get pre-configured coordinator with all brains
    coordinator = get_coordinator()
    
    # Analyze a symbol
    from data import get_market_data
    md = get_market_data()
    
    signal = coordinator.analyze_symbol("NIFTY", md)
    print(f"Action: {signal['action']}, Confidence: {signal['confidence']:.1%}")
    
    # Or analyze all instruments
    signals = coordinator.analyze_all(["NIFTY", "BANKNIFTY"], md)

Why Multiple Brains?
    A single indicator can give false signals. By combining:
    - Technical Analysis (chart patterns, momentum)
    - Sentiment Analysis (news, social mood)
    - Pattern Recognition (candlesticks, levels)
    
    We get more robust signals with higher confidence.
    
    Each brain votes independently, and the coordinator
    aggregates using weighted voting to reach consensus.
"""

__version__ = "1.0.0"

import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# DIRECT IMPORTS (for modules that need class directly)
# ══════════════════════════════════════════════════════════

from brains.base import BaseBrain
from brains.technical import TechnicalBrain
from brains.pattern import PatternBrain
from brains.sentiment import SentimentBrain
from brains.coordinator import BrainCoordinator


# ══════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ══════════════════════════════════════════════════════════

_coordinator_instance: Optional[BrainCoordinator] = None
_brains_initialized: bool = False


# ══════════════════════════════════════════════════════════
# FACTORY FUNCTIONS
# ══════════════════════════════════════════════════════════

def get_coordinator(reset: bool = False) -> BrainCoordinator:
    """
    Get or create the BrainCoordinator singleton.
    
    The coordinator manages all brains and aggregates their signals.
    On first call, it initializes with all available brains.
    
    Args:
        reset: If True, create a fresh coordinator
        
    Returns:
        BrainCoordinator instance with all brains registered
        
    Example:
        >>> coordinator = get_coordinator()
        >>> signal = coordinator.analyze_symbol("NIFTY", market_data)
        >>> print(f"{signal['action']} with {signal['confidence']:.1%} confidence")
    """
    global _coordinator_instance, _brains_initialized
    
    if _coordinator_instance is None or reset:
        _coordinator_instance = BrainCoordinator()
        
        # Add Technical Brain (40% weight)
        try:
            technical = TechnicalBrain()
            _coordinator_instance.add_brain(technical)
            logger.info(f"Added brain: {technical.get_name()} (weight: {technical.get_weight():.0%})")
        except Exception as e:
            logger.error(f"Failed to add TechnicalBrain: {e}")
        
        # Add Sentiment Brain (35% weight)
        try:
            sentiment = SentimentBrain()
            _coordinator_instance.add_brain(sentiment)
            logger.info(f"Added brain: {sentiment.get_name()} (weight: {sentiment.get_weight():.0%})")
        except Exception as e:
            logger.error(f"Failed to add SentimentBrain: {e}")
        
        # Add Pattern Brain (25% weight)
        try:
            pattern = PatternBrain()
            _coordinator_instance.add_brain(pattern)
            logger.info(f"Added brain: {pattern.get_name()} (weight: {pattern.get_weight():.0%})")
        except Exception as e:
            logger.error(f"Failed to add PatternBrain: {e}")
        
        _brains_initialized = True
        logger.info(f"BrainCoordinator initialized with {len(_coordinator_instance.list_brains())} brain(s)")
    
    return _coordinator_instance


def get_technical_brain() -> TechnicalBrain:
    """
    Get a standalone TechnicalBrain instance.
    
    Use this if you want to run technical analysis separately
    without going through the coordinator.
    
    Returns:
        TechnicalBrain instance
        
    Example:
        >>> brain = get_technical_brain()
        >>> signal = brain.analyze("NIFTY", market_data)
        >>> print(f"RSI: {signal['indicators'].get('rsi')}")
    """
    return TechnicalBrain()


def get_sentiment_brain() -> SentimentBrain:
    """
    Get a standalone SentimentBrain instance.
    
    Use this if you want to run sentiment analysis separately
    without going through the coordinator.
    
    Returns:
        SentimentBrain instance
        
    Example:
        >>> brain = get_sentiment_brain()
        >>> signal = brain.analyze("NIFTY", market_data)
        >>> print(f"Sentiment: {signal['indicators'].get('sentiment_score')}")
    """
    return SentimentBrain()


def get_pattern_brain() -> PatternBrain:
    """
    Get a standalone PatternBrain instance.
    
    Use this if you want to run pattern analysis separately
    without going through the coordinator.
    
    Returns:
        PatternBrain instance
        
    Example:
        >>> brain = get_pattern_brain()
        >>> signal = brain.analyze("NIFTY", market_data)
        >>> print(f"Patterns: {signal['indicators'].get('candle_patterns_found')}")
    """
    return PatternBrain()


def create_brain(brain_type: str) -> BaseBrain:
    """
    Factory method to create brain instances by type.
    
    Args:
        brain_type: 'technical', 'sentiment', or 'pattern'
        
    Returns:
        Brain instance
        
    Raises:
        ValueError: If brain_type is unknown
        
    Example:
        >>> brain = create_brain('technical')
        >>> print(brain.get_name())
        technical
    """
    brain_type = brain_type.lower().strip()
    
    if brain_type == 'technical':
        return TechnicalBrain()
    
    elif brain_type == 'sentiment':
        return SentimentBrain()
    
    elif brain_type == 'pattern':
        return PatternBrain()
    
    else:
        available = ['technical', 'sentiment', 'pattern']
        raise ValueError(f"Unknown brain type: '{brain_type}'. Available: {available}")


def list_available_brains() -> List[Dict[str, Any]]:
    """
    List all available brain types.
    
    Returns:
        List of dicts with brain info
        
    Example:
        >>> for brain in list_available_brains():
        ...     print(f"{brain['name']}: {brain['description']}")
    """
    brains = [
        {
            'name': 'technical',
            'class': 'TechnicalBrain',
            'description': 'Technical analysis using RSI, MACD, Bollinger, SMA, EMA',
            'weight': 0.40,
            'status': 'active',
        },
        {
            'name': 'sentiment',
            'class': 'SentimentBrain',
            'description': 'News and market sentiment analysis with keyword scoring',
            'weight': 0.35,
            'status': 'active',
        },
        {
            'name': 'pattern',
            'class': 'PatternBrain',
            'description': 'Candlestick patterns, support/resistance, trend detection',
            'weight': 0.25,
            'status': 'active',
        },
    ]
    return brains


def reset_coordinator():
    """
    Reset the coordinator singleton.
    
    Useful for testing or when you want to reconfigure brains.
    """
    global _coordinator_instance, _brains_initialized
    _coordinator_instance = None
    _brains_initialized = False
    logger.info("BrainCoordinator reset")


def get_brain_status() -> Dict[str, Any]:
    """
    Get status of all brains for dashboard display.
    
    Returns:
        Dict with brain status info
        
    Example:
        >>> status = get_brain_status()
        >>> print(f"Active brains: {status['active_count']}")
    """
    status = {
        'initialized': _brains_initialized,
        'active_count': 0,
        'brains': [],
        'total_weight': 0.0,
    }
    
    try:
        if _coordinator_instance:
            brains = _coordinator_instance.list_brains()
            status['active_count'] = len(brains)
            status['brains'] = brains
            status['total_weight'] = sum(b.get('weight', 0) for b in brains)
    except Exception as e:
        logger.error(f"Error getting brain status: {e}")
    
    return status


# ══════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════

__all__ = [
    # Classes (direct import)
    "BaseBrain",
    "TechnicalBrain",
    "SentimentBrain",
    "PatternBrain",
    "BrainCoordinator",
    
    # Factory functions (recommended)
    "get_coordinator",
    "get_technical_brain",
    "get_sentiment_brain",
    "get_pattern_brain",
    "create_brain",
    "list_available_brains",
    "reset_coordinator",
    "get_brain_status",
    
    # Version
    "__version__",
]


# ══════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  BRAINS PACKAGE - Info")
    print("=" * 60)
    
    print(f"\n  Version: {__version__}")
    
    print("\n  Available Brains:")
    for brain in list_available_brains():
        status_icon = "✅" if brain['status'] == 'active' else "⏳"
        print(f"    {status_icon} {brain['name']:<12} ({brain['weight']:.0%}) - {brain['description']}")
    
    print("\n  Classes:")
    print("    • BaseBrain        → Abstract base class")
    print("    • TechnicalBrain   → Technical analysis (RSI, MACD, etc.)")
    print("    • SentimentBrain   → News sentiment analysis")
    print("    • PatternBrain     → Chart pattern recognition")
    print("    • BrainCoordinator → Aggregates all brains")
    
    print("\n  Factory Functions:")
    print("    • get_coordinator()      → BrainCoordinator (singleton)")
    print("    • get_technical_brain()  → TechnicalBrain instance")
    print("    • get_sentiment_brain()  → SentimentBrain instance")
    print("    • get_pattern_brain()    → PatternBrain instance")
    print("    • create_brain(type)     → Create brain by name")
    print("    • list_available_brains()→ List all brain types")
    print("    • get_brain_status()     → Status for dashboard")
    
    print("\n  Attempting to initialize...")
    
    try:
        coordinator = get_coordinator()
        brains = coordinator.list_brains()
        print(f"  ✅ Coordinator initialized with {len(brains)} brain(s)")
        
        for brain in brains:
            print(f"     • {brain['name']} (weight: {brain['weight']:.0%})")
        
        status = get_brain_status()
        print(f"\n  Brain Status:")
        print(f"    Initialized: {status['initialized']}")
        print(f"    Active: {status['active_count']}")
        print(f"    Total Weight: {status['total_weight']:.0%}")
        
        # Verify total weight is 100%
        if abs(status['total_weight'] - 1.0) < 0.01:
            print(f"    ✅ Weights sum to 100%")
        else:
            print(f"    ⚠️  Weights sum to {status['total_weight']:.0%} (expected 100%)")
        
    except Exception as e:
        print(f"  ⚠️  Cannot fully initialize: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60 + "\n")