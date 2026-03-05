"""
Database package entry point.
Runs when you execute: python -m database
"""

# Run the self-test from __init__.py
from database import __version__, get_database_status

print("\n" + "=" * 60)
print("  DATABASE LAYER - Package Info")
print("=" * 60)

print(f"\n  Version: {__version__}")

print(f"\n  Factory Functions:")
print(f"    • get_db_manager()     → DatabaseManager")
print(f"    • get_trade_repo()     → TradeRepository")
print(f"    • get_position_repo()  → PositionRepository")
print(f"    • get_signal_repo()    → SignalRepository")
print(f"    • get_snapshot_repo()  → SnapshotRepository")

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
    print(f"    ⚠️  Cannot fully initialize yet: {e}")
    print(f"    (Expected if models.py and repository.py not created yet)")

print("\n" + "=" * 60 + "\n")