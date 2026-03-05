"""
Telegram Bot Package - Phase 7
===============================

Connects your phone to the trading bot via Telegram.
Monitor, control, and receive alerts from anywhere.

Uses pyTelegramBotAPI (telebot) for synchronous, thread-safe operation.

Architecture
------------
    ┌─────────────────────────────────────────────────────────┐
    │                     YOUR PHONE                          │
    │                    (Telegram App)                       │
    └────────────────────────┬────────────────────────────────┘
                             │
                             ▼
    ┌─────────────────────────────────────────────────────────┐
    │                  TELEGRAM SERVERS                       │
    └────────────────────────┬────────────────────────────────┘
                             │
                             ▼
    ┌─────────────────────────────────────────────────────────┐
    │              TelegramBotHandler                         │
    │         (Runs in separate thread)                       │
    │                                                         │
    │  ┌───────────────┐  ┌───────────────┐                  │
    │  │   Handlers    │  │ AlertManager  │                  │
    │  │ (22 commands) │  │ (auto alerts) │                  │
    │  └───────┬───────┘  └───────┬───────┘                  │
    │          │                  │                           │
    │          └────────┬─────────┘                           │
    │                   │                                     │
    │                   ▼                                     │
    │            ┌─────────────┐                              │
    │            │ TradingBot  │                              │
    │            │ (shared)    │                              │
    │            └─────────────┘                              │
    │                                                         │
    └─────────────────────────────────────────────────────────┘

Components
----------
TelegramBotHandler : class
    Main Telegram bot controller. Registers command handlers,
    starts polling in a separate thread, sends messages.

AlertManager : class
    Automatic notifications. Sends alerts when trades open/close,
    market opens/closes, circuit breaker triggers, errors occur.

Commands (22 total)
-------------------
Control:
    /start    - Start the trading bot
    /stop     - Stop the trading bot
    /pause    - Pause (monitor only, no new trades)
    /resume   - Resume trading
    /restart  - Restart the bot

Status:
    /status   - Current bot status
    /health   - System health check

Portfolio:
    /portfolio - Portfolio summary
    /positions - Open positions
    /trades    - Recent trades (accepts count)
    /pnl       - P&L summary

Analysis:
    /signals   - Latest brain signals
    /brains    - Brain performance
    /watchlist - Instruments with live prices

Settings:
    /settings  - Current settings
    /mode      - Trading mode (paper/live)
    /risk      - Risk status
    /report    - Daily/weekly reports

Emergency:
    /kill      - Emergency stop (closes all, triggers circuit breaker)
    /close     - Close specific position
    /closeall  - Close all positions

Help:
    /help      - Command list

Threading Model
---------------
Main Thread:
    Runs TradingBot._main_loop() - the trading logic.
    Calls AlertManager methods to send notifications.

Telegram Thread:
    Runs TelegramBotHandler._run_polling() - listens for commands.
    Handlers access TradingBot for data and control.

Both threads share the same TradingBot instance.
Use thread-safe send_message_async() from main thread.

Usage
-----
    from telegram_bot import TelegramBotHandler, AlertManager

    # Create handler (usually done in TradingBot.__init__)
    telegram_handler = TelegramBotHandler(
        token=settings.TELEGRAM_BOT_TOKEN,
        chat_id=settings.TELEGRAM_CHAT_ID,
        admin_ids=settings.TELEGRAM_ADMIN_IDS,
        trading_bot=trading_bot,
    )

    # Setup and start polling (in separate thread)
    telegram_handler.setup()
    telegram_handler.start_polling()

    # Create alert manager
    alert_manager = AlertManager(telegram_handler)

    # Send alerts from main thread
    alert_manager.send_trade_opened(trade)
    alert_manager.send_trade_closed(trade)

Requirements
------------
    pip install pyTelegramBotAPI

    Environment variables in .env:
    TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
    TELEGRAM_CHAT_ID=your_chat_id
    TELEGRAM_ADMIN_IDS=123456789,987654321
"""

import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.bot import TradingBot

logger = logging.getLogger(__name__)

__version__ = "7.1.0"
__phase__ = 7
__description__ = "Telegram Bot - Remote Control & Alerts (pyTelegramBotAPI)"


# ══════════════════════════════════════════════════════════
# IMPORTS
# ══════════════════════════════════════════════════════════

from telegram_bot.bot import TelegramBotHandler, TELEGRAM_AVAILABLE
from telegram_bot.alerts import AlertManager

# Handlers are imported by bot.py, not needed at package level


# ══════════════════════════════════════════════════════════
# FACTORY FUNCTIONS
# ══════════════════════════════════════════════════════════

def create_telegram_bot(
    token: str,
    chat_id: str,
    admin_ids: list,
    trading_bot: "TradingBot",
) -> Optional[TelegramBotHandler]:
    """
    Factory function to create a configured TelegramBotHandler.

    Parameters
    ----------
    token : str
        Telegram bot token from BotFather.
    chat_id : str
        Chat ID to send messages to.
    admin_ids : list
        List of admin user IDs who can control the bot.
    trading_bot : TradingBot
        Reference to the main trading bot instance.

    Returns
    -------
    TelegramBotHandler or None
        Configured handler, or None if setup fails.

    Example
    -------
        telegram_bot = create_telegram_bot(
            token="123:ABC...",
            chat_id="-100123456",
            admin_ids=[123456789],
            trading_bot=bot,
        )
        if telegram_bot:
            telegram_bot.start_polling()
    """
    if not TELEGRAM_AVAILABLE:
        logger.warning(
            "Cannot create Telegram bot: pyTelegramBotAPI not installed. "
            "Run: pip install pyTelegramBotAPI"
        )
        return None

    handler = TelegramBotHandler(
        token=token,
        chat_id=chat_id,
        admin_ids=admin_ids,
        trading_bot=trading_bot,
    )

    if handler.setup():
        return handler
    else:
        logger.error("Telegram bot setup failed")
        return None


