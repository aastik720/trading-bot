"""
Telegram Command Handlers — All 25 Commands + Button Menus
============================================================

Uses pyTelegramBotAPI (telebot) — synchronous, thread-safe.

Every command works TWO ways:
    1. Typed command:   /status
    2. Button press:    Tap [📊 Status] button

The handle_callback() function routes button presses to the
correct command handler. All handlers use handler.reply() so
they work identically for typed commands and button presses.

Handler Signature
-----------------
    def cmd_xxx(source, handler):
        source:  message object OR callback_query object
        handler: TelegramBotHandler instance (has .reply(),
                 .trading_bot, etc.)

Commands
--------
Control:    /start, /stop, /pause, /resume, /restart
Status:     /status, /health
Portfolio:  /portfolio, /positions, /trades, /pnl
Analysis:   /signals, /brains, /watchlist
Settings:   /settings, /mode, /risk, /report
Emergency:  /kill, /close, /closeall
Token:      /set_token, /check_token, /token_status
Help:       /help, /menu
"""

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Any

if TYPE_CHECKING:
    pass

from config import constants
from utils.helpers import (
    format_currency,
    format_pnl,
    format_percentage,
    format_duration,
    get_ist_now,
    safe_divide,
)
from utils.indian_market import (
    is_market_open,
    is_trading_day,
    get_market_status,
    get_weekly_expiry,
    format_expiry,
    get_time_to_market_close,
)

# ── Telegram keyboard imports (pyTelegramBotAPI) ──
try:
    from telebot import types
    BUTTONS_AVAILABLE = True
except ImportError:
    BUTTONS_AVAILABLE = False
    types = None

# ── Token management imports (NEW) ──
try:
    from config.settings import settings as app_settings
    from data.dhan_client import get_dhan_client
    TOKEN_IMPORTS_AVAILABLE = True
except ImportError:
    TOKEN_IMPORTS_AVAILABLE = False
    app_settings = None

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# KEYBOARD BUILDERS
# ══════════════════════════════════════════════════════════

def _back_button():
    """Single row: ◀️ Main Menu."""
    if not BUTTONS_AVAILABLE:
        return None
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "◀️ Main Menu", callback_data="menu_main",
        )
    )
    return markup


def _main_menu_keyboard():
    """6-category main menu grid."""
    if not BUTTONS_AVAILABLE:
        return None
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "🎛 Control", callback_data="menu_control",
        ),
        types.InlineKeyboardButton(
            "📊 Status", callback_data="menu_status",
        ),
        types.InlineKeyboardButton(
            "💼 Portfolio", callback_data="menu_portfolio",
        ),
        types.InlineKeyboardButton(
            "🧠 Analysis", callback_data="menu_analysis",
        ),
        types.InlineKeyboardButton(
            "⚙️ Settings", callback_data="menu_settings",
        ),
        types.InlineKeyboardButton(
            "🚨 Emergency", callback_data="menu_emergency",
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            "🔑 Token", callback_data="menu_token",
        ),
        types.InlineKeyboardButton(
            "❓ Help", callback_data="cmd_help",
        ),
    )
    return markup


def _control_keyboard():
    if not BUTTONS_AVAILABLE:
        return None
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "▶️ Start", callback_data="cmd_start",
        ),
        types.InlineKeyboardButton(
            "⏹ Stop", callback_data="cmd_stop",
        ),
        types.InlineKeyboardButton(
            "⏸ Pause", callback_data="cmd_pause",
        ),
        types.InlineKeyboardButton(
            "▶️ Resume", callback_data="cmd_resume",
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            "🔄 Restart", callback_data="cmd_restart",
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            "◀️ Back", callback_data="menu_main",
        ),
    )
    return markup


def _status_keyboard():
    if not BUTTONS_AVAILABLE:
        return None
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "📊 Status", callback_data="cmd_status",
        ),
        types.InlineKeyboardButton(
            "🏥 Health", callback_data="cmd_health",
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            "◀️ Back", callback_data="menu_main",
        ),
    )
    return markup


def _portfolio_keyboard():
    if not BUTTONS_AVAILABLE:
        return None
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "💼 Portfolio", callback_data="cmd_portfolio",
        ),
        types.InlineKeyboardButton(
            "📈 Positions", callback_data="cmd_positions",
        ),
        types.InlineKeyboardButton(
            "📋 Trades", callback_data="cmd_trades",
        ),
        types.InlineKeyboardButton(
            "💰 P&L", callback_data="cmd_pnl",
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            "◀️ Back", callback_data="menu_main",
        ),
    )
    return markup


def _analysis_keyboard():
    if not BUTTONS_AVAILABLE:
        return None
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "🧠 Signals", callback_data="cmd_signals",
        ),
        types.InlineKeyboardButton(
            "🧠 Brains", callback_data="cmd_brains",
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            "👁 Watchlist", callback_data="cmd_watchlist",
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            "◀️ Back", callback_data="menu_main",
        ),
    )
    return markup


def _settings_keyboard():
    if not BUTTONS_AVAILABLE:
        return None
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "⚙️ Settings", callback_data="cmd_settings",
        ),
        types.InlineKeyboardButton(
            "📊 Mode", callback_data="cmd_mode",
        ),
        types.InlineKeyboardButton(
            "🛡 Risk", callback_data="cmd_risk",
        ),
        types.InlineKeyboardButton(
            "📊 Report", callback_data="cmd_report",
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            "◀️ Back", callback_data="menu_main",
        ),
    )
    return markup


def _emergency_keyboard():
    if not BUTTONS_AVAILABLE:
        return None
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "🚨 KILL", callback_data="cmd_kill",
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            "❌ Close Position", callback_data="cmd_close",
        ),
        types.InlineKeyboardButton(
            "❌ Close ALL", callback_data="cmd_closeall",
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            "◀️ Back", callback_data="menu_main",
        ),
    )
    return markup


def _token_keyboard():
    """Token management keyboard. (NEW)"""
    if not BUTTONS_AVAILABLE:
        return None
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "🔍 Check Token", callback_data="cmd_check_token",
        ),
        types.InlineKeyboardButton(
            "📊 Token Status", callback_data="cmd_token_status",
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            "◀️ Back", callback_data="menu_main",
        ),
    )
    return markup


# ══════════════════════════════════════════════════════════
# HELPER: Parse args from message text
# ══════════════════════════════════════════════════════════

def _get_args(source):
    """
    Extract command arguments from message text.

    /trades 10  →  ["10"]
    /mode paper →  ["paper"]
    /close NIFTY 24500 CE → ["NIFTY", "24500", "CE"]

    For callback_query (button press), returns [].
    """
    try:
        if hasattr(source, "text") and source.text:
            parts = source.text.strip().split()
            return parts[1:] if len(parts) > 1 else []
    except Exception:
        pass
    return []


# ══════════════════════════════════════════════════════════
# SMALL HELPERS
# ══════════════════════════════════════════════════════════

def _escape_html(text):
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_pnl_emoji(pnl):
    if pnl > 0:
        return f"🟢 +{format_currency(pnl)}"
    elif pnl < 0:
        return f"🔴 {format_currency(pnl)}"
    return f"⚪ {format_currency(0)}"


def _format_state_emoji(state):
    return {
        "RUNNING": "🟢 RUNNING",
        "STOPPED": "🔴 STOPPED",
        "PAUSED": "🟡 PAUSED",
        "ERROR": "❌ ERROR",
    }.get(state, f"❓ {state}")


def _format_bool_emoji(value):
    return "✅" if value else "❌"


