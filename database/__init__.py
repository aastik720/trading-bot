"""
Database Layer Package
======================

This is the MEMORY of the trading bot. Every trade, every signal,
every profit and loss is recorded here permanently.

A profitable trader keeps meticulous records. This package ensures:
    - Every trade entry/exit is logged with exact timestamps
    - Every signal generated is stored (executed or not)
    - Daily equity snapshots for performance tracking
    - Position tracking with real-time unrealized PnL
    - Complete audit trail for review and improvement

Architecture:
    ┌──────────────────────────────────────────────┐
    │                 Repository Layer              │
    │  (TradeRepo, PositionRepo, SignalRepo, etc.) │
    ├──────────────────────────────────────────────┤
    │              DatabaseManager                  │
    │        (Engine, Session, Migrations)          │
    ├──────────────────────────────────────────────┤
    │              SQLAlchemy Models                 │
    │   (Trade, Position, Signal, DailySnapshot)   │
    ├──────────────────────────────────────────────┤
    │              SQLite Database                   │
    │           (trading_bot.db file)               │
    └──────────────────────────────────────────────┘

Models:
    Trade         - Complete trade lifecycle (entry → exit → PnL)
    Position      - Currently open positions with live PnL
    Signal        - All signals from brain system
    DailySnapshot - End-of-day equity curve tracking

Usage:
    from database import get_db_manager, get_trade_repo
    
    # Initialize database (auto-creates tables)
    db = get_db_manager()
    
    # Save a trade
    trade_repo = get_trade_repo()
    trade = trade_repo.save_trade({
        'symbol': 'NIFTY',
        'strike': 24500,
        'option_type': 'CE',
        'side': 'BUY',
        'entry_price': 125.50,
        'quantity': 25,
    })
    
    # Get today's trades
    today_trades = trade_repo.get_trades_today()
    
    # Get performance stats
    stats = trade_repo.get_stats()
    print(f"Win Rate: {stats['win_rate']}%")

Why SQLite?
    - Zero configuration (no server needed)
    - Single file (easy backup: just copy trading_bot.db)
    - Fast enough for our use case (< 100 trades/day)
    - Perfect for single-user trading bot
    - Can migrate to PostgreSQL later if needed
"""

# ══════════════════════════════════════════════════════════
# VERSION
# ══════════════════════════════════════════════════════════

__version__ = "1.0.0"


# ══════════════════════════════════════════════════════════
# IMPORTS - Lazy loading to avoid circular imports
# ══════════════════════════════════════════════════════════

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Track initialization status
_db_manager = None
_trade_repo = None
_position_repo = None
_signal_repo = None
_snapshot_repo = None
_initialized = False


# ══════════════════════════════════════════════════════════
# FACTORY FUNCTIONS
# ══════════════════════════════════════════════════════════

def get_db_manager():
    """
    Get or create the DatabaseManager singleton.
    
    Auto-creates the database file and tables on first call.
    
    Returns:
        DatabaseManager instance
        
    Example:
        >>> db = get_db_manager()
        >>> print(f"Database: {db.database_url}")
        >>> print(f"Tables: {db.get_table_count()}")
    """
    global _db_manager, _initialized
    
    if _db_manager is None:
        from database.repository import DatabaseManager
        
        try:
            from config.settings import settings
            database_url = settings.DATABASE_URL
        except Exception:
            database_url = "sqlite:///trading_bot.db"
            logger.warning("Could not load settings, using default database URL")
        
        _db_manager = DatabaseManager(database_url)
        
        if not _initialized:
            _db_manager.create_tables()
            _initialized = True
            logger.info(f"Database initialized: {database_url}")
    
    return _db_manager


def get_trade_repo():
    """
    Get or create the TradeRepository singleton.
    
    Returns:
        TradeRepository instance
        
    Example:
        >>> repo = get_trade_repo()
        >>> open_trades = repo.get_open_trades()
        >>> stats = repo.get_stats()
    """
    global _trade_repo
    
    if _trade_repo is None:
        from database.repository import TradeRepository
        db = get_db_manager()
        _trade_repo = TradeRepository(db)
    
    return _trade_repo


def get_position_repo():
    """
    Get or create the PositionRepository singleton.
    
    Returns:
        PositionRepository instance
        
    Example:
        >>> repo = get_position_repo()
        >>> positions = repo.get_open_positions()
    """
    global _position_repo
    
    if _position_repo is None:
        from database.repository import PositionRepository
        db = get_db_manager()
        _position_repo = PositionRepository(db)
    
    return _position_repo


def get_signal_repo():
    """
    Get or create the SignalRepository singleton.
    
    Returns:
        SignalRepository instance
        
    Example:
        >>> repo = get_signal_repo()
        >>> signals = repo.get_signals_today()
    """
    global _signal_repo
    
    if _signal_repo is None:
        from database.repository import SignalRepository
        db = get_db_manager()
        _signal_repo = SignalRepository(db)
    
    return _signal_repo


def get_snapshot_repo():
    """
    Get or create the SnapshotRepository singleton.
    
    Returns:
        SnapshotRepository instance
        
    Example:
        >>> repo = get_snapshot_repo()
        >>> latest = repo.get_latest_snapshot()
    """
    global _snapshot_repo
    
    if _snapshot_repo is None:
        from database.repository import SnapshotRepository
        db = get_db_manager()
        _snapshot_repo = SnapshotRepository(db)
    
    return _snapshot_repo


