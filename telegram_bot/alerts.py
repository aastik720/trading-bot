"""
Alert Manager - Automatic Notifications
=========================================

Sends automatic notifications to Telegram when events occur:
- Trade opened/closed
- Market open/close
- Circuit breaker triggered/reset
- Errors
- Daily reports

These are NOT triggered by user commands. They are sent
automatically by the trading bot during operation.

Usage
-----
    alert_manager = AlertManager(telegram_bot_handler)
    
    # In trading loop:
    alert_manager.send_trade_opened(trade)
    alert_manager.send_trade_closed(trade)
    alert_manager.send_market_open()
    alert_manager.send_market_close(summary)
    alert_manager.send_circuit_breaker_alert(reason, status)

Thread Safety
-------------
    AlertManager uses send_message_async() which is thread-safe.
    Can be called from the main trading thread without blocking.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Dict, Any

if TYPE_CHECKING:
    from telegram_bot.bot import TelegramBotHandler

from utils.helpers import (
    format_currency,
    format_pnl,
    format_duration,
    format_percentage,
    get_ist_now,
    safe_divide,
)

logger = logging.getLogger(__name__)


class AlertManager:
    """
    Manages automatic Telegram notifications.

    Sends alerts for trading events without user interaction.
    All messages are sent asynchronously to avoid blocking.

    Parameters
    ----------
    telegram_bot : TelegramBotHandler
        The Telegram bot handler to send messages through.

    Attributes
    ----------
    is_enabled : bool
        Whether alerts are enabled.
    last_market_open_alert : datetime
        Timestamp of last market open alert (to avoid duplicates).

    Examples
    --------
        alert_manager = AlertManager(telegram_handler)
        alert_manager.send_trade_opened(trade)
    """

    def __init__(self, telegram_bot: "TelegramBotHandler") -> None:
        self._telegram_bot = telegram_bot
        self._is_enabled: bool = True

        # Track last alerts to avoid duplicates
        self._last_market_open_alert: Optional[datetime] = None
        self._last_market_close_alert: Optional[datetime] = None
        self._last_error_alert: Optional[datetime] = None
        self._last_position_update: Dict[str, datetime] = {}

        # Cooldowns (in seconds)
        self._error_cooldown: int = 300  # 5 minutes between error alerts
        self._position_update_cooldown: int = 600  # 10 minutes between position updates

        logger.info("AlertManager initialized")

    # ================================================================ #
    #  PROPERTIES                                                       #
    # ================================================================ #

    @property
    def is_enabled(self) -> bool:
        """Whether alerts are enabled."""
        return self._is_enabled

    @is_enabled.setter
    def is_enabled(self, value: bool) -> None:
        """Enable or disable alerts."""
        self._is_enabled = value
        logger.info("Alerts %s", "enabled" if value else "disabled")

    # ================================================================ #
    #  HELPER METHODS                                                   #
    # ================================================================ #

    def _send(self, message: str, parse_mode: str = "HTML") -> None:
        """
        Send a message (fire-and-forget).

        Parameters
        ----------
        message : str
            Message text to send.
        parse_mode : str
            Parse mode (HTML or Markdown).
        """
        if not self._is_enabled:
            logger.debug("Alerts disabled, skipping message")
            return

        if not self._telegram_bot:
            logger.warning("No Telegram bot configured, skipping alert")
            return

        try:
            self._telegram_bot.send_message_async(message, parse_mode=parse_mode)
        except Exception as e:
            logger.error("Failed to send alert: %s", e)

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        if not text:
            return ""
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _format_pnl_emoji(self, pnl: float) -> str:
        """Format PnL with emoji."""
        if pnl > 0:
            return f"🟢 +{format_currency(pnl)}"
        elif pnl < 0:
            return f"🔴 {format_currency(pnl)}"
        else:
            return f"⚪ {format_currency(0)}"

    # ================================================================ #
    #  TRADE ALERTS                                                     #
    # ================================================================ #

    def send_trade_opened(self, trade: Any) -> None:
        """
        Send notification when a trade is opened.

        Parameters
        ----------
        trade : Trade
            The trade object that was opened.
        """
        try:
            instrument = getattr(trade, "instrument", "Unknown")
            symbol = getattr(trade, "symbol", "")
            strike = getattr(trade, "strike", 0)
            option_type = getattr(trade, "option_type", "CE")
            side = getattr(trade, "side", "BUY")
            entry_price = float(getattr(trade, "entry_price", 0))
            quantity = int(getattr(trade, "quantity", 0))
            lots = int(getattr(trade, "lots", 1))
            stop_loss = float(getattr(trade, "stop_loss", 0))
            take_profit = float(getattr(trade, "take_profit", 0))
            confidence = float(getattr(trade, "confidence", 0))
            reasoning = getattr(trade, "reasoning", "")
            mode = getattr(trade, "mode", "PAPER")

            # Calculate cost and SL/TP percentages
            cost = entry_price * quantity
            sl_pct = ((stop_loss - entry_price) / entry_price * 100) if entry_price > 0 else -30
            tp_pct = ((take_profit - entry_price) / entry_price * 100) if entry_price > 0 else 50

            # Truncate reasoning
            if len(reasoning) > 100:
                reasoning = reasoning[:97] + "..."

            message = (
                f"📈 <b>TRADE OPENED</b>\n\n"
                f"<b>{instrument}</b>\n"
                f"├─ Side: {side}\n"
                f"├─ Premium: ₹{entry_price:.2f}\n"
                f"├─ Quantity: {quantity} ({lots} lot{'s' if lots > 1 else ''})\n"
                f"└─ Cost: {format_currency(cost)}\n\n"
                f"<b>Exit Targets:</b>\n"
                f"├─ SL: ₹{stop_loss:.2f} ({sl_pct:.0f}%)\n"
                f"└─ TP: ₹{take_profit:.2f} (+{tp_pct:.0f}%)\n\n"
                f"<b>Signal:</b>\n"
                f"├─ Confidence: {confidence:.0%}\n"
                f"└─ Reason: {self._escape_html(reasoning)}\n\n"
                f"Mode: {mode}"
            )

            self._send(message)
            logger.info("Sent trade opened alert: %s", instrument)

        except Exception as e:
            logger.error("Error sending trade opened alert: %s", e)

    def send_trade_closed(self, trade: Any) -> None:
        """
        Send notification when a trade is closed.

        Parameters
        ----------
        trade : Trade
            The trade object that was closed.
        """
        try:
            instrument = getattr(trade, "instrument", "Unknown")
            entry_price = float(getattr(trade, "entry_price", 0))
            exit_price = float(getattr(trade, "exit_price", 0))
            quantity = int(getattr(trade, "quantity", 0))
            pnl = float(getattr(trade, "pnl", 0))
            pnl_percentage = float(getattr(trade, "pnl_percentage", 0))
            exit_reason = getattr(trade, "exit_reason", "Unknown")
            entry_time = getattr(trade, "entry_time", None)
            exit_time = getattr(trade, "exit_time", None)

            # Calculate duration
            duration_str = "N/A"
            if entry_time and exit_time:
                try:
                    duration = exit_time - entry_time
                    duration_str = format_duration(duration.total_seconds())
                except Exception:
                    pass

            # Determine if profit or loss
            if pnl >= 0:
                header = "✅ <b>TRADE CLOSED - PROFIT</b>"
                pnl_str = f"🟢 +{format_currency(pnl)}"
            else:
                header = "❌ <b>TRADE CLOSED - LOSS</b>"
                pnl_str = f"🔴 {format_currency(pnl)}"

            # Exit reason formatting
            reason_text = {
                "SL": "Stop Loss hit",
                "TP": "Take Profit hit",
                "TRAIL": "Trailing Stop hit",
                "TIME": "Market close",
                "MANUAL": "Manual close",
                "EMERGENCY": "Emergency stop",
                "BOT_STOP": "Bot stopped",
            }.get(exit_reason, exit_reason)

            message = (
                f"{header}\n\n"
                f"<b>{instrument}</b>\n"
                f"├─ Entry: ₹{entry_price:.2f}\n"
                f"├─ Exit: ₹{exit_price:.2f}\n"
                f"├─ Change: {pnl_percentage:+.1f}%\n"
                f"└─ P&L: {pnl_str}\n\n"
                f"<b>Details:</b>\n"
                f"├─ Reason: {reason_text}\n"
                f"└─ Duration: {duration_str}"
            )

            self._send(message)
            logger.info("Sent trade closed alert: %s P&L: %.2f", instrument, pnl)

        except Exception as e:
            logger.error("Error sending trade closed alert: %s", e)

    # ================================================================ #
    #  CIRCUIT BREAKER ALERTS                                           #
    # ================================================================ #

    def send_circuit_breaker_alert(self, reason: str, status: Dict[str, Any]) -> None:
        """
        Send notification when circuit breaker triggers.

        Parameters
        ----------
        reason : str
            Why the circuit breaker was triggered.
        status : dict
            Circuit breaker status dict.
        """
        try:
            daily_pnl = status.get("daily_pnl", 0)
            consecutive_losses = status.get("consecutive_losses", 0)
            cooldown_seconds = status.get("cooldown_remaining_seconds", 3600)
            cooldown_minutes = cooldown_seconds // 60

            # Calculate auto-resume time
            now = get_ist_now()
            resume_time = now.replace(
                minute=now.minute + cooldown_minutes
            )
            resume_str = resume_time.strftime("%I:%M %p")

            message = (
                f"🚨 <b>CIRCUIT BREAKER TRIGGERED</b>\n\n"
                f"<b>Reason:</b> {self._escape_html(reason)}\n\n"
                f"<b>Status:</b>\n"
                f"├─ Daily P&L: {self._format_pnl_emoji(daily_pnl)}\n"
                f"├─ Consecutive Losses: {consecutive_losses}\n"
                f"└─ Cooldown: {cooldown_minutes} minutes\n\n"
                f"⏰ Auto-resume at: {resume_str}\n\n"
                f"<b>Actions:</b>\n"
                f"• All new trades STOPPED\n"
                f"• Existing positions still monitored\n"
                f"• SL/TP will still trigger\n\n"
                f"Use /resume to override cooldown."
            )

            self._send(message)
            logger.warning("Sent circuit breaker alert: %s", reason)

        except Exception as e:
            logger.error("Error sending circuit breaker alert: %s", e)

    def send_circuit_breaker_reset(self) -> None:
        """Send notification when circuit breaker resets."""
        try:
            message = (
                f"✅ <b>CIRCUIT BREAKER RESET</b>\n\n"
                f"Trading has resumed.\n"
                f"The bot is now scanning for opportunities."
            )

            self._send(message)
            logger.info("Sent circuit breaker reset alert")

        except Exception as e:
            logger.error("Error sending circuit breaker reset alert: %s", e)

    # ================================================================ #
    #  MARKET ALERTS                                                    #
    # ================================================================ #

    def send_market_open(self) -> None:
        """Send notification when market opens."""
        try:
            now = get_ist_now()

            # Avoid duplicate alerts (only once per day)
            if self._last_market_open_alert:
                if self._last_market_open_alert.date() == now.date():
                    logger.debug("Market open alert already sent today")
                    return

            self._last_market_open_alert = now

            # Get prices
            nifty_price = "N/A"
            banknifty_price = "N/A"

            try:
                if self._telegram_bot and hasattr(self._telegram_bot, '_trading_bot'):
                    trading_bot = self._telegram_bot._trading_bot
                    if hasattr(trading_bot, '_market_data'):
                        nifty_quote = trading_bot._market_data.get_quote("NIFTY")
                        banknifty_quote = trading_bot._market_data.get_quote("BANKNIFTY")
                        nifty_price = f"₹{nifty_quote.get('ltp', 0):,.2f}"
                        banknifty_price = f"₹{banknifty_quote.get('ltp', 0):,.2f}"
            except Exception:
                pass

            # Get expiry
            from utils.indian_market import get_weekly_expiry, format_expiry
            try:
                weekly = get_weekly_expiry()
                expiry_str = f"{weekly.strftime('%d %b')} ({format_expiry(weekly)})"
            except Exception:
                expiry_str = "N/A"

            # Get mode
            mode = "PAPER"
            try:
                if self._telegram_bot and hasattr(self._telegram_bot, '_trading_bot'):
                    trading_bot = self._telegram_bot._trading_bot
                    mode = "PAPER" if getattr(trading_bot._settings, "PAPER_TRADING", True) else "LIVE"
            except Exception:
                pass

            message = (
                f"📈 <b>MARKET OPEN</b>\n\n"
                f"<b>Indices:</b>\n"
                f"├─ NIFTY: {nifty_price}\n"
                f"└─ BANKNIFTY: {banknifty_price}\n\n"
                f"<b>Expiry:</b> {expiry_str}\n\n"
                f"Bot is scanning... 🔍\n"
                f"Mode: {mode}"
            )

            self._send(message)
            logger.info("Sent market open alert")

        except Exception as e:
            logger.error("Error sending market open alert: %s", e)

    def send_market_close(self, summary: Dict[str, Any]) -> None:
        """
        Send notification when market closes with daily summary.

        Parameters
        ----------
        summary : dict
            Daily summary from trading_bot.get_daily_summary().
        """
        try:
            now = get_ist_now()

            # Avoid duplicate alerts (only once per day)
            if self._last_market_close_alert:
                if self._last_market_close_alert.date() == now.date():
                    logger.debug("Market close alert already sent today")
                    return

            self._last_market_close_alert = now

            pnl = summary.get("total_pnl", 0)
            pnl_pct = summary.get("total_pnl_pct", 0)
            trades = summary.get("trades_count", 0)
            wins = summary.get("wins", 0)
            losses = summary.get("losses", 0)
            win_rate = summary.get("win_rate", 0)
            ending_capital = summary.get("ending_capital", 10000)

            message = (
                f"📉 <b>MARKET CLOSED</b>\n\n"
                f"📊 <b>Today's Summary:</b>\n"
                f"├─ P&L: {self._format_pnl_emoji(pnl)} ({pnl_pct:+.1f}%)\n"
                f"├─ Trades: {trades} ({wins}W / {losses}L)\n"
                f"├─ Win Rate: {win_rate:.1f}%\n"
                f"└─ Capital: {format_currency(ending_capital)}\n\n"
                f"See you tomorrow! 👋"
            )

            self._send(message)
            logger.info("Sent market close alert")

        except Exception as e:
            logger.error("Error sending market close alert: %s", e)

    # ================================================================ #
    #  ERROR ALERTS                                                     #
    # ================================================================ #

    def send_error_alert(self, error: str, details: str = "") -> None:
        """
        Send notification when an error occurs.

        Parameters
        ----------
        error : str
            Error description.
        details : str, optional
            Additional details.
        """
        try:
            now = get_ist_now()

            # Rate limit error alerts
            if self._last_error_alert:
                time_diff = (now - self._last_error_alert).total_seconds()
                if time_diff < self._error_cooldown:
                    logger.debug("Error alert rate limited (cooldown: %ds)", self._error_cooldown)
                    return

            self._last_error_alert = now

            # Truncate error message
            error_text = self._escape_html(str(error)[:300])
            details_text = self._escape_html(str(details)[:200]) if details else ""

            message = (
                f"❌ <b>ERROR</b>\n\n"
                f"{error_text}\n"
            )

            if details_text:
                message += f"\n<i>{details_text}</i>\n"

            message += (
                f"\n⚠️ Bot is still running.\n"
                f"Use /health to check system status."
            )

            self._send(message)
            logger.info("Sent error alert: %s", error[:50])

        except Exception as e:
            logger.error("Error sending error alert: %s", e)

    # ================================================================ #
    #  BOT LIFECYCLE ALERTS                                             #
    # ================================================================ #

    def send_bot_started(self) -> None:
        """Send notification when bot starts."""
        try:
            mode = "PAPER"
            capital = 10000
            instruments = ["NIFTY", "BANKNIFTY"]
            scan_interval = 30

            try:
                if self._telegram_bot and hasattr(self._telegram_bot, '_trading_bot'):
                    trading_bot = self._telegram_bot._trading_bot
                    settings = trading_bot._settings
                    mode = "PAPER" if getattr(settings, "PAPER_TRADING", True) else "LIVE"
                    capital = getattr(settings, "INITIAL_CAPITAL", 10000)
                    instruments = getattr(settings, "OPTIONS_INSTRUMENTS", ["NIFTY", "BANKNIFTY"])
                    scan_interval = getattr(settings, "SCAN_INTERVAL", 30)
            except Exception:
                pass

            mode_emoji = "📝" if mode == "PAPER" else "💰"

            message = (
                f"✅ <b>BOT STARTED</b>\n\n"
                f"<b>Configuration:</b>\n"
                f"├─ Mode: {mode_emoji} {mode} TRADING\n"
                f"├─ Capital: {format_currency(capital)}\n"
                f"├─ Instruments: {', '.join(instruments)}\n"
                f"└─ Scan: every {scan_interval}s\n\n"
                f"Scanning for opportunities... 🔍"
            )

            self._send(message)
            logger.info("Sent bot started alert")

        except Exception as e:
            logger.error("Error sending bot started alert: %s", e)

    def send_bot_stopped(self, reason: str = "Manual") -> None:
        """
        Send notification when bot stops.

        Parameters
        ----------
        reason : str
            Why the bot stopped.
        """
        try:
            pnl = 0
            try:
                if self._telegram_bot and hasattr(self._telegram_bot, '_trading_bot'):
                    trading_bot = self._telegram_bot._trading_bot
                    summary = trading_bot.get_daily_summary()
                    pnl = summary.get("total_pnl", 0)
            except Exception:
                pass

            message = (
                f"🛑 <b>BOT STOPPED</b>\n\n"
                f"<b>Reason:</b> {self._escape_html(reason)}\n"
                f"<b>Final P&L:</b> {self._format_pnl_emoji(pnl)}\n\n"
                f"Type /start to restart."
            )

            self._send(message)
            logger.info("Sent bot stopped alert: %s", reason)

        except Exception as e:
            logger.error("Error sending bot stopped alert: %s", e)

    # ================================================================ #
    #  DAILY REPORT                                                     #
    # ================================================================ #

    def send_daily_report(self, report: Dict[str, Any]) -> None:
        """
        Send detailed daily report at market close.

        Parameters
        ----------
        report : dict
            Daily report data.
        """
        try:
            date_str = report.get("date", get_ist_now().strftime("%Y-%m-%d"))
            starting_capital = report.get("starting_capital", 10000)
            ending_capital = report.get("ending_capital", 10000)
            pnl = report.get("total_pnl", 0)
            pnl_pct = report.get("total_pnl_pct", 0)
            trades = report.get("trades_count", 0)
            wins = report.get("wins", 0)
            losses = report.get("losses", 0)
            win_rate = report.get("win_rate", 0)
            best_trade = report.get("best_trade", 0)
            worst_trade = report.get("worst_trade", 0)
            max_drawdown = report.get("max_drawdown_pct", 0)
            cb_triggered = report.get("circuit_breaker_triggered", False)

            message = (
                f"📊 <b>DAILY REPORT</b>\n"
                f"<i>{date_str}</i>\n\n"
                f"<b>Performance:</b>\n"
                f"├─ P&L: {self._format_pnl_emoji(pnl)} ({pnl_pct:+.1f}%)\n"
                f"├─ Trades: {trades} ({wins}W / {losses}L)\n"
                f"└─ Win Rate: {win_rate:.1f}%\n\n"
                f"<b>Capital:</b>\n"
                f"└─ {format_currency(starting_capital)} → {format_currency(ending_capital)}\n\n"
                f"<b>Extremes:</b>\n"
                f"├─ Best: {format_currency(best_trade)}\n"
                f"├─ Worst: {format_currency(worst_trade)}\n"
                f"└─ Max Drawdown: {max_drawdown:.1f}%\n\n"
                f"<b>Circuit Breaker:</b> {'🚨 Triggered' if cb_triggered else '✅ Not triggered'}"
            )

            self._send(message)
            logger.info("Sent daily report")

        except Exception as e:
            logger.error("Error sending daily report: %s", e)

    # ================================================================ #
    #  POSITION UPDATE (Optional)                                       #
    # ================================================================ #

    def send_position_update(self, position: Dict[str, Any]) -> None:
        """
        Send position update notification.

        Only sends if significant movement (>10% change) and
        hasn't been sent recently (cooldown).

        Parameters
        ----------
        position : dict
            Position data with current price and P&L.
        """
        try:
            trade_id = position.get("trade_id", "")
            pnl_pct = abs(position.get("pnl_pct", 0))

            # Only send for significant moves (>10%)
            if pnl_pct < 10:
                return

            # Check cooldown
            now = get_ist_now()
            if trade_id in self._last_position_update:
                time_diff = (now - self._last_position_update[trade_id]).total_seconds()
                if time_diff < self._position_update_cooldown:
                    return

            self._last_position_update[trade_id] = now

            instrument = position.get("instrument", "Unknown")
            entry_price = position.get("entry_price", 0)
            current_price = position.get("current_price", 0)
            pnl = position.get("pnl", 0)
            pnl_pct = position.get("pnl_pct", 0)
            sl = position.get("stop_loss", 0)
            tp = position.get("take_profit", 0)

            pnl_emoji = "📈" if pnl >= 0 else "📉"
            pnl_str = self._format_pnl_emoji(pnl)

            message = (
                f"{pnl_emoji} <b>POSITION UPDATE</b>\n\n"
                f"<b>{instrument}</b>\n"
                f"├─ Entry: ₹{entry_price:.2f}\n"
                f"├─ Current: ₹{current_price:.2f}\n"
                f"├─ P&L: {pnl_str} ({pnl_pct:+.1f}%)\n"
                f"└─ SL: ₹{sl:.2f} | TP: ₹{tp:.2f}"
            )

            self._send(message)
            logger.debug("Sent position update: %s", instrument)

        except Exception as e:
            logger.error("Error sending position update: %s", e)

    # ================================================================ #
    #  UTILITY METHODS                                                  #
    # ================================================================ #

    def enable(self) -> None:
        """Enable alerts."""
        self._is_enabled = True
        logger.info("Alerts enabled")

    def disable(self) -> None:
        """Disable alerts."""
        self._is_enabled = False
        logger.info("Alerts disabled")

    def reset_cooldowns(self) -> None:
        """Reset all cooldown timers."""
        self._last_market_open_alert = None
        self._last_market_close_alert = None
        self._last_error_alert = None
        self._last_position_update.clear()
        logger.info("Alert cooldowns reset")

    def get_status(self) -> Dict[str, Any]:
        """
        Get alert manager status.

        Returns
        -------
        dict
            Status information.
        """
        return {
            "enabled": self._is_enabled,
            "telegram_connected": self._telegram_bot is not None,
            "last_market_open": (
                self._last_market_open_alert.isoformat()
                if self._last_market_open_alert else None
            ),
            "last_market_close": (
                self._last_market_close_alert.isoformat()
                if self._last_market_close_alert else None
            ),
            "last_error": (
                self._last_error_alert.isoformat()
                if self._last_error_alert else None
            ),
            "tracked_positions": len(self._last_position_update),
        }

    def __repr__(self) -> str:
        status = "enabled" if self._is_enabled else "disabled"
        return f"AlertManager(status={status})"


# ====================================================================== #
#  Standalone test                                                         #
# ====================================================================== #

if __name__ == "__main__":
    import sys
    import os

    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    print("\n" + "=" * 60)
    print("  ALERT MANAGER - Test")
    print("=" * 60)

    # Mock TelegramBotHandler
    class MockTelegramBot:
        def send_message_async(self, message, parse_mode="HTML"):
            print(f"\n{'─' * 40}")
            print("MOCK MESSAGE:")
            print(message.replace("<b>", "").replace("</b>", "")
                  .replace("<i>", "").replace("</i>", ""))
            print(f"{'─' * 40}")

    mock_bot = MockTelegramBot()
    alert_manager = AlertManager(mock_bot)

    print(f"\n  {alert_manager}")
    print(f"  Status: {alert_manager.get_status()}")

    # Test trade opened
    print("\n  Testing send_trade_opened...")

    class MockTrade:
        instrument = "NIFTY 24500 CE"
        symbol = "NIFTY"
        strike = 24500
        option_type = "CE"
        side = "BUY"
        entry_price = 95.0
        quantity = 25
        lots = 1
        stop_loss = 66.5
        take_profit = 142.5
        confidence = 0.72
        reasoning = "RSI oversold at 28, MACD bullish crossover"
        mode = "PAPER"

    alert_manager.send_trade_opened(MockTrade())

    # Test trade closed (profit)
    print("\n  Testing send_trade_closed (profit)...")

    class MockClosedTrade:
        instrument = "NIFTY 24500 CE"
        entry_price = 95.0
        exit_price = 142.0
        quantity = 25
        pnl = 1175.0
        pnl_percentage = 49.5
        exit_reason = "TP"
        entry_time = get_ist_now()
        exit_time = get_ist_now()

    alert_manager.send_trade_closed(MockClosedTrade())

    # Test trade closed (loss)
    print("\n  Testing send_trade_closed (loss)...")

    class MockLossTrade:
        instrument = "BANKNIFTY 52000 PE"
        entry_price = 180.0
        exit_price = 126.0
        quantity = 15
        pnl = -810.0
        pnl_percentage = -30.0
        exit_reason = "SL"
        entry_time = get_ist_now()
        exit_time = get_ist_now()

    alert_manager.send_trade_closed(MockLossTrade())

    # Test circuit breaker
    print("\n  Testing send_circuit_breaker_alert...")
    alert_manager.send_circuit_breaker_alert(
        "5 consecutive losses",
        {
            "daily_pnl": -300,
            "consecutive_losses": 5,
            "cooldown_remaining_seconds": 3600,
        }
    )

    # Test market open
    print("\n  Testing send_market_open...")
    alert_manager.send_market_open()

    # Test market close
    print("\n  Testing send_market_close...")
    alert_manager.send_market_close({
        "total_pnl": 1240,
        "total_pnl_pct": 12.4,
        "trades_count": 5,
        "wins": 3,
        "losses": 2,
        "win_rate": 60.0,
        "ending_capital": 11240,
    })

    # Test bot started
    print("\n  Testing send_bot_started...")
    alert_manager.send_bot_started()

    # Test bot stopped
    print("\n  Testing send_bot_stopped...")
    alert_manager.send_bot_stopped("Manual stop")

    # Test error
    print("\n  Testing send_error_alert...")
    alert_manager.send_error_alert("Connection timeout", "Dhan API not responding")

    print("\n" + "=" * 60)
    print("  ✅ All AlertManager tests completed!")
    print("=" * 60 + "\n")