def _format_action_emoji(action):
    return {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(
        action.upper(), "❓"
    )


def _format_brain_type(brain_name):
    brain_info = {
        "technical": {
            "emoji": "📊",
            "indicators": "RSI, MACD, SMA, EMA, Bollinger, Volume",
            "description": "Technical Analysis",
        },
        "sentiment": {
            "emoji": "📰",
            "indicators": "News Headlines, Keywords, Finnhub API",
            "description": "Sentiment Analysis",
        },
        "pattern": {
            "emoji": "📈",
            "indicators": "S/R, Trend, Breakout, Candles, Volume",
            "description": "Chart Pattern Recognition",
        },
    }
    return brain_info.get(
        brain_name.lower(),
        {"emoji": "🧠", "indicators": "Various", "description": "Analysis"},
    )


def _truncate_text(text, max_length=50):
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= max_length else text[: max_length - 3] + "..."


def _format_indicator_summary(brain_name, indicators):
    if not indicators:
        return ""
    bn = brain_name.lower()
    try:
        if bn == "technical":
            parts = []
            rsi = indicators.get("rsi")
            if rsi is not None:
                tag = "OB" if rsi > 70 else ("OS" if rsi < 30 else "N")
                parts.append(f"RSI:{rsi:.0f}({tag})")
            macd_signal = indicators.get("macd_signal")
            if macd_signal:
                parts.append(f"MACD:{macd_signal}")
            trend = indicators.get("trend")
            if trend:
                parts.append(f"Trend:{trend}")
            return " | ".join(parts[:3])

        if bn == "sentiment":
            parts = []
            score = indicators.get("sentiment_score")
            if score is not None:
                parts.append(
                    f"Score:{'+' if score > 0 else ''}{score:.0f}"
                )
            pos = indicators.get("positive_count", 0)
            neg = indicators.get("negative_count", 0)
            total = indicators.get("total_articles", 0)
            if total > 0:
                parts.append(f"News:{pos}+/{neg}-/{total}t")
            finnhub = indicators.get("finnhub_sentiment")
            if finnhub is not None:
                parts.append(f"API:{finnhub:.0f}")
            return " | ".join(parts[:2])

        if bn == "pattern":
            parts = []
            trend = indicators.get("trend")
            if trend:
                parts.append(f"Trend:{trend}")
            breakout = indicators.get("breakout")
            if breakout:
                parts.append(f"Breakout:{breakout}")
            candles = indicators.get("candle_patterns_found", [])
            if candles:
                parts.append(f"Candles:{','.join(candles[:2])}")
            ts = indicators.get("total_score")
            if ts is not None:
                parts.append(f"Score:{ts:.0f}")
            return " | ".join(parts[:2])

    except Exception as e:
        logger.debug("Error formatting indicators: %s", e)
    return ""


# ══════════════════════════════════════════════════════════
# CALLBACK QUERY HANDLER — routes ALL button presses
# ══════════════════════════════════════════════════════════

def handle_callback(call, handler):
    """
    Route every inline-button press to the right handler or menu.

    callback_data format:
        menu_*   → show a sub-menu (edit current message)
        cmd_*    → execute a command handler
    """
    data = call.data or ""

    # ── Menu navigation ──
    menu_map = {
        "menu_main": (
            "🤖 <b>TRADING BOT MENU</b>\n\nSelect a category:",
            _main_menu_keyboard(),
        ),
        "menu_control": (
            "🎛 <b>CONTROL</b>\n\nManage the trading bot:",
            _control_keyboard(),
        ),
        "menu_status": (
            "📊 <b>STATUS</b>\n\nCheck bot & system status:",
            _status_keyboard(),
        ),
        "menu_portfolio": (
            "💼 <b>PORTFOLIO</b>\n\nView portfolio details:",
            _portfolio_keyboard(),
        ),
        "menu_analysis": (
            "🧠 <b>ANALYSIS</b>\n\nBrain signals & data:",
            _analysis_keyboard(),
        ),
        "menu_settings": (
            "⚙️ <b>SETTINGS</b>\n\nView configuration:",
            _settings_keyboard(),
        ),
        "menu_emergency": (
            "🚨 <b>EMERGENCY</b>\n\n⚠️ Use with caution!",
            _emergency_keyboard(),
        ),
        "menu_token": (
            "🔑 <b>TOKEN MANAGEMENT</b>\n\n"
            "Manage your Dhan API token:\n\n"
            "• To set a new token, type:\n"
            "  <code>/set_token YOUR_TOKEN_HERE</code>\n\n"
            "• Use buttons below to check status:",
            _token_keyboard(),
        ),
    }

    if data in menu_map:
        text, markup = menu_map[data]
        handler.reply(call, text, markup)
        return

    # ── Command execution ──
    cmd_map = {
        "cmd_start": cmd_start,
        "cmd_stop": cmd_stop,
        "cmd_pause": cmd_pause,
        "cmd_resume": cmd_resume,
        "cmd_restart": cmd_restart,
        "cmd_status": cmd_status,
        "cmd_health": cmd_health,
        "cmd_portfolio": cmd_portfolio,
        "cmd_positions": cmd_positions,
        "cmd_trades": cmd_trades,
        "cmd_pnl": cmd_pnl,
        "cmd_signals": cmd_signals,
        "cmd_brains": cmd_brains,
        "cmd_watchlist": cmd_watchlist,
        "cmd_settings": cmd_settings,
        "cmd_mode": cmd_mode,
        "cmd_risk": cmd_risk,
        "cmd_report": cmd_report,
        "cmd_kill": cmd_kill,
        "cmd_close": cmd_close,
        "cmd_closeall": cmd_closeall,
        "cmd_help": cmd_help,
        "cmd_set_token": cmd_set_token,
        "cmd_check_token": cmd_check_token,
        "cmd_token_status": cmd_token_status,
    }

    handler_func = cmd_map.get(data)
    if handler_func:
        handler_func(call, handler)
    else:
        handler.reply(
            call,
            f"❓ Unknown action: {data}",
            _back_button(),
        )
# ══════════════════════════════════════════════════════════
# CONTROL COMMANDS
# ══════════════════════════════════════════════════════════

def cmd_start(source, handler):
    """/start — Start the trading bot + show main menu."""
    try:
        trading_bot = handler.trading_bot
        status = trading_bot.get_status()
        current_state = status.get("state", "UNKNOWN")

        if current_state == constants.BOT_STATE_RUNNING:
            handler.reply(
                source,
                "⚠️ Bot is already running.\n\n"
                f"State: {_format_state_emoji(current_state)}\n"
                "Use the buttons below 👇",
                _main_menu_keyboard(),
            )
            return

        mode = status.get("mode", "PAPER")
        instruments = ", ".join(
            getattr(
                trading_bot._settings,
                "OPTIONS_INSTRUMENTS",
                ["NIFTY", "BANKNIFTY"],
            )
        )
        scan_interval = getattr(
            trading_bot._settings, "SCAN_INTERVAL", 30,
        )

        brain_info = status.get("brains", {})
        brain_count = brain_info.get("count", 0)
        brain_names = [
            b.get("name", "?")
            for b in brain_info.get("brains", [])
        ]

        if hasattr(trading_bot, "resume"):
            trading_bot.resume()

        handler.reply(
            source,
            f"🚀 <b>BOT STARTED</b>\n\n"
            f"Mode: {mode} TRADING\n"
            f"Instruments: {instruments}\n"
            f"Scan Interval: {scan_interval}s\n"
            f"Brains: {brain_count} ({', '.join(brain_names)})\n\n"
            f"Scanning for opportunities… 🔍\n\n"
            f"Use the buttons below to navigate 👇",
            _main_menu_keyboard(),
        )
        logger.info("Bot start command received via Telegram")

    except Exception as e:
        logger.error("Error in cmd_start: %s", e)
        handler.reply(
            source,
            f"❌ Error starting bot: {str(e)[:200]}",
            _back_button(),
        )


def cmd_stop(source, handler):
    """/stop — Stop the trading bot."""
    try:
        trading_bot = handler.trading_bot
        status = trading_bot.get_status()
        current_state = status.get("state", "UNKNOWN")

        if current_state == constants.BOT_STATE_STOPPED:
            handler.reply(
                source,
                "⚠️ Bot is already stopped.\n\n"
                "Use /start to start trading.",
                _back_button(),
            )
            return

        summary = trading_bot.get_daily_summary()
        portfolio = trading_bot.get_portfolio()

        daily_pnl = summary.get("total_pnl", 0)
        trades_count = summary.get("trades_count", 0)
        wins = summary.get("wins", 0)
        losses = summary.get("losses", 0)

        trading_bot.stop()

        handler.reply(
            source,
            f"🛑 <b>BOT STOPPED</b>\n\n"
            f"📊 <b>Final Summary:</b>\n"
            f"├─ P&L: {_format_pnl_emoji(daily_pnl)}\n"
            f"├─ Trades: {trades_count} ({wins}W / {losses}L)\n"
            f"└─ Capital: {format_currency(portfolio.get('capital', {}).get('current', 0))}\n\n"
            f"Use /start to restart.",
            _back_button(),
        )
        logger.info("Bot stop command received via Telegram")

    except Exception as e:
        logger.error("Error in cmd_stop: %s", e)
        handler.reply(
            source,
            f"❌ Error stopping bot: {str(e)[:200]}",
            _back_button(),
        )


def cmd_pause(source, handler):
    """/pause — Pause trading (monitor only)."""
    try:
        trading_bot = handler.trading_bot
        status = trading_bot.get_status()
        current_state = status.get("state", "UNKNOWN")

        if current_state == constants.BOT_STATE_PAUSED:
            handler.reply(
                source,
                "⚠️ Bot is already paused.\n\n"
                "Use /resume to continue.",
                _back_button(),
            )
            return

        if current_state != constants.BOT_STATE_RUNNING:
            handler.reply(
                source,
                f"⚠️ Cannot pause: Bot is {current_state}.\n"
                "Use /start first.",
                _back_button(),
            )
            return

        trading_bot.pause()
        positions = status.get("positions", {}).get("open", 0)

        handler.reply(
            source,
            f"⏸️ <b>BOT PAUSED</b>\n\n"
            f"Open Positions: {positions}\n\n"
            f"• No new trades will be taken\n"
            f"• Existing positions still monitored\n"
            f"• SL/TP will still trigger\n\n"
            f"Use /resume to continue.",
            _back_button(),
        )
        logger.info("Bot pause command received via Telegram")

    except Exception as e:
        logger.error("Error in cmd_pause: %s", e)
        handler.reply(
            source,
            f"❌ Error pausing: {str(e)[:200]}",
            _back_button(),
        )


def cmd_resume(source, handler):
    """/resume — Resume trading."""
    try:
        trading_bot = handler.trading_bot
        status = trading_bot.get_status()
        current_state = status.get("state", "UNKNOWN")

        if current_state == constants.BOT_STATE_RUNNING:
            handler.reply(
                source,
                "⚠️ Bot is already running.",
                _back_button(),
            )
            return

        if current_state == constants.BOT_STATE_STOPPED:
            handler.reply(
                source,
                "⚠️ Bot is stopped. Use /start.",
                _back_button(),
            )
            return

        trading_bot.resume()

        if hasattr(trading_bot, "_circuit_breaker"):
            cb_status = trading_bot._circuit_breaker.get_status()
            if cb_status.get("triggered"):
                trading_bot._circuit_breaker.force_reset()

        handler.reply(
            source,
            "▶️ <b>BOT RESUMED</b>\n\n"
            "Trading is now active.\n"
            "Scanning for opportunities… 🔍",
            _back_button(),
        )
        logger.info("Bot resume command received via Telegram")

    except Exception as e:
        logger.error("Error in cmd_resume: %s", e)
        handler.reply(
            source,
            f"❌ Error resuming: {str(e)[:200]}",
            _back_button(),
        )


def cmd_restart(source, handler):
    """/restart — Restart the trading bot."""
    try:
        trading_bot = handler.trading_bot
        handler.reply(source, "🔄 Restarting bot…")

        trading_bot.stop()
        time.sleep(1)

        if hasattr(trading_bot, "resume"):
            trading_bot.resume()

        status = trading_bot.get_status()

        handler.reply(
            source,
            f"✅ <b>BOT RESTARTED</b>\n\n"
            f"State: {_format_state_emoji(status.get('state', 'UNKNOWN'))}\n"
            f"Mode: {status.get('mode', 'PAPER')}\n\n"
            f"Scanning… 🔍",
            _back_button(),
        )
        logger.info("Bot restart command received via Telegram")

    except Exception as e:
        logger.error("Error in cmd_restart: %s", e)
        handler.reply(
            source,
            f"❌ Error restarting: {str(e)[:200]}",
            _back_button(),
        )


# ══════════════════════════════════════════════════════════
# STATUS COMMANDS
# ══════════════════════════════════════════════════════════

def cmd_status(source, handler):
    """/status — Current bot status."""
    try:
        trading_bot = handler.trading_bot
        status = trading_bot.get_status()
        portfolio = trading_bot.get_portfolio()

        state = status.get("state", "UNKNOWN")
        mode = status.get("mode", "PAPER")
        uptime = status.get("uptime", "N/A")

        capital = portfolio.get("capital", {})
        current_capital = capital.get("current", 0)
        available = capital.get("available", 0)

        pnl = portfolio.get("pnl", {})
        daily_pnl = pnl.get("daily", 0)
        daily_pnl_pct = pnl.get("daily_pct", 0)

        positions = status.get("positions", {})
        open_pos = positions.get("open", 0)
        max_pos = positions.get("max", 4)

        trades = status.get("trades", {})
        trades_today = trades.get("today", 0)
        max_trades = trades.get("max", 20)

        market = status.get("market", {})
        market_status_text = market.get("status", "Unknown")
        market_open = market.get("is_open", False)

        cb = status.get("circuit_breaker", {})
        cb_safe = not cb.get("triggered", False)

        brains = status.get("brains", {})
        brain_count = brains.get("count", 0)
        brain_names = ", ".join(
            b.get("name", "?") for b in brains.get("brains", [])
        )

        next_scan = status.get("next_scan_in", 30)

        if market_open:
            try:
                _, close_msg = get_time_to_market_close()
                market_time = f"🟢 OPEN ({close_msg})"
            except Exception:
                market_time = "🟢 OPEN"
        else:
            market_time = f"🔴 {market_status_text}"

        message = (
            f"🤖 <b>BOT STATUS</b>\n\n"
            f"<b>State:</b>\n"
            f"├─ Mode: {mode} TRADING\n"
            f"├─ State: {_format_state_emoji(state)}\n"
            f"├─ Uptime: {uptime}\n"
            f"└─ Brains: {brain_count} ({brain_names})\n\n"
            f"<b>Capital:</b>\n"
            f"├─ Total: {format_currency(current_capital)}\n"
            f"├─ Available: {format_currency(available)}\n"
            f"└─ Today P&L: {_format_pnl_emoji(daily_pnl)} "
            f"({daily_pnl_pct:+.1f}%)\n\n"
            f"<b>Trading:</b>\n"
            f"├─ Positions: {open_pos}/{max_pos}\n"
            f"└─ Trades: {trades_today}/{max_trades}\n\n"
            f"<b>System:</b>\n"
            f"├─ Market: {market_time}\n"
            f"├─ Circuit: {_format_bool_emoji(cb_safe)} "
            f"{'Safe' if cb_safe else 'TRIGGERED'}\n"
            f"└─ Next Scan: {next_scan}s"
        )

        handler.reply(source, message, _back_button())

    except Exception as e:
        logger.error("Error in cmd_status: %s", e)
        handler.reply(
            source,
            f"❌ Error getting status: {str(e)[:200]}",
            _back_button(),
        )


def cmd_health(source, handler):
    """/health — System health check."""
    try:
        trading_bot = handler.trading_bot
        status = trading_bot.get_status()

        dhan_ok = False
        try:
            if hasattr(trading_bot, "_market_data"):
                md = trading_bot._market_data.get_status()
                dhan_ok = md.get("dhan_connected", False)
        except Exception:
            pass

        finnhub_ok = False
        try:
            if hasattr(trading_bot, "_market_data"):
                md = trading_bot._market_data.get_status()
                finnhub_ok = md.get("finnhub_configured", False)
        except Exception:
            pass

        db_ok = False
        trade_count = 0
        try:
            if hasattr(trading_bot, "_trade_repo"):
                stats = trading_bot._trade_repo.get_stats()
                trade_count = stats.get("total_trades", 0)
                db_ok = True
        except Exception:
            pass

        brains_ok = False
        brain_count = 0
        brain_names = []
        try:
            if hasattr(trading_bot, "_coordinator"):
                blist = trading_bot._coordinator.list_brains()
                if blist:
                    brains_ok = True
                    brain_count = len(blist)
                    brain_names = [b.get("name", "?") for b in blist]
        except Exception:
            pass

        risk_ok = False
        try:
            if hasattr(trading_bot, "_risk_manager"):
                trading_bot._risk_manager.get_risk_summary()
                risk_ok = True
        except Exception:
            pass

        cb_safe = True
        try:
            cb = status.get("circuit_breaker", {})
            cb_safe = not cb.get("triggered", False)
        except Exception:
            pass

        memory_mb = 0.0
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            memory_mb = process.memory_info().rss / 1024 / 1024
        except ImportError:
            memory_mb = -1
        except Exception:
            pass

        uptime = status.get("uptime", "N/A")
        memory_str = (
            f"{memory_mb:.1f} MB" if memory_mb >= 0 else "N/A"
        )
        brain_str = (
            f"{brain_count} active ({', '.join(brain_names)})"
            if brains_ok
            else "Not loaded"
        )

        message = (
            f"🏥 <b>SYSTEM HEALTH</b>\n\n"
            f"<b>APIs:</b>\n"
            f"├─ Dhan API: {_format_bool_emoji(dhan_ok)} "
            f"{'Connected' if dhan_ok else 'Mock Mode'}\n"
            f"└─ Finnhub: {_format_bool_emoji(finnhub_ok)} "
            f"{'Connected' if finnhub_ok else 'Not configured'}\n\n"
            f"<b>Components:</b>\n"
            f"├─ Database: {_format_bool_emoji(db_ok)} "
            f"({trade_count} trades)\n"
            f"├─ Brains: {_format_bool_emoji(brains_ok)} {brain_str}\n"
            f"├─ Risk Mgr: {_format_bool_emoji(risk_ok)} "
            f"{'Active' if risk_ok else 'Error'}\n"
            f"└─ Circuit: {_format_bool_emoji(cb_safe)} "
            f"{'Safe' if cb_safe else 'TRIGGERED'}\n\n"
            f"<b>Resources:</b>\n"
            f"├─ Memory: {memory_str}\n"
            f"└─ Uptime: {uptime}"
        )

        handler.reply(source, message, _back_button())

    except Exception as e:
        logger.error("Error in cmd_health: %s", e)
        handler.reply(
            source,
            f"❌ Error checking health: {str(e)[:200]}",
            _back_button(),
        )


# ══════════════════════════════════════════════════════════
# PORTFOLIO COMMANDS
# ══════════════════════════════════════════════════════════

def cmd_portfolio(source, handler):
    """/portfolio — Portfolio summary."""
    try:
        trading_bot = handler.trading_bot
        portfolio = trading_bot.get_portfolio()

        capital = portfolio.get("capital", {})
        initial = capital.get("initial", 10000)
        current = capital.get("current", 0)
        available = capital.get("available", 0)
        invested = capital.get("invested", 0)

        pnl = portfolio.get("pnl", {})
        total_pnl = pnl.get("total", 0)
        total_pct = pnl.get("total_pct", 0)
        daily_pnl = pnl.get("daily", 0)
        daily_pct = pnl.get("daily_pct", 0)

        trades = portfolio.get("trades", {})
        wins = trades.get("wins", 0)
        losses = trades.get("losses", 0)
        win_rate = trades.get("win_rate", 0)

        avg_win = avg_loss = 0
        try:
            if hasattr(trading_bot, "_trade_repo"):
                stats = trading_bot._trade_repo.get_stats()
                avg_win = stats.get("avg_win", 0)
                avg_loss = stats.get("avg_loss", 0)
        except Exception:
            pass

        message = (
            f"💼 <b>PORTFOLIO</b>\n\n"
            f"<b>Capital:</b>\n"
            f"├─ Initial: {format_currency(initial)}\n"
            f"├─ Current: {format_currency(current)}\n"
            f"├─ Invested: {format_currency(invested)}\n"
            f"└─ Available: {format_currency(available)}\n\n"
            f"<b>P&L:</b>\n"
            f"├─ Total: {_format_pnl_emoji(total_pnl)} "
            f"({total_pct:+.1f}%)\n"
            f"└─ Today: {_format_pnl_emoji(daily_pnl)} "
            f"({daily_pct:+.1f}%)\n\n"
            f"<b>Performance:</b>\n"
            f"├─ Win Rate: {win_rate:.1f}% ({wins}W / {losses}L)\n"
            f"├─ Avg Win: {format_currency(avg_win)}\n"
            f"└─ Avg Loss: {format_currency(avg_loss)}"
        )

        handler.reply(source, message, _back_button())

    except Exception as e:
        logger.error("Error in cmd_portfolio: %s", e)
        handler.reply(
            source, f"❌ Error: {str(e)[:200]}", _back_button(),
        )


def cmd_positions(source, handler):
    """/positions — Open positions."""
    try:
        trading_bot = handler.trading_bot
        portfolio = trading_bot.get_portfolio()
        pos_data = portfolio.get("positions", {})
        open_positions = pos_data.get("open", [])
        open_count = pos_data.get("open_count", len(open_positions))

        max_pos = 4
        try:
            max_pos = getattr(
                trading_bot._settings, "MAX_OPEN_POSITIONS", 4,
            )
        except Exception:
            pass

        if not open_positions:
            handler.reply(
                source,
                f"📈 <b>OPEN POSITIONS</b> (0/{max_pos})\n\n"
                f"No open positions.\n\n"
                f"Use /status to see bot state.",
                _back_button(),
            )
            return

        message = (
            f"📈 <b>OPEN POSITIONS</b> "
            f"({open_count}/{max_pos})\n\n"
        )

        for i, pos in enumerate(open_positions, 1):
            instrument = pos.get("instrument", "Unknown")
            entry = pos.get("entry_price", 0)
            current = pos.get("current_price", entry)
            quantity = pos.get("quantity", 0)
            pnl_val = pos.get("pnl", 0)
            pnl_pct = pos.get("pnl_pct", 0)
            sl = pos.get("stop_loss", 0)
            tp = pos.get("take_profit", 0)

            pnl_emoji = "🟢" if pnl_val >= 0 else "🔴"

            message += (
                f"<b>{i}. {instrument}</b>\n"
                f"├─ Entry: ₹{entry:.2f} | Now: ₹{current:.2f}\n"
                f"├─ {pnl_emoji} P&L: {pnl_pct:+.1f}% "
                f"({format_currency(pnl_val)})\n"
                f"├─ Qty: {quantity}\n"
                f"└─ SL: ₹{sl:.2f} | TP: ₹{tp:.2f}\n\n"
            )

        handler.reply(source, message, _back_button())

    except Exception as e:
        logger.error("Error in cmd_positions: %s", e)
        handler.reply(
            source, f"❌ Error: {str(e)[:200]}", _back_button(),
        )


def cmd_trades(source, handler):
    """/trades [N] — Recent trades (default 5)."""
    try:
        trading_bot = handler.trading_bot
        args = _get_args(source)
        count = 5
        if args and args[0].isdigit():
            count = min(int(args[0]), 20)

        trades = []
        try:
            if hasattr(trading_bot, "_trade_repo"):
                all_trades = trading_bot._trade_repo.get_trade_history(
                    limit=count,
                )
                trades = list(all_trades) if all_trades else []
        except Exception as e:
            logger.error("Error fetching trades: %s", e)

        if not trades:
            handler.reply(
                source,
                "📋 <b>RECENT TRADES</b>\n\nNo trades found.\n\n"
                "Bot will trade when signals are generated.",
                _back_button(),
            )
            return

        message = f"📋 <b>RECENT TRADES</b> (last {len(trades)})\n\n"

        for i, trade in enumerate(trades, 1):
            instrument = getattr(trade, "instrument", "Unknown")
            entry_price = float(getattr(trade, "entry_price", 0))
            exit_price = float(
                getattr(trade, "exit_price", 0) or 0
            )
            pnl_val = float(getattr(trade, "pnl", 0) or 0)
            pnl_pct = float(
                getattr(trade, "pnl_percentage", 0) or 0
            )
            exit_reason = getattr(trade, "exit_reason", "?")
            trade_status = getattr(trade, "status", "OPEN")

            if trade_status == "OPEN":
                status_emoji = "🔄"
                status_text = "OPEN"
            elif pnl_val >= 0:
                status_emoji = "✅"
                status_text = exit_reason
            else:
                status_emoji = "❌"
                status_text = exit_reason

            duration_str = "N/A"
            try:
                entry_time = getattr(trade, "entry_time", None)
                exit_time = getattr(trade, "exit_time", None)
                if entry_time and exit_time:
                    duration = exit_time - entry_time
                    duration_str = format_duration(
                        duration.total_seconds()
                    )
            except Exception:
                pass

            message += (
                f"<b>{i}. {instrument}</b> "
                f"{status_emoji} {status_text}\n"
            )

            if trade_status == "OPEN":
                message += f"├─ Entry: ₹{entry_price:.2f}\n\n"
            else:
                message += (
                    f"├─ ₹{entry_price:.2f} → ₹{exit_price:.2f}\n"
                    f"├─ P&L: {_format_pnl_emoji(pnl_val)} "
                    f"({pnl_pct:+.1f}%)\n"
                    f"└─ Duration: {duration_str}\n\n"
                )

        handler.reply(source, message, _back_button())

    except Exception as e:
        logger.error("Error in cmd_trades: %s", e)
        handler.reply(
            source, f"❌ Error: {str(e)[:200]}", _back_button(),
        )


def cmd_pnl(source, handler):
    """/pnl — P&L summary."""
    try:
        trading_bot = handler.trading_bot
        portfolio = trading_bot.get_portfolio()
        summary = trading_bot.get_daily_summary()

        pnl = portfolio.get("pnl", {})
        daily_pnl = pnl.get("daily", 0)
        daily_pct = pnl.get("daily_pct", 0)
        total_pnl = pnl.get("total", 0)
        total_pct = pnl.get("total_pct", 0)

        trades = portfolio.get("trades", {})
        win_rate = trades.get("win_rate", 0)

        avg_win = avg_loss = 0
        try:
            if hasattr(trading_bot, "_trade_repo"):
                stats = trading_bot._trade_repo.get_stats()
                avg_win = stats.get("avg_win", 0)
                avg_loss = stats.get("avg_loss", 0)
        except Exception:
            pass

        best_trade = summary.get("best_trade", 0)
        worst_trade = summary.get("worst_trade", 0)

        message = (
            f"💰 <b>P&L SUMMARY</b>\n\n"
            f"<b>Performance:</b>\n"
            f"├─ Today: {_format_pnl_emoji(daily_pnl)} "
            f"({daily_pct:+.1f}%)\n"
            f"├─ Total: {_format_pnl_emoji(total_pnl)} "
            f"({total_pct:+.1f}%)\n"
            f"└─ Win Rate: {win_rate:.1f}%\n\n"
            f"<b>Averages:</b>\n"
            f"├─ Avg Win: {format_currency(avg_win)}\n"
            f"└─ Avg Loss: {format_currency(avg_loss)}\n\n"
            f"<b>Today's Extremes:</b>\n"
            f"├─ Best Trade: {format_currency(best_trade)}\n"
            f"└─ Worst Trade: {format_currency(worst_trade)}"
        )

        handler.reply(source, message, _back_button())

    except Exception as e:
        logger.error("Error in cmd_pnl: %s", e)
        handler.reply(
            source, f"❌ Error: {str(e)[:200]}", _back_button(),
        )
# ══════════════════════════════════════════════════════════
# ANALYSIS COMMANDS
# ══════════════════════════════════════════════════════════

def cmd_signals(source, handler):
    """/signals — Latest brain signals from all 3 brains."""
    try:
        trading_bot = handler.trading_bot
        message = "🧠 <b>LATEST SIGNALS</b>\n\n"

        instruments = getattr(
            trading_bot._settings,
            "OPTIONS_INSTRUMENTS",
            ["NIFTY", "BANKNIFTY"],
        )

        for symbol in instruments:
            try:
                if hasattr(trading_bot, "_coordinator") and hasattr(
                    trading_bot, "_market_data"
                ):
                    result = trading_bot._coordinator.analyze_symbol(
                        symbol, trading_bot._market_data,
                    )

                    action = result.get("action", "HOLD")
                    confidence = result.get("confidence", 0)
                    reasoning = result.get("reasoning", "No data")
                    brain_count = result.get("brain_count", 0)
                    action_emoji = _format_action_emoji(action)

                    message += f"<b>━━━ {symbol} ━━━</b>\n\n"
                    message += (
                        f"<b>📊 CONSENSUS:</b>\n"
                        f"├─ Signal: {action_emoji} <b>{action}</b> "
                        f"({confidence:.0%})\n"
                        f"├─ Brains: {brain_count} voted\n"
                        f"└─ Reason: "
                        f"{_escape_html(_truncate_text(reasoning, 60))}"
                        f"\n\n"
                    )

                    brain_signals = result.get("brain_signals", [])
                    if brain_signals:
                        message += "<b>🔬 INDIVIDUAL BRAINS:</b>\n"
                        for sig in brain_signals:
                            bname = sig.get("brain", "unknown")
                            baction = sig.get("action", "HOLD")
                            bconf = sig.get("confidence", 0)
                            breason = sig.get("reasoning", "")
                            binfo = _format_brain_type(bname)
                            ind_summary = _format_indicator_summary(
                                bname, sig.get("indicators", {}),
                            )
                            message += (
                                f"\n{binfo['emoji']} "
                                f"<b>{bname.title()}</b> "
                                f"({bconf:.0%}):\n"
                                f"├─ Signal: "
                                f"{_format_action_emoji(baction)} "
                                f"{baction}\n"
                            )
                            if ind_summary:
                                message += (
                                    f"├─ Key: {ind_summary}\n"
                                )
                            if breason:
                                message += (
                                    f"└─ {_escape_html(_truncate_text(breason, 50))}\n"
                                )
                            else:
                                message += (
                                    "└─ No additional reasoning\n"
                                )

                    option_rec = result.get(
                        "option_recommendation", {},
                    )
                    if option_rec and action != "HOLD":
                        opt_type = option_rec.get("type", "")
                        strike = option_rec.get(
                            "strike_preference", "",
                        )
                        expiry = option_rec.get("expiry", "WEEKLY")
                        message += (
                            f"\n<b>💡 RECOMMENDATION:</b>\n"
                            f"└─ {symbol} {strike} {opt_type} "
                            f"({expiry})\n"
                        )

                    message += "\n"
                else:
                    message += (
                        f"<b>{symbol}:</b> ⚠️ Brain not available\n\n"
                    )

            except Exception as e:
                logger.error("Error analyzing %s: %s", symbol, e)
                message += (
                    f"<b>{symbol}:</b> ❌ Error: "
                    f"{_escape_html(str(e)[:50])}\n\n"
                )

        message += (
            "<b>Legend:</b> 🟢 BUY | 🔴 SELL | ⚪ HOLD\n"
            "📊 Technical | 📰 Sentiment | 📈 Pattern"
        )

        handler.reply(source, message, _back_button())

    except Exception as e:
        logger.error("Error in cmd_signals: %s", e)
        handler.reply(
            source, f"❌ Error: {str(e)[:200]}", _back_button(),
        )


def cmd_brains(source, handler):
    """/brains — Brain performance and status."""
    try:
        trading_bot = handler.trading_bot
        message = "🧠 <b>BRAIN PERFORMANCE</b>\n\n"

        brains = []
        brain_performance = {}
        coordinator_stats = {}

        try:
            if hasattr(trading_bot, "_coordinator"):
                brains = trading_bot._coordinator.list_brains()
                brain_performance = (
                    trading_bot._coordinator.get_brain_performance()
                )
                coordinator_stats = (
                    trading_bot._coordinator.get_stats()
                )
        except Exception as e:
            logger.error("Error getting brain info: %s", e)

        if not brains:
            message += (
                "⚠️ No brains configured.\n\n"
                "Expected brains:\n"
                "• Technical (40%)\n"
                "• Sentiment (35%)\n"
                "• Pattern (25%)"
            )
        else:
            total_weight = coordinator_stats.get("total_weight", 0)
            w_ok = (
                "✅" if abs(total_weight - 1.0) < 0.01 else "⚠️"
            )
            message += (
                f"<b>Total Weight:</b> {w_ok} "
                f"{total_weight:.0%}\n\n"
            )

            for brain in brains:
                name = brain.get("name", "unknown")
                weight = brain.get("weight", 0)
                brain_status = brain.get("status", "unknown")
                stats = brain.get("stats", {})

                binfo = _format_brain_type(name)
                status_emoji = (
                    "✅" if brain_status == "active" else "❌"
                )

                perf = brain_performance.get(name, {})
                analysis_count = perf.get(
                    "analysis_count",
                    stats.get("analysis_count", 0),
                )
                last_analysis = perf.get(
                    "last_analysis",
                    stats.get("last_analysis"),
                )

                last_str = "Never"
                if last_analysis:
                    try:
                        if isinstance(last_analysis, datetime):
                            diff = get_ist_now() - last_analysis
                            secs = diff.total_seconds()
                            if secs < 60:
                                last_str = "Just now"
                            elif secs < 3600:
                                last_str = f"{int(secs / 60)}m ago"
                            else:
                                last_str = (
                                    last_analysis.strftime("%H:%M")
                                )
                        else:
                            last_str = str(last_analysis)[:10]
                    except Exception:
                        last_str = "Unknown"

                message += (
                    f"{binfo['emoji']} <b>{name.upper()}</b>\n"
                    f"├─ Weight: {weight:.0%}\n"
                    f"├─ Status: {status_emoji} "
                    f"{brain_status.title()}\n"
                    f"├─ Indicators: {binfo['indicators']}\n"
                    f"├─ Analyses: {analysis_count}\n"
                    f"└─ Last Run: {last_str}\n\n"
                )

        total_analyses = coordinator_stats.get("analysis_count", 0)

        signals_today = 0
        try:
            if hasattr(trading_bot, "_signal_repo"):
                sigs = trading_bot._signal_repo.get_signals_today()
                signals_today = len(sigs) if sigs else 0
        except Exception:
            pass

        message += (
            f"<b>━━━ COORDINATOR ━━━</b>\n"
            f"├─ Total Analyses: {total_analyses}\n"
            f"├─ Active Brains: {len(brains)}\n"
            f"└─ Signals Today: {signals_today}"
        )

        handler.reply(source, message, _back_button())

    except Exception as e:
        logger.error("Error in cmd_brains: %s", e)
        handler.reply(
            source, f"❌ Error: {str(e)[:200]}", _back_button(),
        )


def cmd_watchlist(source, handler):
    """/watchlist — Instruments with live prices."""
    try:
        trading_bot = handler.trading_bot
        message = "👁️ <b>WATCHLIST</b>\n\n"

        instruments = getattr(
            trading_bot._settings,
            "OPTIONS_INSTRUMENTS",
            ["NIFTY", "BANKNIFTY"],
        )

        for i, symbol in enumerate(instruments, 1):
            try:
                if hasattr(trading_bot, "_market_data"):
                    quote = trading_bot._market_data.get_quote(
                        symbol
                    )
                    ltp = quote.get("ltp", 0)
                    change_pct = quote.get("change_pct", 0)
                    is_live = quote.get("is_live", False)

                    trend_emoji = "📈" if change_pct >= 0 else "📉"
                    data_type = "LIVE" if is_live else "MOCK"

                    message += (
                        f"{i}. <b>{symbol}</b>\n"
                        f"   ₹{ltp:,.2f}  {change_pct:+.2f}%  "
                        f"{trend_emoji}  [{data_type}]\n\n"
                    )
                else:
                    message += (
                        f"{i}. <b>{symbol}</b>: "
                        f"Data unavailable\n\n"
                    )

            except Exception as e:
                logger.error(
                    "Error getting quote for %s: %s", symbol, e,
                )
                message += (
                    f"{i}. <b>{symbol}</b>: ❌ Error\n\n"
                )

        try:
            weekly = get_weekly_expiry()
            expiry_str = format_expiry(weekly)
            message += (
                f"📅 Weekly Expiry: "
                f"{weekly.strftime('%d %b')} ({expiry_str})"
            )
        except Exception:
            pass

        handler.reply(source, message, _back_button())

    except Exception as e:
        logger.error("Error in cmd_watchlist: %s", e)
        handler.reply(
            source, f"❌ Error: {str(e)[:200]}", _back_button(),
        )


# ══════════════════════════════════════════════════════════
# SETTINGS COMMANDS
# ══════════════════════════════════════════════════════════

def cmd_settings(source, handler):
    """/settings — Current settings including brain weights."""
    try:
        trading_bot = handler.trading_bot
        s = trading_bot._settings

        mode = (
            "PAPER"
            if getattr(s, "PAPER_TRADING", True)
            else "LIVE"
        )
        capital = getattr(s, "INITIAL_CAPITAL", 10000)
        per_trade = getattr(s, "MAX_CAPITAL_PER_TRADE", 2500)
        max_pos = getattr(s, "MAX_OPEN_POSITIONS", 4)
        max_trades = getattr(s, "MAX_TRADES_PER_DAY", 20)
        sl_pct = getattr(s, "STOP_LOSS_PERCENTAGE", 30)
        tp_pct = getattr(s, "TAKE_PROFIT_PERCENTAGE", 50)
        instruments = getattr(
            s, "OPTIONS_INSTRUMENTS", ["NIFTY", "BANKNIFTY"],
        )
        scan_interval = getattr(s, "SCAN_INTERVAL", 30)
        no_trades_after = getattr(
            s, "NO_NEW_TRADES_AFTER", "14:30",
        )
        close_by = getattr(
            s, "CLOSE_ALL_POSITIONS_BY", "15:15",
        )

        tech_w = getattr(s, "BRAIN_WEIGHT_TECHNICAL", 0.40)
        sent_w = getattr(s, "BRAIN_WEIGHT_SENTIMENT", 0.35)
        pat_w = getattr(s, "BRAIN_WEIGHT_PATTERN", 0.25)
        min_conf = getattr(
            s, "MIN_CONFIDENCE_THRESHOLD", 0.60,
        )

        message = (
            f"⚙️ <b>SETTINGS</b>\n\n"
            f"<b>Trading:</b>\n"
            f"├─ Mode: {mode}\n"
            f"├─ Capital: {format_currency(capital)}\n"
            f"├─ Per Trade: {format_currency(per_trade)}\n"
            f"├─ Max Positions: {max_pos}\n"
            f"└─ Max Trades/Day: {max_trades}\n\n"
            f"<b>Risk:</b>\n"
            f"├─ Stop Loss: {sl_pct}%\n"
            f"└─ Take Profit: {tp_pct}%\n\n"
            f"<b>Brains:</b>\n"
            f"├─ 📊 Technical: {tech_w:.0%}\n"
            f"├─ 📰 Sentiment: {sent_w:.0%}\n"
            f"├─ 📈 Pattern: {pat_w:.0%}\n"
            f"└─ Min Confidence: {min_conf:.0%}\n\n"
            f"<b>Instruments:</b>\n"
            f"└─ {', '.join(instruments)}\n\n"
            f"<b>Timing:</b>\n"
            f"├─ Scan Interval: {scan_interval}s\n"
            f"├─ No Trades After: {no_trades_after}\n"
            f"└─ Close All By: {close_by}"
        )

        handler.reply(source, message, _back_button())

    except Exception as e:
        logger.error("Error in cmd_settings: %s", e)
        handler.reply(
            source, f"❌ Error: {str(e)[:200]}", _back_button(),
        )


def cmd_mode(source, handler):
    """/mode [paper|live] — Show or change trading mode."""
    try:
        trading_bot = handler.trading_bot
        args = _get_args(source)
        current_mode = (
            "PAPER"
            if getattr(trading_bot._settings, "PAPER_TRADING", True)
            else "LIVE"
        )

        if not args:
            mode_emoji = "📝" if current_mode == "PAPER" else "💰"
            handler.reply(
                source,
                f"📊 <b>TRADING MODE</b>\n\n"
                f"Current: {mode_emoji} {current_mode}\n\n"
                f"To change:\n"
                f"/mode paper — Paper trading\n"
                f"/mode live — Live trading (⚠️)",
                _back_button(),
            )
            return

        new_mode = args[0].lower()

        if new_mode == "paper":
            handler.reply(
                source,
                "📝 <b>PAPER MODE</b>\n\n"
                "Safe for testing. No real money.\n\n"
                "⚠️ Set PAPER_TRADING=True in .env and restart.",
                _back_button(),
            )
        elif new_mode == "live":
            handler.reply(
                source,
                "⚠️ <b>WARNING: LIVE TRADING</b>\n\n"
                "Uses REAL MONEY! You can lose capital.\n\n"
                "1. Set PAPER_TRADING=False in .env\n"
                "2. Restart the bot\n\n"
                "Proceed with caution! 💰",
                _back_button(),
            )
        else:
            handler.reply(
                source,
                "❌ Invalid mode. Use:\n"
                "/mode paper\n/mode live",
                _back_button(),
            )

    except Exception as e:
        logger.error("Error in cmd_mode: %s", e)
        handler.reply(
            source, f"❌ Error: {str(e)[:200]}", _back_button(),
        )


def cmd_risk(source, handler):
    """/risk — Risk status."""
    try:
        trading_bot = handler.trading_bot
        risk_summary = {}
        cb_status = {}

        if hasattr(trading_bot, "_risk_manager"):
            risk_summary = (
                trading_bot._risk_manager.get_risk_summary()
            )
        if hasattr(trading_bot, "_circuit_breaker"):
            cb_status = (
                trading_bot._circuit_breaker.get_status()
            )

        daily = risk_summary.get("daily", {})
        daily_pnl = daily.get("pnl", 0)
        loss_limit = daily.get("loss_limit", 300)
        trades_today = daily.get("trades", 0)
        max_trades = daily.get("max_trades", 20)

        positions = risk_summary.get("positions", {})
        open_pos = positions.get("open", 0)
        max_pos = positions.get("max", 4)

        capital = risk_summary.get("capital", {})
        current = capital.get("current", 10000)
        available = capital.get("available", 10000)
        cap_used = (
            ((current - available) / current * 100)
            if current > 0
            else 0
        )

        cb_triggered = cb_status.get("triggered", False)
        consec_losses = cb_status.get("consecutive_losses", 0)
        max_consec = cb_status.get("max_consecutive_losses", 5)

        risk_params = risk_summary.get("risk_params", {})
        sl_pct = risk_params.get("stop_loss_pct", 30)
        tp_pct = risk_params.get("take_profit_pct", 50)

        message = (
            f"🛡️ <b>RISK STATUS</b>\n\n"
            f"<b>Limits:</b>\n"
            f"├─ Daily P&L: {_format_pnl_emoji(daily_pnl)} "
            f"/ -{format_currency(loss_limit)} limit\n"
            f"├─ Daily Trades: {trades_today} / {max_trades}\n"
            f"├─ Positions: {open_pos} / {max_pos}\n"
            f"└─ Capital Used: {cap_used:.1f}%\n\n"
            f"<b>Circuit Breaker:</b>\n"
            f"├─ Status: "
            f"{_format_bool_emoji(not cb_triggered)} "
            f"{'Safe' if not cb_triggered else 'TRIGGERED'}\n"
            f"└─ Consecutive Losses: "
            f"{consec_losses}/{max_consec}\n\n"
            f"<b>Exit Rules:</b>\n"
            f"├─ Stop Loss: {sl_pct}% of premium\n"
            f"└─ Take Profit: {tp_pct}% of premium"
        )

        handler.reply(source, message, _back_button())

    except Exception as e:
        logger.error("Error in cmd_risk: %s", e)
        handler.reply(
            source, f"❌ Error: {str(e)[:200]}", _back_button(),
        )


def cmd_report(source, handler):
    """/report [daily|weekly] — Trading reports."""
    try:
        trading_bot = handler.trading_bot
        args = _get_args(source)
        report_type = args[0].lower() if args else "daily"

        if report_type == "daily":
            summary = trading_bot.get_daily_summary()

            date_str = summary.get(
                "date", get_ist_now().strftime("%Y-%m-%d"),
            )
            pnl = summary.get("total_pnl", 0)
            pnl_pct = summary.get("total_pnl_pct", 0)
            total_trades = summary.get("trades_count", 0)
            wins = summary.get("wins", 0)
            losses = summary.get("losses", 0)
            win_rate = summary.get("win_rate", 0)
            best = summary.get("best_trade", 0)
            worst = summary.get("worst_trade", 0)
            starting = summary.get("starting_capital", 10000)
            ending = summary.get("ending_capital", 10000)
            cb_triggered = summary.get(
                "circuit_breaker_triggered", False,
            )

            brain_analyses = 0
            try:
                if hasattr(trading_bot, "_coordinator"):
                    stats = trading_bot._coordinator.get_stats()
                    brain_analyses = stats.get(
                        "analysis_count", 0,
                    )
            except Exception:
                pass

            message = (
                f"📊 <b>DAILY REPORT</b> — {date_str}\n\n"
                f"<b>Performance:</b>\n"
                f"├─ P&L: {_format_pnl_emoji(pnl)} "
                f"({pnl_pct:+.1f}%)\n"
                f"├─ Trades: {total_trades} "
                f"({wins}W / {losses}L)\n"
                f"└─ Win Rate: {win_rate:.1f}%\n\n"
                f"<b>Extremes:</b>\n"
                f"├─ Best Trade: {format_currency(best)}\n"
                f"└─ Worst Trade: {format_currency(worst)}\n\n"
                f"<b>Capital:</b>\n"
                f"└─ {format_currency(starting)} → "
                f"{format_currency(ending)}\n\n"
                f"<b>System:</b>\n"
                f"├─ Brain Analyses: {brain_analyses}\n"
                f"└─ Circuit: "
                f"{'🚨 Triggered' if cb_triggered else '✅ OK'}"
            )

        elif report_type == "weekly":
            message = (
                "📊 <b>WEEKLY REPORT</b>\n\n"
                "⚠️ Coming soon.\n\n"
                "Use /report daily for today."
            )
        else:
            message = (
                "❌ Invalid. Use:\n"
                "/report daily\n/report weekly"
            )

        handler.reply(source, message, _back_button())

    except Exception as e:
        logger.error("Error in cmd_report: %s", e)
        handler.reply(
            source, f"❌ Error: {str(e)[:200]}", _back_button(),
        )
# ══════════════════════════════════════════════════════════
# EMERGENCY COMMANDS
# ══════════════════════════════════════════════════════════

def cmd_kill(source, handler):
    """/kill — Emergency stop."""
    try:
        trading_bot = handler.trading_bot
        handler.reply(
            source,
            "🚨 <b>EMERGENCY SHUTDOWN</b>\n\n"
            "Closing all positions…",
        )

        trading_bot.emergency_stop("Telegram /kill command")

        summary = trading_bot.get_daily_summary()
        pnl = summary.get("total_pnl", 0)

        handler.reply(
            source,
            f"🚨 <b>EMERGENCY SHUTDOWN COMPLETE</b>\n\n"
            f"✅ All positions closed\n"
            f"✅ Circuit breaker triggered\n"
            f"✅ Bot stopped\n\n"
            f"Final P&L: {_format_pnl_emoji(pnl)}\n\n"
            f"Type /start to restart.",
            _back_button(),
        )
        logger.warning("Emergency shutdown via Telegram /kill")

    except Exception as e:
        logger.error("Error in cmd_kill: %s", e)
        handler.reply(
            source,
            f"❌ Error: {str(e)[:200]}",
            _back_button(),
        )


def cmd_close(source, handler):
    """/close [instrument] — Close specific position."""
    try:
        trading_bot = handler.trading_bot
        args = _get_args(source)

        if not args:
            handler.reply(
                source,
                "❌ <b>Usage:</b> /close NIFTY 24500 CE\n\n"
                "Type the command with the instrument name.\n"
                "Use /positions to see open positions.",
                _back_button(),
            )
            return

        instrument_name = " ".join(args).upper()

        portfolio = trading_bot.get_portfolio()
        positions = portfolio.get("positions", {}).get("open", [])

        matching = None
        for pos in positions:
            pos_instrument = pos.get("instrument", "").upper()
            if (
                instrument_name in pos_instrument
                or pos_instrument in instrument_name
            ):
                matching = pos
                break

        if not matching:
            handler.reply(
                source,
                f"❌ No open position for: {instrument_name}\n\n"
                f"Use /positions to see open positions.",
                _back_button(),
            )
            return

        trade_id = matching.get("trade_id", "")
        instrument = matching.get("instrument", "")
        current_price = matching.get("current_price", 0)

        if hasattr(trading_bot, "_paper_engine"):
            trade = trading_bot._trade_repo.get_trade(trade_id)
            if trade:
                closed = trading_bot._paper_engine.close_position(
                    trade, current_price, "MANUAL",
                )
                if closed:
                    pnl_val = float(getattr(closed, "pnl", 0))
                    handler.reply(
                        source,
                        f"✅ <b>POSITION CLOSED</b>\n\n"
                        f"Instrument: {instrument}\n"
                        f"Exit Price: ₹{current_price:.2f}\n"
                        f"P&L: {_format_pnl_emoji(pnl_val)}\n"
                        f"Reason: Manual close",
                        _back_button(),
                    )
                    return

        handler.reply(
            source,
            f"❌ Failed to close position: {instrument}",
            _back_button(),
        )

    except Exception as e:
        logger.error("Error in cmd_close: %s", e)
        handler.reply(
            source,
            f"❌ Error: {str(e)[:200]}",
            _back_button(),
        )


def cmd_closeall(source, handler):
    """/closeall — Close all positions."""
    try:
        trading_bot = handler.trading_bot
        portfolio = trading_bot.get_portfolio()
        positions = portfolio.get("positions", {})
        open_count = positions.get("open_count", 0)

        if open_count == 0:
            handler.reply(
                source,
                "No open positions to close.",
                _back_button(),
            )
            return

        handler.reply(
            source,
            f"🔄 Closing {open_count} position(s)…",
        )

        closed_trades = []
        if hasattr(trading_bot, "_paper_engine"):
            closed_trades = (
                trading_bot._paper_engine.close_all_positions(
                    "MANUAL"
                )
            )

        total_pnl = sum(
            float(getattr(t, "pnl", 0)) for t in closed_trades
        )

        message = f"✅ <b>ALL POSITIONS CLOSED</b>\n\n"
        message += f"Closed: {len(closed_trades)} position(s)\n\n"

        for trade in closed_trades:
            instrument = getattr(trade, "instrument", "Unknown")
            pnl_val = float(getattr(trade, "pnl", 0))
            message += (
                f"├─ {instrument}: "
                f"{_format_pnl_emoji(pnl_val)}\n"
            )

        message += (
            f"\n<b>Total P&L:</b> {_format_pnl_emoji(total_pnl)}"
        )

        handler.reply(source, message, _back_button())
        logger.info("All positions closed via Telegram /closeall")

    except Exception as e:
        logger.error("Error in cmd_closeall: %s", e)
        handler.reply(
            source,
            f"❌ Error: {str(e)[:200]}",
            _back_button(),
        )


# ══════════════════════════════════════════════════════════
# TOKEN MANAGEMENT COMMANDS (NEW)
# ══════════════════════════════════════════════════════════

def cmd_set_token(source, handler):
    """
    /set_token <new_token>
    Update the Dhan access token on the fly.
    """
    try:
        if not TOKEN_IMPORTS_AVAILABLE:
            handler.reply(
                source,
                "❌ Settings module not available.",
                _back_button(),
            )
            return

        args = _get_args(source)

        if not args:
            handler.reply(
                source,
                "⚠️ <b>Usage:</b> <code>/set_token YOUR_NEW_TOKEN</code>\n\n"
                "📋 <b>How to get your token:</b>\n"
                "1️⃣ Login to Dhan Web\n"
                "2️⃣ Go to API section\n"
                "3️⃣ Copy your Access Token\n"
                "4️⃣ Paste it here\n\n"
                "🔒 Token is stored securely.",
                _token_keyboard(),
            )
            return

        new_token = args[0].strip()

        # Basic validation
        if len(new_token) < 20:
            handler.reply(
                source,
                "❌ Token seems too short. Please check and try again.",
                _back_button(),
            )
            return

        # Update token in settings + .env file
        success = app_settings.update_dhan_token(new_token)

        if not success:
            handler.reply(
                source,
                "❌ <b>Failed to save token.</b>\n"
                "Check bot logs for details.",
                _back_button(),
            )
            return

        # Refresh Dhan client connection with new token
        dhan_client = get_dhan_client()
        dhan_client.refresh_connection()

        # Test the new token
        test_result = dhan_client.test_connection()

        if test_result["connected"]:
            data = test_result.get("data", {})
            available = data.get(
                "availabelBalance",
                data.get("available_balance", "N/A"),
            )

            handler.reply(
                source,
                f"✅ <b>Token Updated Successfully!</b>\n\n"
                f"🔑 <b>Token:</b> <code>{app_settings.get_masked_token()}</code>\n"
                f"🔗 <b>Connection:</b> Active ✅\n"
                f"💰 <b>Balance:</b> ₹{available}\n"
                f"🕐 <b>Updated:</b> {get_ist_now().strftime('%H:%M:%S')}\n\n"
                f"🤖 Bot is ready to trade!",
                _back_button(),
            )
            logger.info("Dhan token updated via /set_token")
        else:
            handler.reply(
                source,
                f"⚠️ <b>Token saved but connection failed!</b>\n\n"
                f"🔑 <b>Token:</b> <code>{app_settings.get_masked_token()}</code>\n"
                f"❌ <b>Error:</b> {_escape_html(test_result['message'])}\n\n"
                f"Token might be invalid or expired.\n"
                f"Use /check_token to test again.",
                _back_button(),
            )
            logger.warning(
                "Token saved but test failed: %s",
                test_result["message"],
            )

        # Try to delete the message containing the token (security)
        try:
            if hasattr(source, "message_id") and hasattr(handler, "bot"):
                handler.bot.delete_message(
                    source.chat.id, source.message_id,
                )
                logger.info("Deleted message containing token for security")
        except Exception:
            pass

    except Exception as e:
        logger.error("Error in cmd_set_token: %s", e)
        handler.reply(
            source,
            f"❌ Error: {str(e)[:200]}",
            _back_button(),
        )


def cmd_check_token(source, handler):
    """
    /check_token
    Check if current Dhan token is valid and working.
    """
    try:
        if not TOKEN_IMPORTS_AVAILABLE:
            handler.reply(
                source,
                "❌ Settings module not available.",
                _back_button(),
            )
            return

        dhan_client = get_dhan_client()
        test_result = dhan_client.test_connection()

        if test_result["connected"]:
            data = test_result.get("data", {})
            available = data.get(
                "availabelBalance",
                data.get("available_balance", "N/A"),
            )
            utilized = data.get(
                "utilizedAmount",
                data.get("utilized_amount", "N/A"),
            )

            handler.reply(
                source,
                f"✅ <b>Token Status: VALID</b>\n\n"
                f"🔑 <b>Token:</b> <code>{app_settings.get_masked_token()}</code>\n"
                f"💰 <b>Available:</b> ₹{available}\n"
                f"📊 <b>Utilized:</b> ₹{utilized}\n"
                f"🕐 <b>Checked:</b> {get_ist_now().strftime('%H:%M:%S')}\n\n"
                f"✅ Everything is working!",
                _back_button(),
            )
        else:
            handler.reply(
                source,
                f"❌ <b>Token Status: INVALID / EXPIRED</b>\n\n"
                f"🔑 <b>Token:</b> <code>{app_settings.get_masked_token()}</code>\n"
                f"⚠️ <b>Error:</b> {_escape_html(test_result['message'])}\n\n"
                f"🔄 Use <code>/set_token NEW_TOKEN</code> to update.",
                _back_button(),
            )

    except Exception as e:
        logger.error("Error in cmd_check_token: %s", e)
        handler.reply(
            source,
            f"❌ Error: {str(e)[:200]}",
            _back_button(),
        )


def cmd_token_status(source, handler):
    """
    /token_status
    Quick overview of token without testing connection.
    """
    try:
        if not TOKEN_IMPORTS_AVAILABLE:
            handler.reply(
                source,
                "❌ Settings module not available.",
                _back_button(),
            )
            return

        token = app_settings.DHAN_ACCESS_TOKEN
        client_id = app_settings.DHAN_CLIENT_ID

        is_set = bool(token and len(token) > 10)
        client_set = bool(client_id and len(client_id) > 3)

        status_emoji = "✅" if is_set else "❌"
        client_emoji = "✅" if client_set else "❌"

        dhan_client = get_dhan_client()
        connected = dhan_client.is_connected()

        handler.reply(
            source,
            f"🔐 <b>Token Status Overview</b>\n\n"
            f"{client_emoji} <b>Client ID:</b> {'Set' if client_set else 'NOT SET'}\n"
            f"{status_emoji} <b>Access Token:</b> {app_settings.get_masked_token()}\n"
            f"📏 <b>Token Length:</b> {len(token) if token else 0} chars\n"
            f"🔗 <b>Connected:</b> {'Yes ✅' if connected else 'No ❌'}\n\n"
            f"<b>💡 Commands:</b>\n"
            f"  <code>/set_token TOKEN</code> - Update token\n"
            f"  <code>/check_token</code> - Test if token works",
            _back_button(),
        )

    except Exception as e:
        logger.error("Error in cmd_token_status: %s", e)
        handler.reply(
            source,
            f"❌ Error: {str(e)[:200]}",
            _back_button(),
        )


# ══════════════════════════════════════════════════════════
# HELP / MENU COMMAND
# ══════════════════════════════════════════════════════════

def cmd_help(source, handler):
    """/help or /menu — Interactive button menu."""
    message = (
        "🤖 <b>TRADING BOT MENU</b>\n\n"
        "Tap a category below to navigate:\n\n"
        "🎛 <b>Control</b> — Start, Stop, Pause, Resume, Restart\n"
        "📊 <b>Status</b> — Bot status, System health\n"
        "💼 <b>Portfolio</b> — Capital, Positions, Trades, P&amp;L\n"
        "🧠 <b>Analysis</b> — Signals, Brains, Watchlist\n"
        "⚙️ <b>Settings</b> — Config, Mode, Risk, Reports\n"
        "🚨 <b>Emergency</b> — Kill, Close positions\n"
        "🔑 <b>Token</b> — Set, Check, Status of Dhan token\n\n"
        "<i>You can also type commands like /status directly.</i>"
    )

    handler.reply(source, message, _main_menu_keyboard())


# ══════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════

__all__ = [
    # Control
    "cmd_start",
    "cmd_stop",
    "cmd_pause",
    "cmd_resume",
    "cmd_restart",
    # Status
    "cmd_status",
    "cmd_health",
    # Portfolio
    "cmd_portfolio",
    "cmd_positions",
    "cmd_trades",
    "cmd_pnl",
    # Analysis
    "cmd_signals",
    "cmd_brains",
    "cmd_watchlist",
    # Settings
    "cmd_settings",
    "cmd_mode",
    "cmd_risk",
    "cmd_report",
    # Emergency
    "cmd_kill",
    "cmd_close",
    "cmd_closeall",
    # Token Management (NEW)
    "cmd_set_token",
    "cmd_check_token",
    "cmd_token_status",
    # Help
    "cmd_help",
    # Callback handler (buttons)
    "handle_callback",
]                
                
        