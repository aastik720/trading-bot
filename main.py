"""
Trading Bot - Main Entry Point
==============================

This is the main entry point for the trading bot.

Usage:
    python main.py              # START THE BOT (live trading loop)
    python main.py --status     # Quick status check (no trading)
    python main.py --test       # Run tests
    python main.py --prices     # Show live prices only
    python main.py --dashboard  # Show full dashboard (no trading)
    python main.py --dry-run    # Simulate one loop iteration

Completed Phases:
    - Phase 1: Foundation (config, utils, helpers) ✅
    - Phase 2: Data Layer (Dhan, Finnhub, MarketData) ✅
    - Phase 3: Database Layer (models, repository) ✅
    - Phase 4: Strategy Layer (technical brain, coordinator) ✅
    - Phase 5: Risk Management (risk manager, circuit breaker) ✅
    - Phase 6: Paper Trading Engine (order manager, paper engine, bot) ✅

Future Phases:
    - Phase 7: Telegram Integration
    - Phase 8: Live Trading
"""

import sys
import time
import argparse
import logging
from datetime import datetime


# ══════════════════════════════════════════════════════════
# CHECK PYTHON VERSION
# ══════════════════════════════════════════════════════════

if sys.version_info < (3, 8):
    print("ERROR: Python 3.8 or higher required!")
    print(f"Your version: {sys.version}")
    sys.exit(1)


# ══════════════════════════════════════════════════════════
# IMPORTS - PHASE 1 (Foundation)
# ══════════════════════════════════════════════════════════

try:
    from config.settings import settings
    from config.constants import (
        APP_NAME,
        APP_VERSION,
        SIGNAL_BUY,
        SIGNAL_SELL,
        SIGNAL_HOLD,
        BOT_STATE_RUNNING,
        BOT_STATE_STOPPED,
        BOT_STATE_PAUSED,
    )
    from utils.helpers import (
        format_currency,
        format_percentage_raw,
        format_pnl,
        format_duration,
        get_ist_now,
    )
    from utils.indian_market import (
        is_market_open,
        is_trading_day,
        get_market_status,
        get_time_to_market_open,
        get_weekly_expiry,
        format_expiry,
        can_take_new_trades,
        should_close_all_positions,
    )
    from utils.exceptions import TradingBotError, ConfigError

    PHASE1_OK = True
except ImportError as e:
    print(f"ERROR: Failed to import Phase 1 modules: {e}")
    PHASE1_OK = False
    sys.exit(1)


# ══════════════════════════════════════════════════════════
# IMPORTS - PHASE 2 (Data Layer)
# ══════════════════════════════════════════════════════════

try:
    from data import get_market_data, get_dhan_client, get_finnhub_client

    PHASE2_OK = True
except ImportError as e:
    print(f"WARNING: Phase 2 modules not fully available: {e}")
    PHASE2_OK = False


# ══════════════════════════════════════════════════════════
# IMPORTS - PHASE 3 (Database Layer)
# ══════════════════════════════════════════════════════════

try:
    from database import get_database_status, get_trade_repo, get_snapshot_repo

    PHASE3_OK = True
except ImportError as e:
    print(f"WARNING: Phase 3 modules not fully available: {e}")
    PHASE3_OK = False


# ══════════════════════════════════════════════════════════
# IMPORTS - PHASE 4 (Strategy Layer)
# ══════════════════════════════════════════════════════════

try:
    from brains import get_coordinator

    PHASE4_OK = True
except ImportError as e:
    print(f"WARNING: Phase 4 modules not fully available: {e}")
    PHASE4_OK = False


# ══════════════════════════════════════════════════════════
# IMPORTS - PHASE 5 (Risk Management)
# ══════════════════════════════════════════════════════════

try:
    from risk import RiskManager, CircuitBreaker

    PHASE5_OK = True
except ImportError as e:
    print(f"WARNING: Phase 5 modules not fully available: {e}")
    PHASE5_OK = False


# ══════════════════════════════════════════════════════════
# IMPORTS - PHASE 6 (Paper Trading Engine)
# ══════════════════════════════════════════════════════════

try:
    from core import TradingBot, get_trading_bot

    PHASE6_OK = True
except ImportError as e:
    print(f"WARNING: Phase 6 modules not fully available: {e}")
    PHASE6_OK = False


# ══════════════════════════════════════════════════════════
# LOGGING SETUP
# ══════════════════════════════════════════════════════════


def setup_logging(debug: bool = False) -> None:
    """Configure logging for the bot."""
    log_level = logging.DEBUG if debug else logging.INFO

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if getattr(settings, "LOG_TO_FILE", False):
        try:
            import os

            log_path = getattr(settings, "LOG_FILE_PATH", "logs/bot.log")
            log_dir = os.path.dirname(log_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)

            file_handler = logging.FileHandler(log_path)
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            print(f"WARNING: Could not set up file logging: {e}")

    # Suppress noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


# ══════════════════════════════════════════════════════════
# PHASE 5 HELPER — create risk manager instance
# ══════════════════════════════════════════════════════════

_risk_manager_instance = None
_circuit_breaker_instance = None


def get_risk_manager():
    """Get or create the RiskManager singleton."""
    global _risk_manager_instance, _circuit_breaker_instance

    if _risk_manager_instance is not None:
        return _risk_manager_instance

    if not PHASE5_OK:
        return None

    if not PHASE3_OK:
        return None

    try:
        from database import get_trade_repo, get_position_repo

        trade_repo = get_trade_repo()
        position_repo = get_position_repo()

        _circuit_breaker_instance = CircuitBreaker(
            max_consecutive_losses=int(getattr(settings, "MAX_CONSECUTIVE_LOSSES", 5)),
            cooldown_seconds=int(getattr(settings, "CIRCUIT_BREAKER_COOLDOWN", 3600)),
            max_daily_loss_pct=float(getattr(settings, "MAX_DAILY_LOSS", 0.03)) * 100,
            initial_capital=float(getattr(settings, "INITIAL_CAPITAL", 10000)),
        )

        _risk_manager_instance = RiskManager(
            settings=settings,
            trade_repository=trade_repo,
            position_repository=position_repo,
            circuit_breaker=_circuit_breaker_instance,
        )

        return _risk_manager_instance

    except Exception as e:
        print(f"WARNING: Could not create RiskManager: {e}")
        return None


def get_circuit_breaker():
    """Get the CircuitBreaker instance (creates RiskManager if needed)."""
    global _circuit_breaker_instance

    if _circuit_breaker_instance is not None:
        return _circuit_breaker_instance

    get_risk_manager()
    return _circuit_breaker_instance


# ══════════════════════════════════════════════════════════
# BANNER
# ══════════════════════════════════════════════════════════


def print_banner():
    """Print the startup banner."""
    banner = f"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║    ████████╗██████╗  █████╗ ██████╗ ██╗███╗   ██╗ ██████╗    ║
║    ╚══██╔══╝██╔══██╗██╔══██╗██╔══██╗██║████╗  ██║██╔════╝    ║
║       ██║   ██████╔╝███████║██║  ██║██║██╔██╗ ██║██║  ███╗   ║
║       ██║   ██╔══██╗██╔══██║██║  ██║██║██║╚██╗██║██║   ██║   ║
║       ██║   ██║  ██║██║  ██║██████╔╝██║██║ ╚████║╚██████╔╝   ║
║       ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚═╝╚═╝  ╚═══╝ ╚═════╝    ║
║                                                              ║
║                      ██████╗  ██████╗ ████████╗              ║
║                      ██╔══██╗██╔═══██╗╚══██╔══╝              ║
║                      ██████╔╝██║   ██║   ██║                 ║
║                      ██╔══██╗██║   ██║   ██║                 ║
║                      ██████╔╝╚██████╔╝   ██║                 ║
║                      ╚═════╝  ╚═════╝    ╚═╝                 ║
║                                                              ║
║                    OPTIONS TRADING BOT                       ║
║                       Version {APP_VERSION}                           ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def print_simple_banner():
    """Print a simpler banner."""
    print("\n" + "=" * 60)
    print(f"  🤖 {APP_NAME} v{APP_VERSION}")
    print("=" * 60)