# ══════════════════════════════════════════════════════════
# ALIASES (for compatibility with core/bot.py)
# ══════════════════════════════════════════════════════════

# Some modules use get_database_manager instead of get_db_manager
get_database_manager = get_db_manager


# ══════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════

def reset_all():
    """
    Reset all singletons. Useful for testing.
    
    WARNING: This closes all database connections.
    """
    global _db_manager, _trade_repo, _position_repo
    global _signal_repo, _snapshot_repo, _initialized
    
    logger.warning("Resetting all database singletons")
    
    if _db_manager:
        try:
            _db_manager.close()
        except Exception:
            pass
    
    _db_manager = None
    _trade_repo = None
    _position_repo = None
    _signal_repo = None
    _snapshot_repo = None
    _initialized = False


def get_database_status() -> dict:
    """
    Get complete database status for dashboard display.
    
    Returns:
        dict: {
            'initialized': True/False,
            'database_url': 'sqlite:///...',
            'file_exists': True/False,
            'file_size_kb': 128,
            'table_count': 4,
            'trade_count': 150,
            'open_trades': 2,
            'signal_count': 500,
            'snapshot_count': 30,
            'today_trades': 5,
            'today_pnl': 1250.00,
        }
    """
    import os
    
    status = {
        'initialized': _initialized,
        'database_url': '',
        'file_exists': False,
        'file_size_kb': 0,
        'table_count': 0,
        'trade_count': 0,
        'open_trades': 0,
        'signal_count': 0,
        'snapshot_count': 0,
        'today_trades': 0,
        'today_pnl': 0.0,
    }
    
    try:
        db = get_db_manager()
        status['database_url'] = db.database_url
        
        # Check file
        db_path = db.database_url.replace('sqlite:///', '')
        if os.path.exists(db_path):
            status['file_exists'] = True
            status['file_size_kb'] = round(os.path.getsize(db_path) / 1024, 1)
        
        # Get counts
        status['table_count'] = db.get_table_count()
        
        # Trade stats
        try:
            trade_repo = get_trade_repo()
            status['trade_count'] = trade_repo.get_total_trade_count()
            status['open_trades'] = len(trade_repo.get_open_trades())
            
            today_trades = trade_repo.get_trades_today()
            status['today_trades'] = len(today_trades)
            status['today_pnl'] = sum(t.pnl or 0 for t in today_trades)
        except Exception:
            pass
        
        # Signal count
        try:
            signal_repo = get_signal_repo()
            status['signal_count'] = signal_repo.get_total_signal_count()
        except Exception:
            pass
        
        # Snapshot count
        try:
            snapshot_repo = get_snapshot_repo()
            status['snapshot_count'] = snapshot_repo.get_total_snapshot_count()
        except Exception:
            pass
        
    except Exception as e:
        logger.error(f"Error getting database status: {e}")
    
    return status


# ══════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════

__all__ = [
    # Factory functions
    "get_db_manager",
    "get_database_manager",  # Alias for compatibility
    "get_trade_repo",
    "get_position_repo",
    "get_signal_repo",
    "get_snapshot_repo",
    
    # Utilities
    "reset_all",
    "get_database_status",
]


# ══════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  DATABASE LAYER - Package Info")
    print("=" * 60)
    
    print(f"\n  Version: {__version__}")
    
    print(f"\n  Factory Functions:")
    print(f"    • get_db_manager()       → DatabaseManager")
    print(f"    • get_database_manager() → DatabaseManager (alias)")
    print(f"    • get_trade_repo()       → TradeRepository")
    print(f"    • get_position_repo()    → PositionRepository")
    print(f"    • get_signal_repo()      → SignalRepository")
    print(f"    • get_snapshot_repo()    → SnapshotRepository")
    
    print(f"\n  Utilities:")
    print(f"    • get_database_status() → Full status dict")
    print(f"    • reset_all()           → Reset connections")
    
    print(f"\n  Database Models:")
    print(f"    • Trade         → Complete trade lifecycle")
    print(f"    • Position      → Open position tracking")
    print(f"    • Signal        → Brain signal history")
    print(f"    • DailySnapshot → Equity curve data")
    
    # Try to initialize
    print(f"\n  Attempting initialization...")
    try:
        db_status = get_database_status()
        print(f"    Initialized:  {'✅ Yes' if db_status['initialized'] else '❌ No'}")
        print(f"    Database:     {db_status['database_url']}")
        print(f"    File Exists:  {'✅ Yes' if db_status['file_exists'] else '❌ No'}")
        print(f"    File Size:    {db_status['file_size_kb']} KB")
        print(f"    Tables:       {db_status['table_count']}")
        print(f"    Total Trades: {db_status['trade_count']}")
        print(f"    Open Trades:  {db_status['open_trades']}")
    except Exception as e:
        print(f"    ❌ Error: {e}")
        print(f"    (This is expected if models.py and repository.py are not yet created)")
    
    print("\n" + "=" * 60 + "\n")