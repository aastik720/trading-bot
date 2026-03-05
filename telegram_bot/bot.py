"""
Telegram Bot Handler - Main Bot Controller
============================================

Uses pyTelegramBotAPI (telebot) — synchronous, thread-safe.
No async issues. No event loop problems.

Handles Telegram bot setup, command registration, and message sending.
Runs in a separate thread from the main trading loop.

Threading Model
---------------
    Main Thread:
        TradingBot._main_loop() runs the trading logic.
        Calls alert_manager methods which use send_message_async().

    Telegram Thread:
        TelegramBotHandler._run_polling() listens for commands.
        Handlers access trading_bot directly (read operations).
        Handlers call trading_bot methods (control operations).

Security
--------
    Every command checks if the user is in admin_ids.
    Unauthorized users get "Unauthorized" response.
    Admin IDs are configured in .env file.

Usage
-----
    handler = TelegramBotHandler(token, chat_id, admin_ids, trading_bot)
    handler.setup()
    handler.start_polling()  # Starts in separate thread

    # Send message from main thread (thread-safe)
    handler.send_message_sync("Hello from main thread!")
"""

import logging
import threading
import time
from typing import Optional, List, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.bot import TradingBot

logger = logging.getLogger(__name__)

# ============================================================
# Check if pyTelegramBotAPI is installed
# ============================================================
try:
    import telebot
    from telebot import types
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    telebot = None
    types = None
    logger.warning(
        "pyTelegramBotAPI not installed. "
        "Install with: pip install pyTelegramBotAPI"
    )