def print_trading_banner():
    """Print banner for trading mode."""
    mode = "PAPER" if getattr(settings, "PAPER_TRADING", True) else "LIVE"
    mode_emoji = "📝" if mode == "PAPER" else "💰"

    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + f"  🤖 {APP_NAME} v{APP_VERSION}".ljust(57) + "║")
    print("║" + f"  {mode_emoji} Mode: {mode} TRADING".ljust(57) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "═" * 58 + "╝")
    print()
    # ══════════════════════════════════════════════════════════


# PHASE 1 - CONFIGURATION DISPLAY
# ══════════════════════════════════════════════════════════


def print_configuration():
    """Print current configuration."""

    print("\n┌─────────────────────────────────────────────────────────┐")
    print("│                    CONFIGURATION                        │")
    print("├─────────────────────────────────────────────────────────┤")

    # Environment
    mode_emoji = "📝" if settings.PAPER_TRADING else "💰"
    mode_text = "PAPER TRADING" if settings.PAPER_TRADING else "LIVE TRADING"
    mode_color = "SAFE" if settings.PAPER_TRADING else "REAL MONEY!"

    print(f"│  Environment:     {settings.ENVIRONMENT:<38} │")
    print(f"│  Debug Mode:      {str(settings.DEBUG):<38} │")
    print(
        f"│  Trading Mode:    {mode_emoji} {mode_text} ({mode_color}){' ' * (22 - len(mode_color))} │"
    )
    print(f"│  Trading Type:    {settings.TRADING_TYPE:<38} │")

    print("├─────────────────────────────────────────────────────────┤")

    # Capital
    capital = format_currency(settings.INITIAL_CAPITAL)
    per_trade = format_currency(settings.MAX_CAPITAL_PER_TRADE)

    print(f"│  Initial Capital: {capital:<38} │")
    print(f"│  Per Trade:       {per_trade:<38} │")
    print(f"│  Max Positions:   {settings.MAX_OPEN_POSITIONS:<38} │")
    print(f"│  Max Trades/Day:  {settings.MAX_TRADES_PER_DAY:<38} │")

    print("├─────────────────────────────────────────────────────────┤")

    # Instruments
    instruments = ", ".join(settings.OPTIONS_INSTRUMENTS)
    print(f"│  Instruments:     {instruments:<38} │")
    print(f"│  NIFTY Lot:       {settings.NIFTY_LOT_SIZE:<38} │")
    print(f"│  BANKNIFTY Lot:   {settings.BANKNIFTY_LOT_SIZE:<38} │")
    print(f"│  Max Lots/Trade:  {settings.MAX_LOTS_PER_TRADE:<38} │")

    print("├─────────────────────────────────────────────────────────┤")

    # Risk
    sl = f"{settings.STOP_LOSS_PERCENTAGE}%"
    tp = f"{settings.TAKE_PROFIT_PERCENTAGE}%"
    daily_loss = f"{settings.MAX_DAILY_LOSS * 100}%"

    print(f"│  Stop Loss:       {sl:<38} │")
    print(f"│  Take Profit:     {tp:<38} │")
    print(f"│  Max Daily Loss:  {daily_loss:<38} │")
    print(f"│  Max Consec Loss: {settings.MAX_CONSECUTIVE_LOSSES:<38} │")

    print("├─────────────────────────────────────────────────────────┤")

    # Timing
    print(f"│  Market Open:     {settings.MARKET_OPEN_TIME:<38} │")
    print(f"│  Market Close:    {settings.MARKET_CLOSE_TIME:<38} │")
    print(f"│  No Trades After: {settings.NO_NEW_TRADES_AFTER:<38} │")
    print(f"│  Close All By:    {settings.CLOSE_ALL_POSITIONS_BY:<38} │")
    print(f"│  Scan Interval:   {settings.SCAN_INTERVAL} seconds{' ' * 28} │")

    print("├─────────────────────────────────────────────────────────┤")

    # Brain Weights
    tech = f"{settings.BRAIN_WEIGHT_TECHNICAL * 100:.0f}%"
    sent = f"{settings.BRAIN_WEIGHT_SENTIMENT * 100:.0f}%"
    patt = f"{settings.BRAIN_WEIGHT_PATTERN * 100:.0f}%"

    print(
        f"│  Brain Weights:   Technical: {tech}, Sentiment: {sent}, Pattern: {patt}  │"
    )

    print("├─────────────────────────────────────────────────────────┤")

    # API Status
    dhan_status = "✅ Configured" if settings.DHAN_CLIENT_ID else "❌ NOT SET"
    finnhub_status = "✅ Configured" if settings.FINNHUB_API_KEY else "❌ NOT SET"
    telegram_status = "✅ Configured" if settings.TELEGRAM_BOT_TOKEN else "❌ NOT SET"

    print(f"│  Dhan API:        {dhan_status:<38} │")
    print(f"│  Finnhub API:     {finnhub_status:<38} │")
    print(f"│  Telegram Bot:    {telegram_status:<38} │")

    print("└─────────────────────────────────────────────────────────┘")


def print_market_status():
    """Print current market status."""

    print("\n┌─────────────────────────────────────────────────────────┐")
    print("│                    MARKET STATUS                        │")
    print("├─────────────────────────────────────────────────────────┤")

    now = get_ist_now()
    current_time = now.strftime("%H:%M:%S")
    current_date = now.strftime("%A, %d %B %Y")

    print(f"│  Current Time:    {current_time} IST{' ' * 27} │")
    print(f"│  Date:            {current_date:<38} │")

    # Market status
    status = get_market_status()
    print(f"│  Status:          {status:<38} │")

    # Trading day check
    is_trading = "Yes ✅" if is_trading_day() else "No ❌"
    print(f"│  Trading Day:     {is_trading:<38} │")

    # Time to open/close
    is_open, time_msg, _ = get_time_to_market_open()
    print(f"│  Market:          {time_msg:<38} │")

    print("├─────────────────────────────────────────────────────────┤")

    # Options expiry
    weekly = get_weekly_expiry()
    weekly_str = f"{weekly.strftime('%d %b %Y')} ({format_expiry(weekly)})"
    print(f"│  Weekly Expiry:   {weekly_str:<38} │")

    print("└─────────────────────────────────────────────────────────┘")


# ══════════════════════════════════════════════════════════
# PHASE 2 - DATA CONNECTIONS & LIVE PRICES
# ══════════════════════════════════════════════════════════


