"""
Brain Coordinator Module
========================

The ORCHESTRATOR that manages all brains and aggregates their signals
into a single consensus decision.

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                    BrainCoordinator                         │
    │                                                             │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
    │  │ Technical   │  │ Sentiment   │  │ Pattern     │         │
    │  │ Brain (40%) │  │ Brain (35%) │  │ Brain (25%) │         │
    │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
    │         │                │                │                 │
    │         │    Signal      │    Signal      │    Signal       │
    │         ▼                ▼                ▼                 │
    │  ┌─────────────────────────────────────────────────────┐   │
    │  │              Weighted Aggregation                    │   │
    │  │  BUY_score = Σ(confidence × weight) for BUY signals  │   │
    │  │  SELL_score = Σ(confidence × weight) for SELL signals│   │
    │  └──────────────────────┬──────────────────────────────┘   │
    │                         │                                   │
    │                         ▼                                   │
    │              ┌─────────────────────┐                        │
    │              │  Consensus Signal   │                        │
    │              │  BUY / SELL / HOLD  │                        │
    │              └─────────────────────┘                        │
    └─────────────────────────────────────────────────────────────┘

Aggregation Logic:
    1. Run ALL brains on the symbol
    2. Collect signals from each brain
    3. Calculate weighted scores:
       - BUY score = sum of (confidence × weight) for BUY signals
       - SELL score = sum of (confidence × weight) for SELL signals
    4. Consensus rules:
       - If BUY_score > threshold AND BUY_score > SELL_score → BUY
       - If SELL_score > threshold AND SELL_score > BUY_score → SELL
       - Otherwise → HOLD

Usage:
    from brains.coordinator import BrainCoordinator
    from brains.technical import TechnicalBrain
    from brains.sentiment import SentimentBrain
    from brains.pattern import PatternBrain
    from data import get_market_data
    
    # Create coordinator and add brains
    coordinator = BrainCoordinator()
    coordinator.add_brain(TechnicalBrain())
    coordinator.add_brain(SentimentBrain())
    coordinator.add_brain(PatternBrain())
    
    # Analyze
    md = get_market_data()
    result = coordinator.analyze_symbol("NIFTY", md)
    
    print(f"Consensus: {result['action']} with {result['confidence']:.1%}")
    print(f"Reasoning: {result['reasoning']}")
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

# Import base brain
from brains.base import BaseBrain

# Import utilities
try:
    from utils.helpers import get_ist_now
    from utils.exceptions import BrainError
    from config.constants import (
        SIGNAL_BUY,
        SIGNAL_SELL,
        SIGNAL_HOLD,
        MIN_CONFIDENCE_THRESHOLD,
        STRONG_SIGNAL_THRESHOLD,
    )
except ImportError as e:
    logging.warning(f"Could not import some modules: {e}")
    
    def get_ist_now():
        from datetime import timedelta
        return datetime.utcnow() + timedelta(hours=5, minutes=30)
    
    class BrainError(Exception):
        pass
    
    SIGNAL_BUY = 'BUY'
    SIGNAL_SELL = 'SELL'
    SIGNAL_HOLD = 'HOLD'
    MIN_CONFIDENCE_THRESHOLD = 0.60
    STRONG_SIGNAL_THRESHOLD = 0.75


# Try to import database for signal storage
try:
    from database import get_signal_repo
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False
    logging.warning("Database not available for signal storage")


# Setup logging
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# CONSENSUS SIGNAL TYPE
# ══════════════════════════════════════════════════════════

class ConsensusSignal:
    """
    Represents the aggregated consensus from all brains.
    
    This is what the trading engine uses to make decisions.
    """
    
    def __init__(
        self,
        symbol: str,
        action: str,
        confidence: float,
        brain_signals: List[Dict[str, Any]],
        reasoning: str,
        option_recommendation: Optional[Dict[str, str]] = None,
    ):
        self.signal_id = self._generate_id()
        self.symbol = symbol
        self.action = action
        self.confidence = confidence
        self.brain_signals = brain_signals
        self.reasoning = reasoning
        self.option_recommendation = option_recommendation
        self.timestamp = get_ist_now()
    
    @staticmethod
    def _generate_id() -> str:
        """Generate unique consensus signal ID."""
        now = get_ist_now()
        import random
        rand = random.randint(1000, 9999)
        return f"CON-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{rand}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'signal_id': self.signal_id,
            'symbol': self.symbol,
            'action': self.action,
            'confidence': self.confidence,
            'brain_signals': self.brain_signals,
            'reasoning': self.reasoning,
            'option_recommendation': self.option_recommendation,
            'timestamp': self.timestamp,
            'brain_count': len(self.brain_signals),
        }
    
    @property
    def is_actionable(self) -> bool:
        """Check if this signal should be acted upon."""
        return (
            self.action in [SIGNAL_BUY, SIGNAL_SELL] and
            self.confidence >= MIN_CONFIDENCE_THRESHOLD
        )
    
    @property
    def is_strong(self) -> bool:
        """Check if this is a strong signal."""
        return self.confidence >= STRONG_SIGNAL_THRESHOLD
    
    def __repr__(self) -> str:
        return (
            f"<ConsensusSignal({self.signal_id}) {self.action} {self.symbol} "
            f"conf={self.confidence:.1%} brains={len(self.brain_signals)}>"
        )


# ══════════════════════════════════════════════════════════
# BRAIN COORDINATOR CLASS
# ══════════════════════════════════════════════════════════

class BrainCoordinator:
    """
    Orchestrates multiple brains and aggregates their signals.
    
    The coordinator:
        1. Manages a collection of brains
        2. Runs all brains on each symbol
        3. Aggregates signals using weighted voting
        4. Returns a consensus signal
        5. Saves signals to database for tracking
    
    Attributes:
        brains: Dict of brain_name -> BaseBrain instance
        save_signals: Whether to save signals to database
    """
    
    def __init__(self, save_signals: bool = True):
        """
        Initialize the coordinator.
        
        Args:
            save_signals: Whether to save signals to database
        """
        self._brains: Dict[str, BaseBrain] = {}
        self._save_signals = save_signals and DATABASE_AVAILABLE
        self._analysis_count = 0
        self._last_analysis_time: Optional[datetime] = None
        
        logger.info("BrainCoordinator initialized")
    
    # ══════════════════════════════════════════════════════
    # BRAIN MANAGEMENT
    # ══════════════════════════════════════════════════════
    
    def add_brain(self, brain: BaseBrain) -> None:
        """
        Add a brain to the coordinator.
        
        Args:
            brain: Brain instance (must inherit from BaseBrain)
            
        Raises:
            TypeError: If brain doesn't inherit from BaseBrain
            ValueError: If brain with same name already exists
        """
        if not isinstance(brain, BaseBrain):
            raise TypeError(f"Brain must inherit from BaseBrain, got {type(brain)}")
        
        name = brain.get_name()
        
        if name in self._brains:
            logger.warning(f"Replacing existing brain: {name}")
        
        self._brains[name] = brain
        logger.info(f"Brain added: {name} (weight: {brain.get_weight():.0%})")
    
    def remove_brain(self, brain_name: str) -> bool:
        """
        Remove a brain from the coordinator.
        
        Args:
            brain_name: Name of brain to remove
            
        Returns:
            bool: True if removed, False if not found
        """
        if brain_name in self._brains:
            del self._brains[brain_name]
            logger.info(f"Brain removed: {brain_name}")
            return True
        
        logger.warning(f"Brain not found: {brain_name}")
        return False
    
    def get_brain(self, name: str) -> Optional[BaseBrain]:
        """
        Get a brain by name.
        
        Args:
            name: Brain name
            
        Returns:
            BaseBrain instance or None
        """
        return self._brains.get(name)
    
    def list_brains(self) -> List[Dict[str, Any]]:
        """
        List all registered brains.
        
        Returns:
            List of brain info dicts
        """
        brains = []
        
        for name, brain in self._brains.items():
            brains.append({
                'name': name,
                'weight': brain.get_weight(),
                'status': 'active',
                'stats': brain.get_stats(),
            })
        
        return brains
    
    def get_total_weight(self) -> float:
        """Get sum of all brain weights."""
        return sum(b.get_weight() for b in self._brains.values())
    
    def _get_active_weight(self, active_brains: List[str]) -> float:
        """
        Get sum of weights for active (non-failed) brains.
        
        Used for renormalization when some brains fail.
        
        Args:
            active_brains: List of brain names that succeeded
            
        Returns:
            Sum of weights for active brains
        """
        total = 0.0
        for name in active_brains:
            if name in self._brains:
                total += self._brains[name].get_weight()
        return total
    
    # ══════════════════════════════════════════════════════
    # ANALYSIS
    # ══════════════════════════════════════════════════════
    
    def analyze_symbol(self, symbol: str, market_data: Any) -> Dict[str, Any]:
        """
        Analyze a single symbol using all brains.
        
        Args:
            symbol: Symbol to analyze (e.g., 'NIFTY')
            market_data: MarketData instance
            
        Returns:
            ConsensusSignal as dict with:
                - signal_id: Unique ID
                - symbol: Symbol analyzed
                - action: BUY/SELL/HOLD
                - confidence: 0.0 to 1.0
                - brain_signals: List of individual brain signals
                - reasoning: Combined reasoning
                - option_recommendation: Option details or None
                - timestamp: Analysis time
        """
        symbol = symbol.upper().strip()
        logger.info(f"Coordinator analyzing {symbol} with {len(self._brains)} brain(s)...")
        
        if not self._brains:
            logger.warning("No brains registered!")
            return self._create_hold_consensus(
                symbol=symbol,
                reasoning="No analysis brains available"
            ).to_dict()
        
        # Collect signals from all brains
        brain_signals = []
        failed_brains = []
        active_brains = []
        
        for name, brain in self._brains.items():
            try:
                signal = brain.analyze(symbol, market_data)
                brain_signals.append(signal)
                active_brains.append(name)
                
                logger.debug(
                    f"Brain {name}: {signal['action']} "
                    f"(conf: {signal['confidence']:.1%})"
                )
                
                # Save to database
                if self._save_signals:
                    self._save_signal_to_db(signal)
                    
            except BrainError as e:
                # Expected brain error - log and continue
                logger.warning(f"Brain {name} reported error: {e}")
                failed_brains.append(name)
                continue
            except Exception as e:
                # Unexpected error - log with more detail
                logger.error(f"Brain {name} failed unexpectedly: {e}")
                failed_brains.append(name)
                continue
        
        # If all brains failed
        if not brain_signals:
            error_msg = f"All brains failed: {', '.join(failed_brains)}"
            logger.error(error_msg)
            return self._create_hold_consensus(
                symbol=symbol,
                reasoning=error_msg
            ).to_dict()
        
        # Log if some brains failed (but not all)
        if failed_brains:
            logger.warning(
                f"Some brains failed for {symbol}: {', '.join(failed_brains)}. "
                f"Continuing with {len(active_brains)} brain(s): {', '.join(active_brains)}"
            )
        
        # Aggregate signals (with active brains for weight renormalization)
        consensus = self._aggregate(symbol, brain_signals, active_brains)
        
        # Update stats
        self._analysis_count += 1
        self._last_analysis_time = get_ist_now()
        
        logger.info(
            f"Coordinator consensus for {symbol}: {consensus.action} "
            f"with {consensus.confidence:.1%} confidence "
            f"(from {len(brain_signals)} brain(s))"
        )
        
        return consensus.to_dict()
    
    def analyze_all(
        self,
        symbols: List[str],
        market_data: Any
    ) -> Dict[str, Dict[str, Any]]:
        """
        Analyze multiple symbols.
        
        Args:
            symbols: List of symbols to analyze
            market_data: MarketData instance
            
        Returns:
            Dict mapping symbol -> consensus signal dict
        """
        results = {}
        
        for symbol in symbols:
            try:
                results[symbol] = self.analyze_symbol(symbol, market_data)
            except Exception as e:
                logger.error(f"Failed to analyze {symbol}: {e}")
                results[symbol] = self._create_hold_consensus(
                    symbol=symbol,
                    reasoning=f"Analysis failed: {e}"
                ).to_dict()
        
        return results
    
    # ══════════════════════════════════════════════════════
    # AGGREGATION
    # ══════════════════════════════════════════════════════
    
    def _aggregate(
        self,
        symbol: str,
        signals: List[Dict[str, Any]],
        active_brains: Optional[List[str]] = None
    ) -> ConsensusSignal:
        """
        Aggregate multiple brain signals into consensus.
        
        Weighted voting:
            - BUY score = Σ(confidence × weight) for BUY signals
            - SELL score = Σ(confidence × weight) for SELL signals
            - HOLD signals don't contribute to either
        
        Weight Renormalization:
            - If some brains fail, weights are renormalized among active brains
            - This ensures failed brains don't affect the final score
        
        Decision rules:
            - If BUY_score > threshold AND BUY_score > SELL_score → BUY
            - If SELL_score > threshold AND SELL_score > BUY_score → SELL
            - Otherwise → HOLD
        
        Args:
            symbol: Symbol being analyzed
            signals: List of brain signals
            active_brains: List of brain names that succeeded (for renormalization)
            
        Returns:
            ConsensusSignal
        """
        buy_score = 0.0
        sell_score = 0.0
        hold_count = 0
        
        buy_reasons = []
        sell_reasons = []
        
        best_option_rec = None
        best_option_confidence = 0.0
        
        for signal in signals:
            brain_name = signal.get('brain', 'unknown')
            action = signal.get('action', SIGNAL_HOLD)
            confidence = signal.get('confidence', 0.0)
            
            # Get brain weight
            brain = self._brains.get(brain_name)
            weight = brain.get_weight() if brain else 0.1
            
            # Calculate weighted score
            weighted_score = confidence * weight
            
            if action == SIGNAL_BUY:
                buy_score += weighted_score
                reason = signal.get('reasoning', '')
                if reason:
                    buy_reasons.append(f"{brain_name}: {reason}")
                
                # Track best option recommendation
                opt_rec = signal.get('option_recommendation')
                if opt_rec and confidence > best_option_confidence:
                    best_option_rec = opt_rec
                    best_option_confidence = confidence
                    
            elif action == SIGNAL_SELL:
                sell_score += weighted_score
                reason = signal.get('reasoning', '')
                if reason:
                    sell_reasons.append(f"{brain_name}: {reason}")
                
                # Track best option recommendation
                opt_rec = signal.get('option_recommendation')
                if opt_rec and confidence > best_option_confidence:
                    best_option_rec = opt_rec
                    best_option_confidence = confidence
                    
            else:
                hold_count += 1
        
        # Normalize scores by total weight
        # Use active brains weight if some brains failed (renormalization)
        if active_brains is not None:
            total_weight = self._get_active_weight(active_brains)
        else:
            total_weight = self.get_total_weight()
        
        if total_weight > 0:
            buy_score_norm = buy_score / total_weight
            sell_score_norm = sell_score / total_weight
        else:
            buy_score_norm = buy_score
            sell_score_norm = sell_score
        
        # Determine consensus action
        if buy_score_norm >= MIN_CONFIDENCE_THRESHOLD and buy_score_norm > sell_score_norm:
            action = SIGNAL_BUY
            confidence = buy_score_norm
            reasoning = self._combine_reasons(buy_reasons, "Bullish consensus")
            option_rec = best_option_rec
            
        elif sell_score_norm >= MIN_CONFIDENCE_THRESHOLD and sell_score_norm > buy_score_norm:
            action = SIGNAL_SELL
            confidence = sell_score_norm
            reasoning = self._combine_reasons(sell_reasons, "Bearish consensus")
            option_rec = best_option_rec
            
        else:
            action = SIGNAL_HOLD
            confidence = max(buy_score_norm, sell_score_norm) * 0.5
            
            if buy_score_norm > sell_score_norm:
                reasoning = f"Slight bullish lean but below threshold (buy: {buy_score_norm:.1%}, sell: {sell_score_norm:.1%})"
            elif sell_score_norm > buy_score_norm:
                reasoning = f"Slight bearish lean but below threshold (sell: {sell_score_norm:.1%}, buy: {buy_score_norm:.1%})"
            else:
                reasoning = f"No clear direction (buy: {buy_score_norm:.1%}, sell: {sell_score_norm:.1%})"
            
            option_rec = None
        
        # Clamp confidence
        confidence = max(0.0, min(1.0, confidence))
        
        return ConsensusSignal(
            symbol=symbol,
            action=action,
            confidence=confidence,
            brain_signals=signals,
            reasoning=reasoning,
            option_recommendation=option_rec,
        )
    
    def _combine_reasons(self, reasons: List[str], prefix: str) -> str:
        """Combine multiple reasons into one string."""
        if not reasons:
            return prefix
        
        if len(reasons) == 1:
            return reasons[0]
        
        # Take first 2 reasons
        combined = " | ".join(reasons[:2])
        if len(reasons) > 2:
            combined += f" (+{len(reasons) - 2} more)"
        
        return combined
    
    def _create_hold_consensus(self, symbol: str, reasoning: str) -> ConsensusSignal:
        """Create a HOLD consensus signal."""
        return ConsensusSignal(
            symbol=symbol,
            action=SIGNAL_HOLD,
            confidence=0.0,
            brain_signals=[],
            reasoning=reasoning,
            option_recommendation=None,
        )
    
    # ══════════════════════════════════════════════════════
    # DATABASE
    # ══════════════════════════════════════════════════════
    
    def _save_signal_to_db(self, signal: Dict[str, Any]) -> None:
        """Save a brain signal to database."""
        if not DATABASE_AVAILABLE:
            return
        
        try:
            repo = get_signal_repo()
            repo.save_signal({
                'signal_id': signal.get('signal_id'),
                'symbol': signal.get('symbol'),
                'instrument': signal.get('instrument'),
                'action': signal.get('action'),
                'confidence': signal.get('confidence'),
                'brain_name': signal.get('brain'),
                'reasoning': signal.get('reasoning'),
                'indicators': signal.get('indicators'),
                'executed': False,
                'timestamp': signal.get('timestamp'),
            })
        except Exception as e:
            logger.warning(f"Failed to save signal to database: {e}")
    
    # ══════════════════════════════════════════════════════
    # STATS & INFO
    # ══════════════════════════════════════════════════════
    
    def get_brain_performance(self) -> Dict[str, Any]:
        """
        Get performance stats for each brain.
        
        Returns:
            Dict with brain performance metrics
        """
        performance = {}
        
        for name, brain in self._brains.items():
            stats = brain.get_stats()
            performance[name] = {
                'name': name,
                'weight': brain.get_weight(),
                'analysis_count': stats.get('analysis_count', 0),
                'last_analysis': stats.get('last_analysis'),
                'status': 'active',
            }
        
        return performance
    
    def get_stats(self) -> Dict[str, Any]:
        """Get coordinator statistics."""
        return {
            'brain_count': len(self._brains),
            'total_weight': self.get_total_weight(),
            'analysis_count': self._analysis_count,
            'last_analysis': self._last_analysis_time,
            'save_signals': self._save_signals,
            'brains': list(self._brains.keys()),
        }
    
    def __repr__(self) -> str:
        return f"<BrainCoordinator(brains={len(self._brains)}, analyses={self._analysis_count})>"


# ══════════════════════════════════════════════════════════
# FACTORY FUNCTION - Creates coordinator with all brains
# ══════════════════════════════════════════════════════════

def create_coordinator_with_all_brains(save_signals: bool = True) -> BrainCoordinator:
    """
    Factory function to create a BrainCoordinator with all available brains.
    
    This function attempts to import and add all brains:
    - TechnicalBrain (weight: 0.40)
    - SentimentBrain (weight: 0.35)
    - PatternBrain (weight: 0.25)
    
    If a brain fails to import, it logs a warning and continues with others.
    
    Args:
        save_signals: Whether to save signals to database
        
    Returns:
        BrainCoordinator with all available brains registered
        
    Example:
        >>> coordinator = create_coordinator_with_all_brains()
        >>> print(f"Loaded {len(coordinator.list_brains())} brains")
        >>> result = coordinator.analyze_symbol("NIFTY", market_data)
    """
    coordinator = BrainCoordinator(save_signals=save_signals)
    
    # Try to add TechnicalBrain
    try:
        from brains.technical import TechnicalBrain
        coordinator.add_brain(TechnicalBrain())
        logger.info("TechnicalBrain loaded successfully")
    except ImportError as e:
        logger.warning(f"Could not import TechnicalBrain: {e}")
    except Exception as e:
        logger.error(f"Error initializing TechnicalBrain: {e}")
    
    # Try to add SentimentBrain
    try:
        from brains.sentiment import SentimentBrain
        coordinator.add_brain(SentimentBrain())
        logger.info("SentimentBrain loaded successfully")
    except ImportError as e:
        logger.warning(f"Could not import SentimentBrain: {e}")
    except Exception as e:
        logger.error(f"Error initializing SentimentBrain: {e}")
    
    # Try to add PatternBrain
    try:
        from brains.pattern import PatternBrain
        coordinator.add_brain(PatternBrain())
        logger.info("PatternBrain loaded successfully")
    except ImportError as e:
        logger.warning(f"Could not import PatternBrain: {e}")
    except Exception as e:
        logger.error(f"Error initializing PatternBrain: {e}")
    
    # Log summary
    brain_count = len(coordinator.list_brains())
    total_weight = coordinator.get_total_weight()
    
    if brain_count == 0:
        logger.error("No brains could be loaded! Coordinator will return HOLD for all signals.")
    elif total_weight < 0.99 or total_weight > 1.01:
        logger.warning(
            f"Total brain weight is {total_weight:.2f}, expected 1.00. "
            f"Some brains may have failed to load."
        )
    else:
        logger.info(
            f"BrainCoordinator ready with {brain_count} brains, "
            f"total weight: {total_weight:.2f}"
        )
    
    return coordinator


# ══════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  BRAIN COORDINATOR - TEST")
    print("=" * 60)
    
    # Setup logging for test
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create coordinator
    print("\n  1. Creating BrainCoordinator...")
    coordinator = BrainCoordinator(save_signals=False)  # Don't save during test
    print(f"     ✅ Created: {coordinator}")
    
    # Add Technical Brain
    print("\n  2. Adding TechnicalBrain...")
    try:
        from brains.technical import TechnicalBrain
        tech_brain = TechnicalBrain()
        coordinator.add_brain(tech_brain)
        print(f"     ✅ Added: {tech_brain}")
    except Exception as e:
        print(f"     ❌ Error: {e}")
    
    # Add Sentiment Brain
    print("\n  3. Adding SentimentBrain...")
    try:
        from brains.sentiment import SentimentBrain
        sent_brain = SentimentBrain()
        coordinator.add_brain(sent_brain)
        print(f"     ✅ Added: {sent_brain}")
    except Exception as e:
        print(f"     ❌ Error: {e}")
    
    # Add Pattern Brain
    print("\n  4. Adding PatternBrain...")
    try:
        from brains.pattern import PatternBrain
        pat_brain = PatternBrain()
        coordinator.add_brain(pat_brain)
        print(f"     ✅ Added: {pat_brain}")
    except Exception as e:
        print(f"     ❌ Error: {e}")
    
    # List brains
    print("\n  5. Listing brains...")
    for brain in coordinator.list_brains():
        print(f"     • {brain['name']} (weight: {brain['weight']:.0%})")
    
    print(f"     Total weight: {coordinator.get_total_weight():.0%}")
    
    # Analyze single symbol
    print("\n  6. Analyzing NIFTY...")
    try:
        # Try with real market data
        try:
            from data import get_market_data
            md = get_market_data()
        except:
            md = None
        
        result = coordinator.analyze_symbol("NIFTY", md)
        
        action = result['action']
        confidence = result['confidence']
        
        action_icon = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
        
        print(f"     {action_icon} Consensus: {action} with {confidence:.1%} confidence")
        print(f"     Reasoning: {result['reasoning']}")
        print(f"     Brains used: {result['brain_count']}")
        
        if result['option_recommendation']:
            opt = result['option_recommendation']
            print(f"     Option: {opt['type']} {opt['strike_preference']} {opt['expiry']}")
        
        # Show individual brain signals
        print(f"\n     Individual Brain Signals:")
        for sig in result['brain_signals']:
            brain = sig.get('brain', 'unknown')
            act = sig.get('action', '?')
            conf = sig.get('confidence', 0)
            icon = "🟢" if act == "BUY" else "🔴" if act == "SELL" else "⚪"
            print(f"       {icon} {brain}: {act} ({conf:.1%})")
            
    except Exception as e:
        print(f"     ❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Analyze all instruments
    print("\n  7. Analyzing all instruments...")
    try:
        results = coordinator.analyze_all(["NIFTY", "BANKNIFTY"], md)
        
        for symbol, result in results.items():
            action = result['action']
            confidence = result['confidence']
            icon = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
            print(f"     {icon} {symbol}: {action} ({confidence:.1%})")
            
    except Exception as e:
        print(f"     ❌ Error: {e}")
    
    # Get stats
    print("\n  8. Coordinator Stats...")
    stats = coordinator.get_stats()
    print(f"     Brain count: {stats['brain_count']}")
    print(f"     Total weight: {stats['total_weight']:.0%}")
    print(f"     Analysis count: {stats['analysis_count']}")
    
    # Brain performance
    print("\n  9. Brain Performance...")
    perf = coordinator.get_brain_performance()
    for name, data in perf.items():
        print(f"     • {name}: {data['analysis_count']} analyses, weight: {data['weight']:.0%}")
    
    # Test consensus with multiple signals
    print("\n  10. Testing aggregation logic...")
    
    # Create mock signals
    mock_signals = [
        {
            'signal_id': 'TEST-001',
            'symbol': 'NIFTY',
            'action': 'BUY',
            'confidence': 0.75,
            'brain': 'technical',
            'reasoning': 'RSI oversold',
            'indicators': {},
            'option_recommendation': {'type': 'CE', 'strike_preference': 'ATM', 'expiry': 'WEEKLY'},
        },
        {
            'signal_id': 'TEST-002',
            'symbol': 'NIFTY',
            'action': 'BUY',
            'confidence': 0.65,
            'brain': 'sentiment',
            'reasoning': 'Positive news',
            'indicators': {},
            'option_recommendation': {'type': 'CE', 'strike_preference': 'OTM1', 'expiry': 'WEEKLY'},
        },
        {
            'signal_id': 'TEST-003',
            'symbol': 'NIFTY',
            'action': 'HOLD',
            'confidence': 0.50,
            'brain': 'pattern',
            'reasoning': 'No clear pattern',
            'indicators': {},
            'option_recommendation': None,
        },
    ]
    
    # Create fresh coordinator for this test
    test_coord = BrainCoordinator(save_signals=False)
    
    # Manually add brains with known weights
    class MockBrain(BaseBrain):
        def __init__(self, name, weight):
            super().__init__(name, weight)
        def analyze(self, symbol, market_data):
            return {}
    
    test_coord._brains['technical'] = MockBrain('technical', 0.40)
    test_coord._brains['sentiment'] = MockBrain('sentiment', 0.35)
    test_coord._brains['pattern'] = MockBrain('pattern', 0.25)
    
    # Test with all 3 brains active
    consensus = test_coord._aggregate(
        "NIFTY", 
        mock_signals, 
        active_brains=['technical', 'sentiment', 'pattern']
    )
    
    print(f"     Mock signals: technical=BUY(75%), sentiment=BUY(65%), pattern=HOLD(50%)")
    print(f"     Total weight: {test_coord.get_total_weight():.0%}")
    print(f"     Consensus: {consensus.action} with {consensus.confidence:.1%}")
    print(f"     Is actionable: {consensus.is_actionable}")
    print(f"     Is strong: {consensus.is_strong}")
    
    # Test weight renormalization when one brain fails
    print("\n  11. Testing weight renormalization (pattern brain failed)...")
    
    mock_signals_2_brains = [
        {
            'signal_id': 'TEST-001',
            'symbol': 'NIFTY',
            'action': 'BUY',
            'confidence': 0.75,
            'brain': 'technical',
            'reasoning': 'RSI oversold',
            'indicators': {},
            'option_recommendation': {'type': 'CE', 'strike_preference': 'ATM', 'expiry': 'WEEKLY'},
        },
        {
            'signal_id': 'TEST-002',
            'symbol': 'NIFTY',
            'action': 'BUY',
            'confidence': 0.65,
            'brain': 'sentiment',
            'reasoning': 'Positive news',
            'indicators': {},
            'option_recommendation': {'type': 'CE', 'strike_preference': 'OTM1', 'expiry': 'WEEKLY'},
        },
    ]
    
    # Only technical and sentiment are active (pattern failed)
    consensus_renorm = test_coord._aggregate(
        "NIFTY", 
        mock_signals_2_brains, 
        active_brains=['technical', 'sentiment']  # pattern is not in this list
    )
    
    active_weight = test_coord._get_active_weight(['technical', 'sentiment'])
    print(f"     Active brains: technical, sentiment (pattern failed)")
    print(f"     Active weight: {active_weight:.0%} (renormalized from 100%)")
    print(f"     Mock signals: technical=BUY(75%), sentiment=BUY(65%)")
    print(f"     Consensus: {consensus_renorm.action} with {consensus_renorm.confidence:.1%}")
    
    # Test factory function
    print("\n  12. Testing factory function...")
    try:
        full_coordinator = create_coordinator_with_all_brains(save_signals=False)
        print(f"     ✅ Created coordinator with {len(full_coordinator.list_brains())} brains")
        for brain in full_coordinator.list_brains():
            print(f"        • {brain['name']} (weight: {brain['weight']:.0%})")
    except Exception as e:
        print(f"     ❌ Error: {e}")
    
    print("\n" + "=" * 60)
    print("  Brain Coordinator Tests Complete! ✅")
    print("=" * 60 + "\n")