"""
Risk Management Package - Phase 5
==================================

The GATEKEEPER layer of the trading bot.
Every signal from the Brain (Phase 4) must pass through Risk Management
before it can become an actual trade.

Components
----------
RiskManager : class
    Main risk gatekeeper. Validates every trade against 11 sequential checks
    including market status, capital limits, position limits, premium bounds,
    IV thresholds, and duplicate detection. Also handles stop-loss,
    take-profit, trailing-stop calculations, and position exit monitoring.

CircuitBreaker : class
    Emergency shutdown system. Triggers automatically on consecutive losses
    or daily loss limit breach. Supports manual trigger/reset via future
    Telegram integration (/kill, /resume). Has time-based cooldown with
    auto-reset capability.

Flow
----
    Brain Signal
        │
        ▼
    RiskManager.can_trade()
        │
        ├── Check 1:  Market Open?
        ├── Check 2:  Circuit Breaker Safe?
        ├── Check 3:  Daily Trade Limit?
        ├── Check 4:  Daily Loss Limit?
        ├── Check 5:  Max Positions?
        ├── Check 6:  Capital Available?
        ├── Check 7:  Confidence Threshold?
        ├── Check 8:  Premium Bounds?
        ├── Check 9:  IV Threshold?
        ├── Check 10: Expiry Valid?
        ├── Check 11: Duplicate Position?
        │
        ▼
    Approved trade_params dict ──► Execution (Phase 6)

Usage
-----
    from risk import RiskManager, CircuitBreaker

    circuit_breaker = CircuitBreaker(
        max_consecutive_losses=5,
        cooldown_seconds=3600,
        max_daily_loss_pct=3.0,
        initial_capital=10000.0
    )

    risk_manager = RiskManager(
        settings=settings,
        trade_repository=trade_repo,
        position_repository=position_repo,
        circuit_breaker=circuit_breaker
    )

    approved, reason, trade_params = risk_manager.can_trade(signal, capital)
"""

from risk.circuit_breaker import CircuitBreaker
from risk.risk_manager import RiskManager

__all__ = [
    "RiskManager",
    "CircuitBreaker",
]

__version__ = "5.0.0"
__phase__ = 5
__description__ = "Risk Management - The Gatekeeper"