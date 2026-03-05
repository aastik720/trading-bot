"""
Core Trading Engine Package - Phase 6
=======================================

This is where the bot actually TRADES. Everything before this phase
was building blocks — now we wire them all together into a living,
breathing trading loop.

Components
----------
TradingBot : class
    The main orchestrator. Initialises all components, runs the main
    trading loop, handles the complete lifecycle from market open
    to close.

PaperEngine : class
    Paper trading simulator. Tracks capital, executes simulated trades,
    monitors positions, calculates P&L, manages daily snapshots.

OrderManager : class
    Order lifecycle management. Creates orders from risk-approved
    trade params, executes them (paper or live), closes positions,
    handles cancellations.

Architecture
------------
    main.py
      │
      └── TradingBot (bot.py)
            │
            ├── MarketData ────────── prices & option chains
            ├── BrainCoordinator ──── signals (BUY/SELL/HOLD)
            ├── RiskManager ───────── gatekeeper (11 checks)
            ├── CircuitBreaker ────── emergency stop
            ├── OrderManager ──────── order lifecycle
            ├── PaperEngine ───────── simulated execution
            └── Repositories ──────── database persistence

Main Loop Flow (every SCAN_INTERVAL)
------------------------------------
    1. Pre-checks:
       ├── Is it a trading day?
       ├── Is market open?
       ├── Should close all positions? (near market close)
       └── Is circuit breaker safe?

    2. For each instrument (NIFTY, BANKNIFTY):
       ├── Brain analyzes → consensus signal
       ├── RiskManager gates → approved/rejected
       ├── OrderManager creates order
       └── PaperEngine executes & tracks

    3. Position monitoring:
       ├── Check all open positions
       ├── Update current prices
       └── Exit if SL/TP/TRAIL/TIME hit

    4. Sleep SCAN_INTERVAL seconds → repeat

Usage
-----
    from core import TradingBot

    bot = TradingBot()
    bot.start()  # Runs forever until stopped

    # Or for status check without running:
    status = bot.get_status()
    portfolio = bot.get_portfolio()

States
------
    STOPPED  → Bot is not running
    RUNNING  → Bot is actively trading
    PAUSED   → Bot monitors but doesn't take new trades
    ERROR    → Bot encountered a critical error

Daily Lifecycle
---------------
    Market Open (09:15):
        └── start_new_day() resets counters

    Trading Hours (09:15 - 14:30):
        └── Normal trading loop

    Close Window (14:30 - 15:15):
        └── No new trades, only monitor existing

    Position Close (15:15):
        └── close_all_positions("TIME")

    Market Close (15:30):
        └── save_daily_snapshot()
"""

from core.order_manager import OrderManager
from core.paper_engine import PaperEngine
from core.bot import TradingBot

__all__ = [
    "TradingBot",
    "PaperEngine",
    "OrderManager",
]

__version__ = "6.0.0"
__phase__ = 6
__description__ = "Core Trading Engine - The Bot Comes Alive"


def get_trading_bot():
    """
    Factory function to create a configured TradingBot instance.
    
    Returns
    -------
    TradingBot
        Fully initialised bot ready to start.
    
    Examples
    --------
        from core import get_trading_bot
        
        bot = get_trading_bot()
        bot.start()
    """
    return TradingBot()