def print_data_connections():
    """Print data connection status (Phase 2)."""

    if not PHASE2_OK:
        print("\n┌─────────────────────────────────────────────────────────┐")
        print("│                  DATA CONNECTIONS                       │")
        print("├─────────────────────────────────────────────────────────┤")
        print("│  ⚠️  Phase 2 modules not available                      │")
        print("└─────────────────────────────────────────────────────────┘")
        return

    print("\n┌─────────────────────────────────────────────────────────┐")
    print("│                  DATA CONNECTIONS                        │")
    print("├─────────────────────────────────────────────────────────┤")

    try:
        md = get_market_data()
        status = md.get_status()

        dhan_status = (
            "✅ Connected"
            if status["dhan_connected"]
            else "⚠️  Not Connected (using mock)"
        )
        print(f"│  Dhan API:        {dhan_status:<38} │")

        finnhub_status = (
            "✅ Configured" if status["finnhub_configured"] else "⚠️  Not Configured"
        )
        print(f"│  Finnhub API:     {finnhub_status:<38} │")

        cache = status.get("cache_stats", {})
        cache_info = f"Items: {cache.get('cached_items', 0)}, Hit Rate: {cache.get('hit_rate', 0)}%"
        print(f"│  Cache:           {cache_info:<38} │")

    except Exception as e:
        print(f"│  ❌ Error: {str(e)[:45]:<45} │")

    print("└─────────────────────────────────────────────────────────┘")


def print_live_prices():
    """Print live/mock prices for indices (Phase 2)."""

    if not PHASE2_OK:
        return

    print("\n┌─────────────────────────────────────────────────────────┐")
    print("│                    LIVE PRICES                          │")
    print("├─────────────────────────────────────────────────────────┤")

    try:
        md = get_market_data()

        for symbol in ["NIFTY", "BANKNIFTY"]:
            quote = md.get_quote(symbol)

            ltp = quote.get("ltp", 0)
            change = quote.get("change", 0)
            change_pct = quote.get("change_pct", 0)
            data_type = "LIVE" if quote.get("is_live") else "MOCK"

            if change >= 0:
                change_str = f"▲ +{change:.2f} (+{change_pct:.2f}%)"
            else:
                change_str = f"▼ {change:.2f} ({change_pct:.2f}%)"

            symbol_str = f"{symbol}:"
            price_str = f"₹{ltp:,.2f}"

            print(
                f"│  {symbol_str:<12} {price_str:>12}  {change_str:<15} [{data_type}] │"
            )

    except Exception as e:
        print(f"│  ❌ Error fetching prices: {str(e)[:30]:<30} │")

    print("└─────────────────────────────────────────────────────────┘")


def print_option_chain_summary():
    """Print option chain summary (Phase 2)."""

    if not PHASE2_OK:
        return

    print("\n┌─────────────────────────────────────────────────────────┐")
    print("│                  OPTION CHAIN (NIFTY)                   │")
    print("├─────────────────────────────────────────────────────────┤")

    try:
        md = get_market_data()
        chain = md.get_option_chain("NIFTY")

        spot = chain.get("spot_price", 0)
        atm = chain.get("atm_strike", 0)
        expiry = chain.get("expiry", "N/A")
        data_type = "LIVE" if chain.get("is_live") else "MOCK"

        print(f"│  Spot Price:      ₹{spot:,.2f}{' ' * (35 - len(f'{spot:,.2f}'))} │")
        print(f"│  ATM Strike:      {atm:<38} │")
        print(f"│  Expiry:          {expiry:<38} │")
        print(f"│  Data Source:     {data_type:<38} │")

        print("├─────────────────────────────────────────────────────────┤")

        atm_ce = None
        atm_pe = None

        for c in chain.get("calls", []):
            if c["strike"] == atm:
                atm_ce = c
                break

        for p in chain.get("puts", []):
            if p["strike"] == atm:
                atm_pe = p
                break

        if atm_ce:
            ce_info = f"₹{atm_ce['ltp']:.2f} (IV: {atm_ce.get('iv', 0):.1f}%)"
            print(f"│  ATM {atm} CE:  {ce_info:<36} │")

        if atm_pe:
            pe_info = f"₹{atm_pe['ltp']:.2f} (IV: {atm_pe.get('iv', 0):.1f}%)"
            print(f"│  ATM {atm} PE:  {pe_info:<36} │")

        if atm_ce and atm_pe:
            straddle = atm_ce["ltp"] + atm_pe["ltp"]
            print(
                f"│  ATM Straddle:    ₹{straddle:.2f}{' ' * (35 - len(f'{straddle:.2f}'))} │"
            )

    except Exception as e:
        print(f"│  ❌ Error: {str(e)[:45]:<45} │")

    print("└─────────────────────────────────────────────────────────┘")


def print_market_news():
    """Print latest market news (Phase 2)."""

    if not PHASE2_OK:
        return

    print("\n┌─────────────────────────────────────────────────────────┐")
    print("│                    MARKET NEWS                          │")
    print("├─────────────────────────────────────────────────────────┤")

    try:
        md = get_market_data()
        news = md.get_news(limit=3)

        if not news:
            print("│  No news available                                      │")
        else:
            for i, article in enumerate(news, 1):
                headline = article.get("headline", "No headline")
                source = article.get("source", "Unknown")

                max_len = 50
                if len(headline) > max_len:
                    headline = headline[: max_len - 3] + "..."

                mock = " (MOCK)" if article.get("_mock") else ""

                print(f"│  {i}. {headline:<52} │")
                print(
                    f"│     Source: {source}{mock}{' ' * (42 - len(source) - len(mock))} │"
                )

                if i < len(news):
                    print("│                                                         │")

    except Exception as e:
        print(f"│  ❌ Error: {str(e)[:45]:<45} │")

    print("└─────────────────────────────────────────────────────────┘")


# ══════════════════════════════════════════════════════════
# PHASE 3 - DATABASE STATUS
# ══════════════════════════════════════════════════════════


def print_database_status():
    """Print database status (Phase 3)."""

    if not PHASE3_OK:
        print("\n┌─────────────────────────────────────────────────────────┐")
        print("│                    DATABASE                             │")
        print("├─────────────────────────────────────────────────────────┤")
        print("│  ⚠️  Phase 3 modules not available                      │")
        print("└─────────────────────────────────────────────────────────┘")
        return

    print("\n┌─────────────────────────────────────────────────────────┐")
    print("│                    DATABASE                              │")
    print("├─────────────────────────────────────────────────────────┤")

    try:
        db_status = get_database_status()

        db_file = db_status.get("database_url", "").replace("sqlite:///", "")
        if not db_file:
            db_file = "trading_bot.db"
        file_exists = "✅ Yes" if db_status.get("file_exists") else "📝 New"
        file_size = db_status.get("file_size_kb", 0)

        print(f"│  Database:        {db_file:<38} │")
        print(f"│  File Exists:     {file_exists:<38} │")
        print(f"│  File Size:       {file_size} KB{' ' * (35 - len(str(file_size)))} │")
        print(f"│  Tables:          {db_status.get('table_count', 0):<38} │")

        print("├─────────────────────────────────────────────────────────┤")

        total_trades = db_status.get("trade_count", 0)
        open_trades = db_status.get("open_trades", 0)
        today_trades = db_status.get("today_trades", 0)
        today_pnl = db_status.get("today_pnl", 0)

        print(f"│  Total Trades:    {total_trades:<38} │")
        print(f"│  Open Trades:     {open_trades:<38} │")
        print(f"│  Today's Trades:  {today_trades:<38} │")

        if today_pnl > 0:
            pnl_str = f"₹{today_pnl:+,.2f} 📈"
        elif today_pnl < 0:
            pnl_str = f"₹{today_pnl:+,.2f} 📉"
        else:
            pnl_str = f"₹{today_pnl:,.2f} ➡️"

        print(f"│  Today's PnL:     {pnl_str:<38} │")

    except Exception as e:
        print(f"│  ❌ Error: {str(e)[:45]:<45} │")

    print("└─────────────────────────────────────────────────────────┘")