def create_alert_manager(
    telegram_bot: Optional[TelegramBotHandler],
) -> Optional[AlertManager]:
    """
    Factory function to create an AlertManager.

    Parameters
    ----------
    telegram_bot : TelegramBotHandler or None
        The Telegram bot handler to send messages through.

    Returns
    -------
    AlertManager or None
        Ready to send automatic alerts, or None if no bot.

    Example
    -------
        alert_manager = create_alert_manager(telegram_bot)
        if alert_manager:
            alert_manager.send_trade_opened(trade)
    """
    if telegram_bot is None:
        return None
    return AlertManager(telegram_bot)


# ══════════════════════════════════════════════════════════
# VALIDATION
# ══════════════════════════════════════════════════════════

def validate_telegram_config(
    token: str,
    chat_id: str,
    admin_ids: list,
) -> tuple:
    """
    Validate Telegram configuration.

    Parameters
    ----------
    token : str
        Bot token to validate.
    chat_id : str
        Chat ID to validate.
    admin_ids : list
        Admin IDs to validate.

    Returns
    -------
    tuple
        (is_valid: bool, error_message: str or None)
    """
    if not token or token == "your_telegram_bot_token":
        return False, "TELEGRAM_BOT_TOKEN not configured"

    if not chat_id or chat_id == "your_chat_id":
        return False, "TELEGRAM_CHAT_ID not configured"

    if not admin_ids:
        return False, "TELEGRAM_ADMIN_IDS not configured"

    # Basic token format check (number:alphanumeric)
    if ":" not in token:
        return False, "Invalid TELEGRAM_BOT_TOKEN format"

    return True, None


def is_telegram_configured() -> bool:
    """
    Check if Telegram is properly configured.

    Returns
    -------
    bool
        True if Telegram is configured AND library available.
    """
    if not TELEGRAM_AVAILABLE:
        return False

    try:
        from config.settings import settings

        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
        admin_ids_raw = getattr(settings, "TELEGRAM_ADMIN_IDS", [])

        # Parse admin IDs
        if isinstance(admin_ids_raw, str):
            admin_ids = [
                x.strip() for x in admin_ids_raw.split(",") if x.strip()
            ]
        elif isinstance(admin_ids_raw, list):
            admin_ids = [x for x in admin_ids_raw if x]
        else:
            admin_ids = []

        is_valid, _ = validate_telegram_config(token, chat_id, admin_ids)
        return is_valid

    except Exception:
        return False


def is_telegram_available() -> bool:
    """
    Check if pyTelegramBotAPI library is installed.

    Returns
    -------
    bool
        True if library is available.
    """
    return TELEGRAM_AVAILABLE


# ══════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════

__all__ = [
    # Main classes
    "TelegramBotHandler",
    "AlertManager",

    # Availability flag
    "TELEGRAM_AVAILABLE",

    # Factory functions
    "create_telegram_bot",
    "create_alert_manager",

    # Utilities
    "validate_telegram_config",
    "is_telegram_configured",
    "is_telegram_available",
]


# ══════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  TELEGRAM BOT PACKAGE - Phase 7")
    print("=" * 60)

    print(f"\n  Version: {__version__}")
    print(f"  Phase: {__phase__}")
    print(f"  Description: {__description__}")

    print("\n  Library Check:")
    if TELEGRAM_AVAILABLE:
        print("    ✅ pyTelegramBotAPI is installed")
    else:
        print("    ❌ pyTelegramBotAPI NOT installed")
        print("       Run: pip install pyTelegramBotAPI")

    print("\n  Components:")
    print("    • TelegramBotHandler - Command handling & polling")
    print("    • AlertManager       - Automatic notifications")

    print("\n  Commands (22 total):")
    print("    Control:   /start /stop /pause /resume /restart")
    print("    Status:    /status /health")
    print("    Portfolio: /portfolio /positions /trades /pnl")
    print("    Analysis:  /signals /brains /watchlist")
    print("    Settings:  /settings /mode /risk /report")
    print("    Emergency: /kill /close /closeall")
    print("    Help:      /help")

    print("\n  Factory Functions:")
    print("    • create_telegram_bot()   → TelegramBotHandler")
    print("    • create_alert_manager()  → AlertManager")

    print("\n  Utilities:")
    print("    • validate_telegram_config() → Check config validity")
    print("    • is_telegram_configured()   → Quick config check")
    print("    • is_telegram_available()    → Library installed?")

    print("\n  Configuration Check:")
    try:
        if is_telegram_configured():
            print("    ✅ Telegram is configured and ready")
        elif not TELEGRAM_AVAILABLE:
            print("    ❌ pyTelegramBotAPI not installed")
            print("       Run: pip install pyTelegramBotAPI")
        else:
            print("    ⚠️  Telegram is NOT configured")
            print("       Set these in .env:")
            print("       - TELEGRAM_BOT_TOKEN")
            print("       - TELEGRAM_CHAT_ID")
            print("       - TELEGRAM_ADMIN_IDS")
    except Exception as e:
        print(f"    ❌ Error checking config: {e}")

    print("\n  Threading Model:")
    print("    Main Thread    → Trading loop")
    print("    Telegram Thread → Command polling (daemon)")
    print("    Shared         → TradingBot instance")

    print("\n" + "=" * 60 + "\n")