class TelegramBotHandler:
    """
    Main Telegram bot controller.

    Handles command registration, polling, and message sending.
    Runs in a separate daemon thread.

    Parameters
    ----------
    token : str
        Telegram bot token from BotFather.
    chat_id : str
        Default chat ID for sending messages.
    admin_ids : list
        List of admin user IDs (integers).
    trading_bot : TradingBot
        Reference to the main trading bot instance.

    Attributes
    ----------
    bot : telebot.TeleBot
        pyTelegramBotAPI TeleBot instance.
    is_running : bool
        Whether the bot is currently polling.

    Examples
    --------
        handler = TelegramBotHandler(
            token="123:ABC...",
            chat_id="-100123456",
            admin_ids=[123456789],
            trading_bot=bot,
        )
        handler.setup()
        handler.start_polling()
    """

    def __init__(
        self,
        token: str,
        chat_id: str,
        admin_ids: List[int],
        trading_bot: "TradingBot",
    ) -> None:
        self._token = token
        self._chat_id = str(chat_id)
        self._admin_ids = [int(aid) for aid in admin_ids if aid]
        self._trading_bot = trading_bot

        self._bot: Optional[Any] = None
        self._polling_thread: Optional[threading.Thread] = None
        self._is_running: bool = False
        self._is_setup: bool = False

        logger.info(
            "TelegramBotHandler initialized | "
            "Chat ID: %s | Admins: %s",
            self._chat_id,
            self._admin_ids,
        )

    # ================================================================ #
    #  PROPERTIES                                                       #
    # ================================================================ #

    @property
    def is_running(self) -> bool:
        """Whether the Telegram bot is currently polling."""
        return self._is_running

    @property
    def chat_id(self) -> str:
        """Default chat ID for messages."""
        return self._chat_id

    @property
    def admin_ids(self) -> List[int]:
        """List of admin user IDs."""
        return self._admin_ids.copy()

    @property
    def trading_bot(self) -> "TradingBot":
        """Reference to the trading bot."""
        return self._trading_bot

    @property
    def bot(self) -> Any:
        """The telebot.TeleBot instance."""
        return self._bot

    # ================================================================ #
    #  SETUP                                                            #
    # ================================================================ #

    def setup(self) -> bool:
        """
        Set up the Telegram bot and register handlers.

        Returns
        -------
        bool
            True if setup successful, False otherwise.
        """
        if not TELEGRAM_AVAILABLE:
            logger.error("Cannot setup: pyTelegramBotAPI not installed")
            return False

        if not self._token or ":" not in self._token:
            logger.error("Cannot setup: Invalid bot token")
            return False

        try:
            # Create bot instance
            self._bot = telebot.TeleBot(
                self._token,
                parse_mode="HTML",
                threaded=True,
            )

            # Test connection
            me = self._bot.get_me()
            logger.info(
                "✅ Bot connected: @%s (ID: %d)",
                me.username, me.id,
            )

            # Register all command handlers
            self._register_handlers()

            # Verify admin IDs
            if not self._admin_ids:
                logger.error(
                    "⚠️ NO ADMIN IDS CONFIGURED! "
                    "Nobody can use the bot! "
                    "Set TELEGRAM_ADMIN_IDS in .env"
                )

            self._is_setup = True
            logger.info(
                "✅ Telegram bot setup complete | Admins: %s",
                self._admin_ids,
            )
            return True

        except Exception as e:
            logger.error("❌ Failed to setup Telegram bot: %s", e)
            return False

    # ================================================================ #
    #  ADMIN CHECK                                                      #
    # ================================================================ #

    def _is_admin(self, user_id: int) -> bool:
        """
        Check if user is an admin.

        Parameters
        ----------
        user_id : int
            Telegram user ID to check.

        Returns
        -------
        bool
            True if user is admin, False otherwise.
        """
        return user_id in self._admin_ids

    def _check_admin_message(self, message) -> bool:
        """
        Check if message sender is admin.
        Sends rejection message if not.

        Returns True if admin, False otherwise.
        """
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"

        if self._is_admin(user_id):
            return True

        logger.warning(
            "⛔ Unauthorized | User: %s (ID:%d) | Command: %s",
            username, user_id, message.text,
        )
        try:
            self._bot.reply_to(
                message,
                f"⛔ Unauthorized.\n\n"
                f"Your ID: {user_id}\n"
                f"Add to TELEGRAM_ADMIN_IDS in .env",
            )
        except Exception:
            pass
        return False

    def _check_admin_callback(self, call) -> bool:
        """
        Check if callback (button press) sender is admin.
        Sends rejection if not.

        Returns True if admin, False otherwise.
        """
        user_id = call.from_user.id

        if self._is_admin(user_id):
            return True

        logger.warning(
            "⛔ Unauthorized callback | User ID: %d | Button: %s",
            user_id, call.data,
        )
        try:
            self._bot.answer_callback_query(
                call.id, "⛔ Unauthorized.", show_alert=True,
            )
        except Exception:
            pass
        return False

    # ================================================================ #
    #  REPLY HELPER — works for messages AND callbacks                  #
    # ================================================================ #

    def reply(self, source, text, reply_markup=None):
        """
        Universal reply that works for both:
          - message objects  (from /command)
          - callback_query objects  (from button press)

        For callbacks, tries to EDIT the existing message.
        If edit fails, sends a new message.

        Parameters
        ----------
        source : message or callback_query
            The source to reply to.
        text : str
            Message text (HTML).
        reply_markup : InlineKeyboardMarkup, optional
            Buttons to attach.
        """
        # Telegram message limit
        if len(text) > 4096:
            text = text[:4090] + "\n…"

        try:
            if hasattr(source, "message"):
                # This is a callback_query — edit the existing message
                try:
                    self._bot.edit_message_text(
                        text=text,
                        chat_id=source.message.chat.id,
                        message_id=source.message.message_id,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )
                except Exception:
                    # Edit failed — send new message
                    self._bot.send_message(
                        chat_id=source.message.chat.id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )
            else:
                # This is a regular message — reply to it
                self._bot.reply_to(
                    source,
                    text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
        except Exception as e:
            logger.error("Reply failed: %s", e)

    # ================================================================ #
    #  HANDLER REGISTRATION                                             #
    # ================================================================ #

    def _register_handlers(self) -> None:
        """Register all command handlers and callback handler."""
        from telegram_bot.handlers import (
            cmd_start,
            cmd_stop,
            cmd_pause,
            cmd_resume,
            cmd_restart,
            cmd_status,
            cmd_health,
            cmd_portfolio,
            cmd_positions,
            cmd_trades,
            cmd_signals,
            cmd_brains,
            cmd_watchlist,
            cmd_settings,
            cmd_mode,
            cmd_report,
            cmd_risk,
            cmd_pnl,
            cmd_kill,
            cmd_close,
            cmd_closeall,
            cmd_help,
            handle_callback,
        )

        bot = self._bot

        # ── Command → handler mapping ──
        command_map = {
            "start":     cmd_start,
            "stop":      cmd_stop,
            "pause":     cmd_pause,
            "resume":    cmd_resume,
            "restart":   cmd_restart,
            "status":    cmd_status,
            "health":    cmd_health,
            "portfolio": cmd_portfolio,
            "positions": cmd_positions,
            "trades":    cmd_trades,
            "pnl":       cmd_pnl,
            "signals":   cmd_signals,
            "brains":    cmd_brains,
            "watchlist": cmd_watchlist,
            "settings":  cmd_settings,
            "mode":      cmd_mode,
            "risk":      cmd_risk,
            "report":    cmd_report,
            "kill":      cmd_kill,
            "close":     cmd_close,
            "closeall":  cmd_closeall,
            "help":      cmd_help,
            "menu":      cmd_help,
        }

        # Register each command
        for cmd_name, handler_func in command_map.items():
            # Create closure to capture handler_func correctly
            def make_handler(func):
                def handler(message):
                    if not self._check_admin_message(message):
                        return
                    username = message.from_user.username or "Unknown"
                    logger.info(
                        "Command: /%s from %s (ID:%d)",
                        message.text.split()[0].lstrip("/"),
                        username,
                        message.from_user.id,
                    )
                    try:
                        func(message, self)
                    except Exception as e:
                        logger.error(
                            "Handler error: %s", e, exc_info=True,
                        )
                        self.reply(
                            message,
                            f"❌ Error: {str(e)[:200]}",
                        )
                return handler
            
            bot.message_handler(commands=[cmd_name])(
                make_handler(handler_func)
            )

        # ── Callback query handler for ALL buttons ──
        @bot.callback_query_handler(func=lambda call: True)
        def callback_handler(call):
            if not self._check_admin_callback(call):
                return

            self._bot.answer_callback_query(call.id)

            username = call.from_user.username or "Unknown"
            logger.info(
                "Button: %s from %s (ID:%d)",
                call.data, username, call.from_user.id,
            )

            try:
                handle_callback(call, self)
            except Exception as e:
                logger.error(
                    "Callback error: %s", e, exc_info=True,
                )
                self.reply(
                    call,
                    f"❌ Error: {str(e)[:200]}",
                )

        logger.info(
            "✅ Registered %d commands + callback handler",
            len(command_map),
        )

    # ================================================================ #
    #  POLLING (Separate Thread) — Simple, no async                     #
    # ================================================================ #

    def start_polling(self) -> bool:
        """
        Start the Telegram bot polling in a separate thread.

        The polling runs in a daemon thread, so it will be
        automatically stopped when the main program exits.

        Returns
        -------
        bool
            True if polling started, False otherwise.
        """
        if not self._is_setup:
            logger.error(
                "Cannot start polling: Bot not setup. "
                "Call setup() first."
            )
            return False

        if self._is_running:
            logger.warning("Polling already running")
            return True

        try:
            self._is_running = True

            self._polling_thread = threading.Thread(
                target=self._run_polling,
                name="TelegramPolling",
                daemon=True,
            )
            self._polling_thread.start()

            logger.info(
                "🟢 Telegram bot polling started! "
                "Send /start or /menu to begin."
            )
            return True

        except Exception as e:
            logger.error("Failed to start polling: %s", e)
            self._is_running = False
            return False

    def _run_polling(self) -> None:
        """
        Run polling in this thread.

        Uses infinity_polling() — simple, synchronous,
        works perfectly in threads. No async needed.
        """
        logger.info("Telegram polling thread running...")

        try:
            self._bot.infinity_polling(
                timeout=10,
                long_polling_timeout=5,
                allowed_updates=["message", "callback_query"],
            )
        except Exception as e:
            logger.error(
                "Polling error: %s", e, exc_info=True,
            )
        finally:
            self._is_running = False
            logger.info("Telegram polling thread stopped")

    def stop_polling(self) -> None:
        """Stop the Telegram bot polling."""
        if not self._is_running:
            return

        logger.info("Stopping Telegram polling...")
        self._is_running = False

        try:
            self._bot.stop_polling()
        except Exception:
            pass

        if self._polling_thread and self._polling_thread.is_alive():
            self._polling_thread.join(timeout=5)

        logger.info("Telegram polling stopped")

    # ================================================================ #
    #  MESSAGE SENDING — All thread-safe                                #
    # ================================================================ #

    def send_message_sync(
        self,
        text: str,
        parse_mode: str = "HTML",
        chat_id: Optional[str] = None,
    ) -> bool:
        """
        Send a message synchronously (thread-safe).

        Use this method when sending from the main thread
        (e.g., from AlertManager in the trading loop).

        Parameters
        ----------
        text : str
            Message text to send.
        parse_mode : str, optional
            Parse mode: 'HTML', 'Markdown', or None.
        chat_id : str, optional
            Override chat ID.

        Returns
        -------
        bool
            True if sent successfully, False otherwise.
        """
        if not self._bot:
            logger.warning("Cannot send: Bot not initialized")
            return False

        target = chat_id or self._chat_id

        try:
            if len(text) > 4096:
                text = text[:4090] + "\n…"

            self._bot.send_message(
                chat_id=target,
                text=text,
                parse_mode=parse_mode if parse_mode else None,
            )
            logger.debug(
                "Message sent to %s (%d chars)", target, len(text),
            )
            return True

        except Exception as e:
            logger.error("Failed to send message: %s", e)
            return False

    def send_message_async(
        self,
        text: str,
        parse_mode: str = "HTML",
        chat_id: Optional[str] = None,
    ) -> None:
        """
        Send a message asynchronously (fire-and-forget).

        Use this method when you don't need to wait for result.
        Message is sent in a background thread.

        Parameters
        ----------
        text : str
            Message text to send.
        parse_mode : str, optional
            Parse mode: 'HTML', 'Markdown', or None.
        chat_id : str, optional
            Override chat ID.
        """
        thread = threading.Thread(
            target=self.send_message_sync,
            args=(text, parse_mode, chat_id),
            daemon=True,
        )
        thread.start()
        logger.debug("Message queued for %s", chat_id or self._chat_id)

    # Backward compatibility alias
    async def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        chat_id: Optional[str] = None,
    ) -> bool:
        """Async send (wraps sync for backward compatibility)."""
        return self.send_message_sync(text, parse_mode, chat_id)

    # ================================================================ #
    #  UTILITY METHODS                                                  #
    # ================================================================ #

    def get_status(self) -> dict:
        """
        Get Telegram bot status.

        Returns
        -------
        dict
            Status information.
        """
        return {
            "is_running": self._is_running,
            "is_setup": self._is_setup,
            "chat_id": self._chat_id,
            "admin_count": len(self._admin_ids),
            "thread_alive": (
                self._polling_thread.is_alive()
                if self._polling_thread
                else False
            ),
        }

    def __repr__(self) -> str:
        status = "running" if self._is_running else "stopped"
        return (
            f"TelegramBotHandler(status={status}, "
            f"admins={len(self._admin_ids)})"
        )


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
    print("  TELEGRAM BOT HANDLER - Test")
    print("=" * 60)

    print("\n  Checking dependencies...")

    if TELEGRAM_AVAILABLE:
        print("  ✅ pyTelegramBotAPI is installed")
    else:
        print("  ❌ pyTelegramBotAPI NOT installed")
        print("     Run: pip install pyTelegramBotAPI")

    print("\n  Checking configuration...")

    try:
        from config.settings import settings

        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
        admin_ids_raw = getattr(settings, "TELEGRAM_ADMIN_IDS", [])

        if isinstance(admin_ids_raw, str):
            admin_ids = [
                int(x.strip())
                for x in admin_ids_raw.split(",")
                if x.strip()
            ]
        else:
            admin_ids = list(admin_ids_raw) if admin_ids_raw else []

        has_token = bool(token and ":" in token)
        has_chat = bool(chat_id)
        has_admins = bool(admin_ids)

        print(f"  Token:     {'✅ Set' if has_token else '❌ Not set'}")
        print(f"  Chat ID:   {'✅ Set' if has_chat else '❌ Not set'}")
        print(
            f"  Admin IDs: "
            f"{'✅ Set (' + str(len(admin_ids)) + ')' if has_admins else '❌ Not set'}"
        )

        if has_token and has_chat and has_admins and TELEGRAM_AVAILABLE:
            print("\n  Creating handler (mock trading bot)...")

            class MockTradingBot:
                def get_status(self):
                    return {"state": "STOPPED", "mode": "PAPER"}

                def get_portfolio(self):
                    return {"capital": {"current": 10000}}

            handler = TelegramBotHandler(
                token=token,
                chat_id=chat_id,
                admin_ids=admin_ids,
                trading_bot=MockTradingBot(),
            )

            print(f"  {handler}")
            print(f"  Status: {handler.get_status()}")
            print("\n  ⚠️  Not starting polling (test only)")

        else:
            print("\n  ⚠️  Cannot create handler - missing config")

    except Exception as e:
        print(f"  ❌ Error: {e}")

    print("\n" + "=" * 60 + "\n")