def print_trading_stats():
    """Print trading performance stats (Phase 3)."""

    if not PHASE3_OK:
        return

    print("\n┌─────────────────────────────────────────────────────────┐")
    print("│                 TRADING PERFORMANCE                      │")
    print("├─────────────────────────────────────────────────────────┤")

    try:
        trade_repo = get_trade_repo()
        stats = trade_repo.get_stats()

        total = stats.get("closed_trades", 0)

        if total == 0:
            print("│  No closed trades yet. Start trading to see stats!     │")
            print("└─────────────────────────────────────────────────────────┘")
            return

        winners = stats.get("winning_trades", 0)
        losers = stats.get("losing_trades", 0)
        win_rate = stats.get("win_rate", 0)

        total_pnl = stats.get("total_pnl", 0)
        avg_win = stats.get("avg_win", 0)
        avg_loss = stats.get("avg_loss", 0)
        profit_factor = stats.get("profit_factor", 0)

        # Win rate bar
        bar_length = 20
        filled = int(bar_length * win_rate / 100) if win_rate > 0 else 0
        win_bar = "█" * filled + "░" * (bar_length - filled)

        print(f"│  Closed Trades:   {total:<38} │")

        wl_str = f"{winners}W / {losers}L"
        print(f"│  Win/Loss:        {wl_str:<38} │")

        wr_str = f"{win_rate}% [{win_bar}]"
        print(f"│  Win Rate:        {wr_str:<38} │")

        print("├─────────────────────────────────────────────────────────┤")

        if total_pnl >= 0:
            pnl_str = f"₹{total_pnl:+,.2f} 📈"
        else:
            pnl_str = f"₹{total_pnl:+,.2f} 📉"

        print(f"│  Total PnL:       {pnl_str:<38} │")

        aw_str = f"₹{avg_win:+,.2f}"
        al_str = f"₹{avg_loss:+,.2f}"
        print(f"│  Avg Win:         {aw_str:<38} │")
        print(f"│  Avg Loss:        {al_str:<38} │")
        print(f"│  Profit Factor:   {profit_factor:<38} │")
        print(f"│  Best Symbol:     {stats.get('best_symbol', 'N/A'):<38} │")

    except Exception as e:
        print(f"│  ❌ Error: {str(e)[:45]:<45} │")

    print("└─────────────────────────────────────────────────────────┘")


# ══════════════════════════════════════════════════════════
# PHASE 4 - BRAIN ANALYSIS
# ══════════════════════════════════════════════════════════


def print_brain_analysis():
    """Print brain consensus analysis (Phase 4)."""

    if not PHASE4_OK:
        print("\n┌─────────────────────────────────────────────────────────┐")
        print("│                    BRAIN ANALYSIS                       │")
        print("├─────────────────────────────────────────────────────────┤")
        print("│  ⚠️  Phase 4 modules not available                      │")
        print("└─────────────────────────────────────────────────────────┘")
        return

    print("\n┌─────────────────────────────────────────────────────────┐")
    print("│                    BRAIN ANALYSIS                       │")
    print("├─────────────────────────────────────────────────────────┤")

    try:
        coordinator = get_coordinator()
        md = get_market_data()

        for symbol in settings.OPTIONS_INSTRUMENTS:
            result = coordinator.analyze_symbol(symbol, md)

            action = result.get("action", "HOLD")
            confidence = result.get("confidence", 0.0)
            reasoning = result.get("reasoning", "No reasoning provided")

            icon = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"

            line = f"{icon} {symbol}: {action} ({confidence:.1%})"
            print(f"│  {line:<53}│")

            short_reason = reasoning[:50] + "..." if len(reasoning) > 50 else reasoning
            print(f"│     {short_reason:<51}│")
            print("│                                                         │")

    except Exception as e:
        print(f"│  ❌ Brain Error: {str(e)[:45]:<45}│")

    print("└─────────────────────────────────────────────────────────┘")


# ══════════════════════════════════════════════════════════
# PHASE 5 - RISK MANAGEMENT STATUS
# ══════════════════════════════════════════════════════════


def print_risk_status():
    """Print risk management status (Phase 5)."""

    if not PHASE5_OK:
        print("\n┌─────────────────────────────────────────────────────────┐")
        print("│                  RISK MANAGEMENT                       │")
        print("├─────────────────────────────────────────────────────────┤")
        print("│  ⏳ Phase 5 modules not available                      │")
        print("└─────────────────────────────────────────────────────────┘")
        return

    print("\n┌─────────────────────────────────────────────────────────┐")
    print("│                  RISK MANAGEMENT                        │")
    print("├─────────────────────────────────────────────────────────┤")

    try:
        rm = get_risk_manager()
        if rm is None:
            print("│  ⚠️  Could not initialise Risk Manager                  │")
            print("└─────────────────────────────────────────────────────────┘")
            return

        summary = rm.get_risk_summary()

        # Capital section
        cap = summary.get("capital", {})
        initial = format_currency(cap.get("initial", 0))
        current = format_currency(cap.get("current", 0))
        change = cap.get("change", 0)
        change_pct = cap.get("change_pct", 0)

        if change >= 0:
            cap_change = f"+{format_currency(change)} (+{change_pct:.1f}%) 📈"
        elif change < 0:
            cap_change = f"{format_currency(change)} ({change_pct:.1f}%) 📉"
        else:
            cap_change = "No change ➡️"

        print(f"│  Initial Capital: {initial:<38} │")
        print(f"│  Current Capital: {current:<38} │")
        print(f"│  Capital Change:  {cap_change:<38} │")

        print("├─────────────────────────────────────────────────────────┤")

        # Daily metrics
        daily = summary.get("daily", {})
        daily_pnl = daily.get("pnl", 0)
        daily_trades = daily.get("trades", 0)
        max_trades = daily.get("max_trades", 20)
        trades_left = daily.get("trades_remaining", 0)
        loss_limit = daily.get("loss_limit", 0)
        loss_left = daily.get("loss_remaining", 0)

        if daily_pnl > 0:
            pnl_str = f"₹{daily_pnl:+,.2f} 📈"
        elif daily_pnl < 0:
            pnl_str = f"₹{daily_pnl:+,.2f} 📉"
        else:
            pnl_str = f"₹{daily_pnl:,.2f} ➡️"

        print(f"│  Daily P&L:       {pnl_str:<38} │")
        print(
            f"│  Trades Today:    {daily_trades} / {max_trades} ({trades_left} remaining){' ' * max(0, 20 - len(str(trades_left)))} │"
        )
        print(f"│  Loss Limit:      {format_currency(loss_limit):<38} │")
        print(f"│  Loss Remaining:  {format_currency(loss_left):<38} │")

        print("├─────────────────────────────────────────────────────────┤")

        # Positions
        pos = summary.get("positions", {})
        open_pos = pos.get("open", 0)
        max_pos = pos.get("max", 4)
        slots = pos.get("slots_remaining", 0)

        pos_bar_len = 20
        pos_filled = int(pos_bar_len * open_pos / max_pos) if max_pos > 0 else 0
        pos_bar = "█" * pos_filled + "░" * (pos_bar_len - pos_filled)

        pos_str = f"{open_pos} / {max_pos} [{pos_bar}]"
        print(f"│  Open Positions:  {pos_str:<38} │")
        print(f"│  Slots Free:      {slots:<38} │")

        print("├─────────────────────────────────────────────────────────┤")

        # Circuit Breaker
        cb_status = summary.get("circuit_breaker", {})
        cb_triggered = cb_status.get("triggered", False)
        cb_reason = cb_status.get("reason", "")
        consec_losses = cb_status.get("consecutive_losses", 0)
        max_consec = cb_status.get("max_consecutive_losses", 5)
        cooldown_rem = cb_status.get("cooldown_remaining_seconds", 0)

        if cb_triggered:
            cb_icon = "🚨"
            cb_text = "TRIGGERED"
        else:
            cb_icon = "✅"
            cb_text = "SAFE"

        print(f"│  Circuit Breaker: {cb_icon} {cb_text:<35} │")

        if cb_triggered:
            reason_short = cb_reason[:35] + "..." if len(cb_reason) > 35 else cb_reason
            print(f"│    Reason:        {reason_short:<38} │")
            cooldown_min = cooldown_rem // 60
            cooldown_sec = cooldown_rem % 60
            cd_str = f"{cooldown_min}m {cooldown_sec}s remaining"
            print(f"│    Cooldown:      {cd_str:<38} │")

        loss_bar_len = 20
        loss_filled = (
            int(loss_bar_len * consec_losses / max_consec) if max_consec > 0 else 0
        )
        loss_bar = "█" * loss_filled + "░" * (loss_bar_len - loss_filled)
        loss_str = f"{consec_losses} / {max_consec} [{loss_bar}]"
        print(f"│  Consec. Losses:  {loss_str:<38} │")

        print("├─────────────────────────────────────────────────────────┤")

        # Overall Readiness
        can_trade = summary.get("can_trade", False)
        mkt_open = summary.get("market_open", False)
        accepting = summary.get("accepting_new_trades", False)

        if can_trade:
            ready_str = "🟢 READY TO TRADE"
        elif not mkt_open:
            ready_str = "🔴 MARKET CLOSED"
        elif not accepting:
            ready_str = "🟡 PAST TRADE CUTOFF"
        elif cb_triggered:
            ready_str = "🚨 CIRCUIT BREAKER ACTIVE"
        else:
            ready_str = "🔴 NOT READY (check limits)"

        print(f"│  Status:          {ready_str:<38} │")

    except Exception as e:
        print(f"│  ❌ Error: {str(e)[:45]:<45} │")

    print("└─────────────────────────────────────────────────────────┘")


# ══════════════════════════════════════════════════════════
# PHASE 6 - BOT STATUS
# ══════════════════════════════════════════════════════════


def print_bot_status(bot=None):
    """Print trading bot status (Phase 6)."""

    if not PHASE6_OK:
        print("\n┌─────────────────────────────────────────────────────────┐")
        print("│                    TRADING BOT                          │")
        print("├─────────────────────────────────────────────────────────┤")
        print("│  ⏳ Phase 6 modules not available                       │")
        print("└─────────────────────────────────────────────────────────┘")
        return

    print("\n┌─────────────────────────────────────────────────────────┐")
    print("│                    TRADING BOT                          │")
    print("├─────────────────────────────────────────────────────────┤")

    try:
        if bot is None:
            print("│  Bot not initialised yet                                │")
            print("│  Run 'python main.py' to start trading                  │")
            print("└─────────────────────────────────────────────────────────┘")
            return

        status = bot.get_status()

        # State
        state = status.get("state", "UNKNOWN")
        mode = status.get("mode", "PAPER")

        state_emoji = {
            "RUNNING": "🟢",
            "STOPPED": "🔴",
            "PAUSED": "🟡",
            "ERROR": "❌",
        }.get(state, "❓")

        mode_emoji = "📝" if mode == "PAPER" else "💰"

        print(f"│  State:           {state_emoji} {state:<35} │")
        print(f"│  Mode:            {mode_emoji} {mode:<35} │")
        print(f"│  Uptime:          {status.get('uptime', 'N/A'):<38} │")
        print(f"│  Loop Count:      {status.get('loop_count', 0):<38} │")

        print("├─────────────────────────────────────────────────────────┤")

        # Capital
        cap = status.get("capital", {})
        print(f"│  Capital:         {format_currency(cap.get('current', 0)):<38} │")
        print(f"│  Available:       {format_currency(cap.get('available', 0)):<38} │")

        # P&L
        pnl = status.get("pnl", {})
        daily_pnl = pnl.get("daily", 0)
        total_pnl = pnl.get("total", 0)

        daily_str = format_pnl(daily_pnl)
        total_str = format_pnl(total_pnl)

        print(f"│  Daily P&L:       {daily_str:<38} │")
        print(f"│  Total P&L:       {total_str:<38} │")

        print("├─────────────────────────────────────────────────────────┤")

        # Positions & Trades
        positions = status.get("positions", {})
        trades = status.get("trades", {})

        pos_str = f"{positions.get('open', 0)} / {positions.get('max', 4)}"
        trades_str = f"{trades.get('today', 0)} / {trades.get('max', 20)}"
        win_rate = trades.get("win_rate", 0)

        print(f"│  Open Positions:  {pos_str:<38} │")
        print(f"│  Trades Today:    {trades_str:<38} │")
        print(f"│  Win Rate:        {win_rate:.1f}%{' ' * 34} │")

        print("├─────────────────────────────────────────────────────────┤")

        # Market
        market = status.get("market", {})
        market_status = market.get("status", "Unknown")
        can_trade_now = market.get("can_trade", False)

        print(f"│  Market:          {market_status:<38} │")
        print(f"│  Can Trade:       {'✅ Yes' if can_trade_now else '🔴 No':<38} │")
        print(f"│  Next Scan:       {status.get('next_scan_in', 30)}s{' ' * 35} │")

    except Exception as e:
        print(f"│  ❌ Error: {str(e)[:45]:<45} │")

    print("└─────────────────────────────────────────────────────────┘")


# ══════════════════════════════════════════════════════════
# PHASE STATUS
# ══════════════════════════════════════════════════════════


def print_phase_status():
    """Print phase completion status."""

    print("\n┌─────────────────────────────────────────────────────────┐")
    print("│              DEVELOPMENT PROGRESS                       │")
    print("├─────────────────────────────────────────────────────────┤")
    print("│                                                         │")
    print("│   ✅ Phase 1: Foundation                                │")
    print("│   ✅ Phase 2: Data Layer                                │")
    print("│   ✅ Phase 3: Database Layer                            │")
    print("│   ✅ Phase 4: Strategy Layer                            │")
    print("│   ✅ Phase 5: Risk Management                           │")
    print("│   ✅ Phase 6: Paper Trading Engine                      │")
    print("│                                                         │")
    print("│   ✅ Phase 7: Telegram Integration                      │")
    print("│      ├── telegram/__init__.py     ✅                    │")
    print("│      ├── telegram/bot.py          ✅                    │")
    print("│      ├── telegram/handlers.py     ✅                    │")
    print("│      └── telegram/alerts.py       ✅                    │")
    print("│                                                         │")
    print("│   ⏳ Phase 8: Live Trading (Final)                      │")
    print("│                                                         │")
    print("└─────────────────────────────────────────────────────────┘")
    # ══════════════════════════════════════════════════════════


# QUICK STATUS CHECK
# ══════════════════════════════════════════════════════════


def quick_status():
    """Quick status check (--status flag)."""

    print("\n" + "=" * 60)
    print("  QUICK STATUS CHECK")
    print("=" * 60)

    now = get_ist_now()
    print(f"\n  🕐 Time: {now.strftime('%H:%M:%S')} IST")
    print(f"  📅 Date: {now.strftime('%A, %d %B %Y')}")

    # Market status
    status = get_market_status()
    is_open = is_market_open()
    print(f"\n  📊 Market: {status}")
    print(f"  🏪 Open: {'✅ Yes' if is_open else '🔴 No'}")

    # Trading mode
    mode = "📝 PAPER" if settings.PAPER_TRADING else "💰 LIVE"
    print(f"  💼 Mode: {mode}")

    # Data connections (Phase 2)
    if PHASE2_OK:
        try:
            md = get_market_data()
            data_status = md.get_status()

            print(
                f"\n  🔌 Dhan: {'✅ Connected' if data_status['dhan_connected'] else '⚠️  Mock Data'}"
            )
            print(
                f"  📰 Finnhub: {'✅ Active' if data_status['finnhub_configured'] else '⚠️  Not Configured'}"
            )

            print(f"\n  💹 Prices:")
            for symbol in ["NIFTY", "BANKNIFTY"]:
                quote = md.get_quote(symbol)
                data_type = "LIVE" if quote.get("is_live") else "MOCK"
                print(f"     {symbol}: ₹{quote['ltp']:,.2f} [{data_type}]")

        except Exception as e:
            print(f"\n  ❌ Data Error: {e}")

    # Database status (Phase 3)
    if PHASE3_OK:
        try:
            db_status = get_database_status()
            trade_repo = get_trade_repo()

            total = db_status.get("trade_count", 0)
            today = db_status.get("today_trades", 0)
            today_pnl = db_status.get("today_pnl", 0)
            total_pnl = trade_repo.get_total_pnl()
            win_rate = trade_repo.get_win_rate()

            print(f"\n  🗄️  Database:")
            print(f"     Total Trades: {total}")
            print(f"     Today: {today} trades | PnL: ₹{today_pnl:+,.2f}")
            print(f"     All Time PnL: ₹{total_pnl:+,.2f}")
            if total > 0:
                print(f"     Win Rate: {win_rate}%")

        except Exception as e:
            print(f"\n  ❌ Database Error: {e}")

    # Brain status (Phase 4)
    if PHASE4_OK:
        try:
            coordinator = get_coordinator()
            md = get_market_data()
            result = coordinator.analyze_symbol("NIFTY", md)
            print(
                f"\n  🧠 Brain (NIFTY): {result['action']} ({result['confidence']:.1%})"
            )
        except Exception as e:
            print(f"\n  ❌ Brain Error: {e}")

    # Risk status (Phase 5)
    if PHASE5_OK:
        try:
            rm = get_risk_manager()
            if rm is not None:
                summary = rm.get_risk_summary()
                can_trade = summary.get("can_trade", False)
                cb = summary.get("circuit_breaker", {})
                daily = summary.get("daily", {})
                pos = summary.get("positions", {})

                print(f"\n  🛡️  Risk Management:")
                print(f"     Capital: {format_currency(summary['capital']['current'])}")
                print(f"     Daily P&L: ₹{daily.get('pnl', 0):+,.2f}")
                print(f"     Positions: {pos.get('open', 0)} / {pos.get('max', 4)}")
                print(
                    f"     Trades Today: {daily.get('trades', 0)} / {daily.get('max_trades', 20)}"
                )

                cb_status = "🚨 TRIGGERED" if cb.get("triggered") else "✅ Safe"
                print(f"     Circuit Breaker: {cb_status}")

                trade_status = "🟢 READY" if can_trade else "🔴 NOT READY"
                print(f"     Can Trade: {trade_status}")
        except Exception as e:
            print(f"\n  ❌ Risk Error: {e}")

    # Bot status (Phase 6)
    if PHASE6_OK:
        print(f"\n  🤖 Trading Bot: Ready to start")
        print(f"     Run 'python main.py' to begin trading")

    print("\n" + "=" * 60 + "\n")


# ══════════════════════════════════════════════════════════
# RUN TESTS
# ══════════════════════════════════════════════════════════


def run_tests():
    """Run module tests (--test flag)."""

    print("\n" + "=" * 60)
    print("  RUNNING MODULE TESTS")
    print("=" * 60)

    tests_passed = 0
    tests_failed = 0

    # Test 1: Config
    print("\n  1. Testing config...")
    try:
        from config.settings import settings
        from config.constants import SIGNAL_BUY, SIGNAL_SELL

        assert settings.PAPER_TRADING is not None
        print("     ✅ Config: PASSED")
        tests_passed += 1
    except Exception as e:
        print(f"     ❌ Config: FAILED - {e}")
        tests_failed += 1

    # Test 2: Utils
    print("\n  2. Testing utils...")
    try:
        from utils.helpers import get_ist_now, format_currency, get_atm_strike
        from utils.indian_market import is_market_open, get_weekly_expiry
        from utils.exceptions import TradingBotError

        now = get_ist_now()
        currency = format_currency(10000)
        atm = get_atm_strike(23456.78, 50)

        assert now is not None
        assert currency == "₹10,000.00"
        assert atm == 23450

        print("     ✅ Utils: PASSED")
        tests_passed += 1
    except Exception as e:
        print(f"     ❌ Utils: FAILED - {e}")
        tests_failed += 1

    # Test 3: Data Layer
    print("\n  3. Testing data layer...")
    try:
        from data import DhanClient, FinnhubClient, MarketData
        from data import get_market_data

        md = get_market_data()
        quote = md.get_quote("NIFTY")

        assert quote is not None
        assert "ltp" in quote

        print("     ✅ Data Layer: PASSED")
        tests_passed += 1
    except Exception as e:
        print(f"     ❌ Data Layer: FAILED - {e}")
        tests_failed += 1

    # Test 4: Option Chain
    print("\n  4. Testing option chain...")
    try:
        from data import get_market_data

        md = get_market_data()

        chain = md.get_option_chain("NIFTY")

        assert chain is not None
        assert "calls" in chain
        assert "puts" in chain
        assert len(chain["calls"]) > 0

        print("     ✅ Option Chain: PASSED")
        tests_passed += 1
    except Exception as e:
        print(f"     ❌ Option Chain: FAILED - {e}")
        tests_failed += 1

    # Test 5: News
    print("\n  5. Testing news...")
    try:
        from data import get_market_data

        md = get_market_data()

        news = md.get_news(limit=3)

        assert news is not None
        assert isinstance(news, list)

        print("     ✅ News: PASSED")
        tests_passed += 1
    except Exception as e:
        print(f"     ❌ News: FAILED - {e}")
        tests_failed += 1

    # Test 6: Database
    print("\n  6. Testing database...")
    try:
        from database import get_database_status, get_trade_repo

        db_status = get_database_status()
        assert db_status is not None, "db_status is None"

        # Check tables exist
        table_count = db_status.get("table_count", 0)
        assert table_count >= 4, f"Expected 4 tables, got {table_count}"

        # Check trade repo works
        trade_repo = get_trade_repo()
        stats = trade_repo.get_stats()
        assert stats is not None, "stats is None"
        assert "total_trades" in stats, "total_trades not in stats"

        print("     ✅ Database: PASSED")
        tests_passed += 1
    except Exception as e:
        error_msg = str(e) if str(e) else type(e).__name__
        print(f"     ❌ Database: FAILED - {error_msg}")
        tests_failed += 1

    # Test 7: Trade Operations
    print("\n  7. Testing trade operations...")
    try:
        from database.repository import DatabaseManager, TradeRepository

        # Use in-memory DB for testing
        test_db = DatabaseManager("sqlite:///:memory:")
        test_db.create_tables()
        test_repo = TradeRepository(test_db)

        # Save a trade
        trade = test_repo.save_trade(
            {
                "symbol": "NIFTY",
                "strike": 24500,
                "option_type": "CE",
                "expiry": "05MAR",
                "side": "BUY",
                "entry_price": 100.0,
                "quantity": 25,
                "lots": 1,
                "stop_loss": 70.0,
                "take_profit": 150.0,
            }
        )
        assert trade is not None
        assert trade.trade_id is not None

        # Close the trade
        closed = test_repo.close_trade(trade.trade_id, 140.0, "TP")
        assert closed.pnl == 1000.0
        assert closed.status == "CLOSED"

        test_db.close()

        print("     ✅ Trade Operations: PASSED")
        tests_passed += 1
    except Exception as e:
        print(f"     ❌ Trade Operations: FAILED - {e}")
        tests_failed += 1

    # Test 8: Brain Layer
    print("\n  8. Testing brain layer...")
    try:
        if PHASE4_OK:
            from brains import get_coordinator
            from data import get_market_data

            coordinator = get_coordinator()
            md = get_market_data()
            result = coordinator.analyze_symbol("NIFTY", md)

            assert result is not None
            assert "action" in result
            print("     ✅ Brain Layer: PASSED")
            tests_passed += 1
        else:
            print("     ⚠️  Brain Layer skipped (not available)")
    except Exception as e:
        print(f"     ❌ Brain Layer: FAILED - {e}")
        tests_failed += 1

    # Test 9: Circuit Breaker
    print("\n  9. Testing circuit breaker...")
    try:
        from risk import CircuitBreaker

        cb = CircuitBreaker(
            max_consecutive_losses=3,
            cooldown_seconds=60,
            max_daily_loss_pct=3.0,
            initial_capital=10_000.0,
        )

        assert cb.is_safe() is True
        cb.record_trade_result(-50.0)
        assert cb.consecutive_losses == 1
        cb.record_trade_result(100.0)
        assert cb.consecutive_losses == 0
        cb.force_reset()

        print("     ✅ Circuit Breaker: PASSED")
        tests_passed += 1
    except Exception as e:
        print(f"     ❌ Circuit Breaker: FAILED - {e}")
        tests_failed += 1

    # Test 10: Risk Manager
    print("\n  10. Testing risk manager...")
    try:
        from risk import RiskManager, CircuitBreaker

        class MockTradeRepo:
            def get_trades_today(self):
                return []

            def get_total_pnl(self):
                return 0.0

        class MockPosRepo:
            def get_open_positions(self):
                return []

        class MockSettings:
            INITIAL_CAPITAL = 10000.0
            MAX_CAPITAL_PER_TRADE = 2500.0
            MAX_OPEN_POSITIONS = 4
            MAX_TRADES_PER_DAY = 20
            MAX_DAILY_LOSS = 0.03
            STOP_LOSS_PERCENTAGE = 30.0
            TAKE_PROFIT_PERCENTAGE = 50.0
            TRAILING_STOP_PERCENTAGE = 20.0
            MAX_PREMIUM_PER_LOT = 250.0
            MIN_PREMIUM_PER_LOT = 20.0
            MAX_IV_THRESHOLD = 30.0
            MAX_LOTS_PER_TRADE = 1
            NIFTY_LOT_SIZE = 25
            BANKNIFTY_LOT_SIZE = 15
            MIN_CONFIDENCE_THRESHOLD = 0.60
            RISK_PER_TRADE = 0.02

        test_cb = CircuitBreaker(3, 60, 3.0, 10_000.0)
        test_rm = RiskManager(MockSettings(), MockTradeRepo(), MockPosRepo(), test_cb)

        sl = test_rm.calculate_stop_loss(100.0, "CE")
        assert sl == 70.0

        tp = test_rm.calculate_take_profit(100.0, "CE")
        assert tp == 150.0

        print("     ✅ Risk Manager: PASSED")
        tests_passed += 1
    except Exception as e:
        print(f"     ❌ Risk Manager: FAILED - {e}")
        tests_failed += 1

    # Test 11: Order Manager
    print("\n  11. Testing order manager...")
    try:
        from core.order_manager import OrderManager

        class MockSettings:
            PAPER_TRADING = True

        class MockMarketData:
            def get_option_quote(self, symbol, strike, option_type, expiry):
                return {"ltp": 100.0}

        class MockTradeRepo:
            def save_trade(self, data):
                class Trade:
                    pass

                t = Trade()
                for k, v in data.items():
                    setattr(t, k, v)
                return t

            def get_open_trades(self):
                return []

        class MockPosRepo:
            def save_position(self, data):
                pass

        om = OrderManager(
            MockSettings(), MockMarketData(), MockTradeRepo(), MockPosRepo()
        )
        assert om.mode == "PAPER"
        assert om.is_paper_mode is True

        print("     ✅ Order Manager: PASSED")
        tests_passed += 1
    except Exception as e:
        print(f"     ❌ Order Manager: FAILED - {e}")
        tests_failed += 1

    # Test 12: Paper Engine
    print("\n  12. Testing paper engine...")
    try:
        from core.paper_engine import PaperEngine

        class MockSettings:
            PAPER_TRADING = True
            INITIAL_CAPITAL = 10000.0

        class MockMarketData:
            def get_quote(self, symbol):
                return {"ltp": 24500}

            def get_option_quote(self, symbol, strike, option_type, expiry):
                return {"ltp": 100.0, "iv": 15.0}

        class MockOrderManager:
            def create_order(self, params):
                return params

            def execute_order(self, order):
                class Trade:
                    trade_id = "TEST123"
                    entry_price = 100.0
                    quantity = 25
                    instrument = "NIFTY 24500 CE"

                return Trade()

        class MockRiskManager:
            def can_trade(self, signal, capital):
                return (
                    True,
                    "OK",
                    {"trade_id": "T1", "quantity": 25, "entry_price": 100},
                )

            def check_position_exit(self, trade, price):
                return False, ""

            def update_capital(self, cap):
                pass

        class MockCircuitBreaker:
            triggered = False

            def record_trade_result(self, pnl):
                pass

            def start_new_day(self):
                pass

        class MockTradeRepo:
            def get_open_trades(self):
                return []

            def get_trades_today(self):
                return []

        class MockPosRepo:
            def update_position_price(self, tid, price):
                pass

        pe = PaperEngine(
            MockSettings(),
            MockMarketData(),
            MockOrderManager(),
            MockRiskManager(),
            MockCircuitBreaker(),
            MockTradeRepo(),
            MockPosRepo(),
            None,
        )

        assert pe.capital == 10000.0
        assert pe.available_capital == 10000.0

        print("     ✅ Paper Engine: PASSED")
        tests_passed += 1
    except Exception as e:
        print(f"     ❌ Paper Engine: FAILED - {e}")
        tests_failed += 1

    # Test 13: Trading Bot Init
    print("\n  13. Testing trading bot initialisation...")
    try:
        from core import TradingBot

        bot = TradingBot()
        assert bot.state == "STOPPED"
        assert bot.mode in ["PAPER", "LIVE"]

        status = bot.get_status()
        assert "state" in status
        assert "capital" in status

        print("     ✅ Trading Bot: PASSED")
        tests_passed += 1
    except Exception as e:
        print(f"     ❌ Trading Bot: FAILED - {e}")
        tests_failed += 1

    # Summary
    print("\n" + "-" * 60)
    total = tests_passed + tests_failed
    print(f"  Results: {tests_passed}/{total} tests passed")

    if tests_failed == 0:
        print("  ✅ All tests passed!")
    else:
        print(f"  ⚠️  {tests_failed} test(s) failed")

    print("=" * 60 + "\n")

    return tests_failed == 0


# ══════════════════════════════════════════════════════════
# PRICES ONLY VIEW
# ══════════════════════════════════════════════════════════


def show_prices_only():
    """Show only live prices (--prices flag)."""

    if not PHASE2_OK:
        print("\n  ❌ Data layer not available")
        return

    print("\n" + "=" * 60)
    print("  LIVE MARKET PRICES")
    print("=" * 60)

    now = get_ist_now()
    print(f"\n  🕐 {now.strftime('%H:%M:%S')} IST | {get_market_status()}")

    try:
        md = get_market_data()

        print("\n  ┌────────────┬──────────────┬─────────────────┬────────┐")
        print("  │ Symbol     │ LTP          │ Change          │ Type   │")
        print("  ├────────────┼──────────────┼─────────────────┼────────┤")

        for symbol in ["NIFTY", "BANKNIFTY"]:
            quote = md.get_quote(symbol)

            ltp = quote.get("ltp", 0)
            change = quote.get("change", 0)
            change_pct = quote.get("change_pct", 0)
            data_type = "LIVE" if quote.get("is_live") else "MOCK"

            if change >= 0:
                change_str = f"▲ +{change_pct:.2f}%"
            else:
                change_str = f"▼ {change_pct:.2f}%"

            print(
                f"  │ {symbol:<10} │ ₹{ltp:>10,.2f} │ {change_str:<15} │ {data_type:<6} │"
            )

        print("  └────────────┴──────────────┴─────────────────┴────────┘")

        chain = md.get_option_chain("NIFTY")
        atm = chain.get("atm_strike", 0)

        print(f"\n  📊 NIFTY ATM Strike: {atm}")

        for c in chain.get("calls", []):
            if c["strike"] == atm:
                print(f"     CE: ₹{c['ltp']:.2f} | PE: ", end="")
                break

        for p in chain.get("puts", []):
            if p["strike"] == atm:
                print(f"₹{p['ltp']:.2f}")
                break

    except Exception as e:
        print(f"\n  ❌ Error: {e}")

    print("\n" + "=" * 60 + "\n")


# ══════════════════════════════════════════════════════════
# DASHBOARD VIEW (NO TRADING)
# ══════════════════════════════════════════════════════════


def show_dashboard():
    """Show full dashboard without starting trading loop."""

    print_simple_banner()

    # Phase 1
    print_configuration()
    print_market_status()

    # Phase 2
    print_data_connections()
    print_live_prices()
    print_option_chain_summary()
    print_market_news()

    # Phase 3
    print_database_status()
    print_trading_stats()

    # Phase 4
    print_brain_analysis()

    # Phase 5
    print_risk_status()

    # Phase 6
    print_bot_status(None)

    # Progress
    print_phase_status()

    # Summary
    print("\n" + "=" * 60)
    if settings.PAPER_TRADING:
        print("  ✅ Bot ready in PAPER TRADING mode (safe)")
    else:
        print("  ⚠️  Bot ready in LIVE TRADING mode (real money!)")
    print("=" * 60)

    print("\n  Commands:")
    print("    python main.py              Start trading bot")
    print("    python main.py --dashboard  Show this dashboard")
    print("    python main.py --status     Quick status")
    print("    python main.py --test       Run tests")
    print("    python main.py --prices     Live prices only")
    print()


# ══════════════════════════════════════════════════════════
# START TRADING BOT
# ══════════════════════════════════════════════════════════


def start_trading_bot():
    """Start the trading bot main loop."""

    if not PHASE6_OK:
        print("\n❌ Phase 6 (Core Trading Engine) not available!")
        print("   Cannot start trading bot.")
        return 1

    # Setup logging
    setup_logging(debug=settings.DEBUG)

    # Print trading banner
    print_trading_banner()

    # Print pre-flight summary
    print("\n" + "─" * 60)
    print("  PRE-FLIGHT CHECK")
    print("─" * 60)

    mode = "PAPER" if settings.PAPER_TRADING else "LIVE"
    print(f"\n  Mode:            {mode}")
    print(f"  Capital:         {format_currency(settings.INITIAL_CAPITAL)}")
    print(f"  Instruments:     {', '.join(settings.OPTIONS_INSTRUMENTS)}")
    print(f"  Scan Interval:   {settings.SCAN_INTERVAL}s")
    print(f"  Market Status:   {get_market_status()}")
    print(f"  Trading Day:     {'Yes' if is_trading_day() else 'No'}")
    print(f"  Market Open:     {'Yes' if is_market_open() else 'No'}")

    # Confirm if LIVE mode
    if not settings.PAPER_TRADING:
        print("\n" + "⚠️ " * 20)
        print("  WARNING: LIVE TRADING MODE")
        print("  Real money will be used!")
        print("⚠️ " * 20)

        try:
            confirm = input("\n  Type 'YES' to confirm: ")
            if confirm.strip().upper() != "YES":
                print("\n  Aborted.")
                return 0
        except KeyboardInterrupt:
            print("\n  Aborted.")
            return 0

    print("\n" + "─" * 60)
    print("  STARTING BOT...")
    print("─" * 60 + "\n")

    try:
        # Create and start bot
        bot = TradingBot()
        bot.start()  # This blocks until stopped

        return 0

    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user. Goodbye!")
        return 0

    except Exception as e:
        print(f"\n❌ Fatal Error: {e}")
        import traceback

        traceback.print_exc()
        return 1


# ══════════════════════════════════════════════════════════
# MAIN FUNCTION
# ══════════════════════════════════════════════════════════


def main():
    """Main entry point for the trading bot."""

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Options Trading Bot for NSE",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py              Start the trading bot (main loop)
  python main.py --dashboard  Show full dashboard (no trading)
  python main.py --status     Quick status check
  python main.py --test       Run module tests
  python main.py --prices     Show live prices only
  python main.py --version    Show version
        """,
    )
    parser.add_argument(
        "--status", "-s", action="store_true", help="Quick status check"
    )
    parser.add_argument("--test", "-t", action="store_true", help="Run tests")
    parser.add_argument("--prices", "-p", action="store_true", help="Show prices only")
    parser.add_argument(
        "--dashboard",
        "-d",
        action="store_true",
        help="Show full dashboard (no trading)",
    )
    parser.add_argument("--version", "-v", action="store_true", help="Show version")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    try:
        # Version only
        if args.version:
            print(f"\n  {APP_NAME} v{APP_VERSION}")
            print("  Phase: 6 (Paper Trading Engine)")
            mode = "PAPER" if settings.PAPER_TRADING else "LIVE"
            print(f"  Mode: {mode}\n")
            return 0

        # Run tests
        if args.test:
            print_simple_banner()
            success = run_tests()
            return 0 if success else 1

        # Quick status
        if args.status:
            print_simple_banner()
            quick_status()
            return 0

        # Prices only
        if args.prices:
            print_simple_banner()
            show_prices_only()
            return 0

        # Dashboard (no trading)
        if args.dashboard:
            show_dashboard()
            return 0

        # ══════════════════════════════════════════════════
        # DEFAULT: START TRADING BOT
        # ══════════════════════════════════════════════════

        return start_trading_bot()

    except ConfigError as e:
        print(f"\n❌ Configuration Error: {e}")
        print("   Please check your .env file.")
        return 1

    except TradingBotError as e:
        print(f"\n❌ Bot Error: {e}")
        return 1

    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user. Goodbye!")
        return 0

    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")
        import traceback

        traceback.print_exc()
        return 1


# ══════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
