"""
Trading Bot - Main Orchestrator
================================

This is the HEART of the trading bot. It initialises all components,
runs the main trading loop, and orchestrates the entire trading lifecycle.

Now includes Telegram integration for remote monitoring and control.

Threading Model
---------------
    Main Thread:
        TradingBot._main_loop() - trading logic, position monitoring
        Calls AlertManager methods to send notifications

    Telegram Thread:
        TelegramBotHandler._run_polling() - listens for commands
        Handlers access TradingBot for data and control

The bot runs FOREVER (until stopped) and follows this cycle:

    ┌─────────────────────────────────────────────────────────────┐
    │                     MAIN LOOP (every 30s)                   │
    ├─────────────────────────────────────────────────────────────┤
    │                                                             │
    │  1. PRE-CHECKS                                              │
    │     ├── Is it a trading day?                                │
    │     ├── Is market open?                                     │
    │     ├── Should close all positions? (near market close)     │
    │     └── Is circuit breaker safe?                            │
    │                                                             │
    │  2. SCAN & TRADE (for each instrument)                      │
    │     ├── Brain analyzes market → consensus signal            │
    │     │   (Technical 40% + Sentiment 35% + Pattern 25%)       │
    │     ├── RiskManager validates → approved/rejected           │
    │     ├── PaperEngine executes → Trade saved to DB            │
    │     └── AlertManager sends notification → Telegram          │
    │                                                             │
    │  3. MONITOR POSITIONS                                       │
    │     ├── Update current prices                               │
    │     ├── Check SL/TP/Trailing/Time exits                     │
    │     ├── Close positions that hit exit conditions            │
    │     └── AlertManager sends close notification               │
    │                                                             │
    │  4. SLEEP (SCAN_INTERVAL seconds)                           │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘

Brain Architecture (Phase 8)
----------------------------
    ┌─────────────────────────────────────────────────────────────┐
    │                    BrainCoordinator                         │
    │                                                             │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
    │  │ Technical   │  │ Sentiment   │  │ Pattern     │         │
    │  │ Brain (40%) │  │ Brain (35%) │  │ Brain (25%) │         │
    │  │             │  │             │  │             │         │
    │  │ RSI, MACD,  │  │ News,       │  │ S/R, Trend, │         │
    │  │ SMA, EMA,   │  │ Keywords,   │  │ Breakout,   │         │
    │  │ Bollinger,  │  │ Finnhub API │  │ Candles,    │         │
    │  │ Volume      │  │             │  │ Volume      │         │
    │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
    │         │                │                │                 │
    │         └────────────────┼────────────────┘                 │
    │                          ▼                                  │
    │              ┌─────────────────────┐                        │
    │              │  Weighted Voting    │                        │
    │              │  Consensus Signal   │                        │
    │              └─────────────────────┘                        │
    └─────────────────────────────────────────────────────────────┘

States
------
    STOPPED  → Bot is not running (initial state)
    RUNNING  → Bot is actively trading
    PAUSED   → Bot monitors positions but doesn't take new trades
    ERROR    → Bot encountered a critical error
"""

import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from config.settings import settings
from config import constants
from utils.helpers import (
    format_currency,
    format_pnl,
    format_duration,
    get_ist_now,
)
from utils.indian_market import (
    is_market_open,
    is_trading_day,
    can_take_new_trades,
    should_close_all_positions,
    get_market_status,
    get_time_to_market_open,
)

logger = logging.getLogger(__name__)


class TradingBot:
    """
    Main trading bot orchestrator.

    Initialises all components and runs the main trading loop.
    This is the entry point for the entire trading system.

    Now includes:
    - Multi-brain analysis (Technical + Sentiment + Pattern)
    - Telegram integration for remote monitoring and control
    - Automatic alerts (trade opened, closed, errors)

    Brain Weights:
    - Technical Brain: 40% (RSI, MACD, SMA, EMA, Bollinger, Volume)
    - Sentiment Brain: 35% (News analysis, keyword scoring, Finnhub API)
    - Pattern Brain: 25% (S/R, trend, breakout, candlestick patterns)

    Examples
    --------
        bot = TradingBot()
        bot.start()  # Runs forever until stopped
    """

    def __init__(self) -> None:
        """
        Initialise ALL bot components.

        This sets up:
        - Database and repositories
        - Market data providers
        - Brain coordinator (with all 3 brains)
        - Risk management
        - Order management
        - Paper trading engine
        - Telegram bot and alerts
        """
        logger.info("=" * 60)
        logger.info("  INITIALISING TRADING BOT")
        logger.info("=" * 60)

        self._settings = settings
        self._state: str = constants.BOT_STATE_STOPPED
        self._start_time: Optional[datetime] = None
        self._stop_requested: bool = False
        self._loop_count: int = 0
        self._last_scan_time: Optional[datetime] = None
        self._errors: List[str] = []

        # Track market state for alerts
        self._market_was_open: bool = False
        self._market_open_alerted: bool = False
        self._market_close_alerted: bool = False

        # ── Step 1: Database ─────────────────────────────────────────
        logger.info("Step 1/9: Initialising database...")
        try:
            from database import (
                get_database_manager,
                get_trade_repo,
                get_position_repo,
                get_signal_repo,
                get_snapshot_repo,
            )

            self._db_manager = get_database_manager()
            self._db_manager.create_tables()

            self._trade_repo = get_trade_repo()
            self._position_repo = get_position_repo()
            self._signal_repo = get_signal_repo()
            self._snapshot_repo = get_snapshot_repo()

            logger.info("  ✅ Database ready")

        except Exception as e:
            logger.error("  ❌ Database init failed: %s", e)
            self._handle_init_error("Database", e)
            raise

        # ── Step 2: Market Data ──────────────────────────────────────
        logger.info("Step 2/9: Initialising market data...")
        try:
            from data import get_market_data, get_dhan_client, get_finnhub_client

            self._dhan_client = get_dhan_client()
            self._finnhub_client = get_finnhub_client()
            self._market_data = get_market_data()

            logger.info("  ✅ Market data ready")

        except Exception as e:
            logger.error("  ❌ Market data init failed: %s", e)
            self._handle_init_error("MarketData", e)
            raise

        # ── Step 3: Brain Coordinator (ALL 3 BRAINS) ─────────────────
        logger.info("Step 3/9: Initialising brain coordinator...")
        try:
            # Try to use factory function first (recommended)
            try:
                from brains.coordinator import create_coordinator_with_all_brains
                self._coordinator = create_coordinator_with_all_brains()
                logger.info("  ✅ Brain coordinator ready (factory method)")
            except ImportError:
                # Fallback: manual brain loading
                from brains import get_coordinator
                self._coordinator = get_coordinator()
                self._load_all_brains()
                logger.info("  ✅ Brain coordinator ready (manual loading)")

            # Log loaded brains
            brain_list = self._coordinator.list_brains()
            total_weight = self._coordinator.get_total_weight()
            
            logger.info("  Loaded %d brain(s) with total weight %.2f:", 
                       len(brain_list), total_weight)
            for brain_info in brain_list:
                logger.info("    • %s (weight: %.0f%%)", 
                           brain_info['name'], 
                           brain_info['weight'] * 100)

            # Warn if weights don't sum to 1.0
            if abs(total_weight - 1.0) > 0.01:
                logger.warning("  ⚠️ Total brain weight is %.2f, expected 1.00", total_weight)

        except Exception as e:
            logger.error("  ❌ Brain init failed: %s", e)
            self._handle_init_error("Brain", e)
            raise

        # ── Step 4: Circuit Breaker ──────────────────────────────────
        logger.info("Step 4/9: Initialising circuit breaker...")
        try:
            from risk import CircuitBreaker

            self._circuit_breaker = CircuitBreaker(
                max_consecutive_losses=int(
                    getattr(settings, "MAX_CONSECUTIVE_LOSSES", 5)
                ),
                cooldown_seconds=int(
                    getattr(settings, "CIRCUIT_BREAKER_COOLDOWN", 3600)
                ),
                max_daily_loss_pct=float(
                    getattr(settings, "MAX_DAILY_LOSS", 0.03)
                ) * 100,
                initial_capital=float(
                    getattr(settings, "INITIAL_CAPITAL", 10000)
                ),
            )

            logger.info("  ✅ Circuit breaker ready")

        except Exception as e:
            logger.error("  ❌ Circuit breaker init failed: %s", e)
            self._handle_init_error("CircuitBreaker", e)
            raise

        # ── Step 5: Risk Manager ─────────────────────────────────────
        logger.info("Step 5/9: Initialising risk manager...")
        try:
            from risk import RiskManager

            self._risk_manager = RiskManager(
                settings=settings,
                trade_repository=self._trade_repo,
                position_repository=self._position_repo,
                circuit_breaker=self._circuit_breaker,
            )

            logger.info("  ✅ Risk manager ready")

        except Exception as e:
            logger.error("  ❌ Risk manager init failed: %s", e)
            self._handle_init_error("RiskManager", e)
            raise

        # ── Step 6: Order Manager ────────────────────────────────────
        logger.info("Step 6/9: Initialising order manager...")
        try:
            from core.order_manager import OrderManager

            self._order_manager = OrderManager(
                settings=settings,
                market_data=self._market_data,
                trade_repository=self._trade_repo,
                position_repository=self._position_repo,
            )

            logger.info("  ✅ Order manager ready")

        except Exception as e:
            logger.error("  ❌ Order manager init failed: %s", e)
            self._handle_init_error("OrderManager", e)
            raise

        # ── Step 7: Paper Engine ─────────────────────────────────────
        logger.info("Step 7/9: Initialising paper engine...")
        try:
            from core.paper_engine import PaperEngine

            self._paper_engine = PaperEngine(
                settings=settings,
                market_data=self._market_data,
                order_manager=self._order_manager,
                risk_manager=self._risk_manager,
                circuit_breaker=self._circuit_breaker,
                trade_repository=self._trade_repo,
                position_repository=self._position_repo,
                snapshot_repository=self._snapshot_repo,
            )

            logger.info("  ✅ Paper engine ready")

        except Exception as e:
            logger.error("  ❌ Paper engine init failed: %s", e)
            self._handle_init_error("PaperEngine", e)
            raise

        # ── Step 8: Telegram Bot ─────────────────────────────────────
        logger.info("Step 8/9: Initialising Telegram bot...")
        self._telegram_bot = None
        self._alert_manager = None

        try:
            from telegram_bot import TelegramBotHandler, AlertManager, is_telegram_configured

            if is_telegram_configured():
                token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
                chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
                admin_ids_raw = getattr(settings, "TELEGRAM_ADMIN_IDS", "")

                # Parse admin IDs
                if isinstance(admin_ids_raw, str):
                    admin_ids = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip()]
                elif isinstance(admin_ids_raw, list):
                    admin_ids = [int(x) for x in admin_ids_raw if x]
                else:
                    admin_ids = []

                self._telegram_bot = TelegramBotHandler(
                    token=token,
                    chat_id=chat_id,
                    admin_ids=admin_ids,
                    trading_bot=self,
                )

                if self._telegram_bot.setup():
                    self._alert_manager = AlertManager(self._telegram_bot)
                    logger.info("  ✅ Telegram bot ready")
                else:
                    logger.warning("  ⚠️ Telegram bot setup failed")
                    self._telegram_bot = None
            else:
                logger.info("  ⚠️ Telegram not configured (skipping)")

        except ImportError as e:
            logger.warning("  ⚠️ Telegram modules not available: %s", e)
        except Exception as e:
            logger.warning("  ⚠️ Telegram init failed: %s", e)

        # ── Step 9: Final Setup ──────────────────────────────────────
        logger.info("Step 9/9: Final setup...")

        self._mode = "PAPER" if getattr(settings, "PAPER_TRADING", True) else "LIVE"
        self._scan_interval = int(getattr(settings, "SCAN_INTERVAL", 30))
        self._instruments = getattr(settings, "OPTIONS_INSTRUMENTS", ["NIFTY", "BANKNIFTY"])

        logger.info("  ✅ Final setup complete")

        logger.info("=" * 60)
        logger.info("  🤖 TRADING BOT INITIALISED")
        logger.info("  Mode: %s", self._mode)
        logger.info("  Capital: %s", format_currency(self._paper_engine.capital))
        logger.info("  Instruments: %s", ", ".join(self._instruments))
        logger.info("  Scan Interval: %ds", self._scan_interval)
        logger.info("  Brains: %d (%s)", 
                   len(self._coordinator.list_brains()),
                   ", ".join(b['name'] for b in self._coordinator.list_brains()))
        logger.info("  Telegram: %s", "✅ Enabled" if self._telegram_bot else "❌ Disabled")
        logger.info("=" * 60)

    def _load_all_brains(self) -> None:
        """
        Load all available brains into the coordinator.
        
        This method attempts to load each brain individually,
        so if one fails, the others can still work.
        
        Brains loaded:
        - TechnicalBrain (weight: 0.40) - RSI, MACD, SMA, etc.
        - SentimentBrain (weight: 0.35) - News sentiment analysis
        - PatternBrain (weight: 0.25) - Chart pattern recognition
        """
        loaded_brains = []
        failed_brains = []
        
        # Load TechnicalBrain
        try:
            from brains.technical import TechnicalBrain
            tech_brain = TechnicalBrain()
            self._coordinator.add_brain(tech_brain)
            loaded_brains.append(f"TechnicalBrain ({tech_brain.get_weight():.0%})")
            logger.info("    ✅ TechnicalBrain loaded")
        except ImportError as e:
            failed_brains.append("TechnicalBrain")
            logger.warning("    ⚠️ TechnicalBrain not available: %s", e)
        except Exception as e:
            failed_brains.append("TechnicalBrain")
            logger.error("    ❌ TechnicalBrain failed: %s", e)
        
        # Load SentimentBrain
        try:
            from brains.sentiment import SentimentBrain
            sent_brain = SentimentBrain()
            self._coordinator.add_brain(sent_brain)
            loaded_brains.append(f"SentimentBrain ({sent_brain.get_weight():.0%})")
            logger.info("    ✅ SentimentBrain loaded")
        except ImportError as e:
            failed_brains.append("SentimentBrain")
            logger.warning("    ⚠️ SentimentBrain not available: %s", e)
        except Exception as e:
            failed_brains.append("SentimentBrain")
            logger.error("    ❌ SentimentBrain failed: %s", e)
        
        # Load PatternBrain
        try:
            from brains.pattern import PatternBrain
            pat_brain = PatternBrain()
            self._coordinator.add_brain(pat_brain)
            loaded_brains.append(f"PatternBrain ({pat_brain.get_weight():.0%})")
            logger.info("    ✅ PatternBrain loaded")
        except ImportError as e:
            failed_brains.append("PatternBrain")
            logger.warning("    ⚠️ PatternBrain not available: %s", e)
        except Exception as e:
            failed_brains.append("PatternBrain")
            logger.error("    ❌ PatternBrain failed: %s", e)
        
        # Summary
        if loaded_brains:
            logger.info("  Loaded brains: %s", ", ".join(loaded_brains))
        
        if failed_brains:
            logger.warning("  Failed brains: %s", ", ".join(failed_brains))
        
        if not loaded_brains:
            logger.error("  ❌ No brains loaded! Bot will return HOLD for all signals.")

    def _handle_init_error(self, component: str, error: Exception) -> None:
        """Record initialisation error."""
        self._errors.append(f"{component}: {str(error)}")
        self._state = constants.BOT_STATE_ERROR

    # ================================================================ #
    #  PROPERTIES                                                       #
    # ================================================================ #

    @property
    def state(self) -> str:
        """Current bot state: STOPPED, RUNNING, PAUSED, ERROR."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Whether the bot is currently running."""
        return self._state == constants.BOT_STATE_RUNNING

    @property
    def is_paused(self) -> bool:
        """Whether the bot is paused."""
        return self._state == constants.BOT_STATE_PAUSED

    @property
    def mode(self) -> str:
        """Trading mode: PAPER or LIVE."""
        return self._mode

    @property
    def uptime(self) -> Optional[timedelta]:
        """Time since bot started, or None if not running."""
        if self._start_time is None:
            return None
        return get_ist_now() - self._start_time

    @property
    def coordinator(self):
        """Access to the brain coordinator for external queries."""
        return self._coordinator

    # ================================================================ #
    #  LIFECYCLE CONTROL                                                #
    # ================================================================ #

    def start(self) -> None:
        """
        Start the trading bot.

        This method blocks and runs forever until stop() is called
        or a KeyboardInterrupt is received.

        Also starts Telegram polling in a separate thread.
        """
        if self._state == constants.BOT_STATE_RUNNING:
            logger.warning("Bot is already running")
            return

        self._state = constants.BOT_STATE_RUNNING
        self._start_time = get_ist_now()
        self._stop_requested = False
        self._paper_engine.state = constants.BOT_STATE_RUNNING

        # Reset daily alert flags
        self._market_open_alerted = False
        self._market_close_alerted = False

        logger.info("")
        logger.info("🚀" + "=" * 58)
        logger.info("  BOT STARTED")
        logger.info("  Mode: %s", self._mode)
        logger.info("  Time: %s", self._start_time.strftime("%Y-%m-%d %H:%M:%S IST"))
        logger.info("  Capital: %s", format_currency(self._paper_engine.capital))
        logger.info("  Brains: %s", ", ".join(b['name'] for b in self._coordinator.list_brains()))
        logger.info("=" * 60)
        logger.info("")

        # Start Telegram polling in separate thread
        if self._telegram_bot:
            try:
                self._telegram_bot.start_polling()
                logger.info("📱 Telegram polling started")
            except Exception as e:
                logger.error("Failed to start Telegram polling: %s", e)

        # Send bot started alert
        if self._alert_manager:
            try:
                self._alert_manager.send_bot_started()
            except Exception as e:
                logger.error("Failed to send bot started alert: %s", e)

        try:
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("\n👋 Interrupted by user")
            self.stop()
        except Exception as e:
            logger.critical("💥 FATAL ERROR in main loop: %s", e, exc_info=True)
            self._state = constants.BOT_STATE_ERROR

            # Send error alert
            if self._alert_manager:
                try:
                    self._alert_manager.send_error_alert(
                        "Fatal error in main loop",
                        str(e)[:200]
                    )
                except Exception:
                    pass

            self.stop()
            raise

    def stop(self) -> None:
        """
        Stop the trading bot gracefully.

        This will:
        1. Close all open positions
        2. Save daily snapshot
        3. Stop Telegram polling
        4. Update state to STOPPED
        """
        if self._state == constants.BOT_STATE_STOPPED:
            logger.info("Bot is already stopped")
            return

        logger.info("")
        logger.info("🛑" + "=" * 58)
        logger.info("  STOPPING BOT...")
        logger.info("=" * 60)

        self._stop_requested = True

        # Close all positions if any
        try:
            if self._paper_engine.has_open_positions():
                logger.info("Closing all open positions...")
                closed = self._paper_engine.close_all_positions("BOT_STOP")
                logger.info("  Closed %d positions", len(closed))

                # Send alerts for closed positions
                if self._alert_manager:
                    for trade in closed:
                        try:
                            self._alert_manager.send_trade_closed(trade)
                        except Exception:
                            pass
        except Exception as e:
            logger.error("Error closing positions: %s", e)

        # Save daily snapshot
        try:
            self._paper_engine.save_daily_snapshot()
        except Exception as e:
            logger.error("Error saving snapshot: %s", e)

        # Stop Telegram polling
        if self._telegram_bot:
            try:
                self._telegram_bot.stop_polling()
                logger.info("📱 Telegram polling stopped")
            except Exception as e:
                logger.error("Error stopping Telegram: %s", e)

        # Send bot stopped alert
        if self._alert_manager:
            try:
                self._alert_manager.send_bot_stopped("Manual stop")
            except Exception as e:
                logger.error("Failed to send bot stopped alert: %s", e)

        # Update state
        self._state = constants.BOT_STATE_STOPPED
        self._paper_engine.state = constants.BOT_STATE_STOPPED

        # Calculate uptime
        uptime_str = "N/A"
        if self._start_time:
            uptime = get_ist_now() - self._start_time
            uptime_str = format_duration(uptime.total_seconds())

        logger.info("")
        logger.info("=" * 60)
        logger.info("  BOT STOPPED")
        logger.info("  Uptime: %s", uptime_str)
        logger.info("  Loops: %d", self._loop_count)
        logger.info("  Final Capital: %s", format_currency(self._paper_engine.capital))
        logger.info("  Total P&L: %s", format_pnl(self._paper_engine.total_pnl))
        logger.info("=" * 60)
        logger.info("")

    def pause(self) -> None:
        """
        Pause the bot.

        While paused, the bot monitors existing positions but
        does not take new trades.
        """
        if self._state != constants.BOT_STATE_RUNNING:
            logger.warning("Cannot pause: bot is not running (state=%s)", self._state)
            return

        self._state = constants.BOT_STATE_PAUSED
        self._paper_engine.state = constants.BOT_STATE_PAUSED

        logger.info("⏸️  Bot PAUSED — monitoring positions only")

    def resume(self) -> None:
        """
        Resume the bot from paused state.
        """
        if self._state != constants.BOT_STATE_PAUSED:
            logger.warning("Cannot resume: bot is not paused (state=%s)", self._state)
            return

        self._state = constants.BOT_STATE_RUNNING
        self._paper_engine.state = constants.BOT_STATE_RUNNING

        logger.info("▶️  Bot RESUMED — trading active")

        # Reset circuit breaker if needed
        if self._circuit_breaker.triggered:
            self._circuit_breaker.force_reset()
            if self._alert_manager:
                try:
                    self._alert_manager.send_circuit_breaker_reset()
                except Exception:
                    pass
        # ================================================================ #
    #  MAIN TRADING LOOP                                                #
    # ================================================================ #

    def _main_loop(self) -> None:
        """
        The main trading loop — runs FOREVER until stopped.

        This is the heart of the bot. Every SCAN_INTERVAL seconds:
        1. Run pre-checks (trading day, market open, circuit breaker)
        2. Scan instruments and execute trades
        3. Monitor and update existing positions
        4. Send Telegram alerts for events
        
        Brain Analysis:
        - Each instrument is analyzed by all 3 brains
        - Technical (40%), Sentiment (35%), Pattern (25%)
        - Weighted voting produces consensus signal
        """
        logger.info("📍 Entering main loop (interval: %ds)", self._scan_interval)
        
        # Log brain info at loop start
        brain_list = self._coordinator.list_brains()
        logger.info("🧠 Active brains: %s", 
                   ", ".join(f"{b['name']}({b['weight']:.0%})" for b in brain_list))

        while self._state != constants.BOT_STATE_STOPPED and not self._stop_requested:
            self._loop_count += 1
            loop_start = get_ist_now()
            self._last_scan_time = loop_start

            try:
                # ── Handle PAUSED state ──────────────────────────────
                if self._state == constants.BOT_STATE_PAUSED:
                    logger.debug("Bot paused — sleeping %ds", self._scan_interval)

                    # Still monitor positions while paused
                    try:
                        closed = self._paper_engine.update_positions()
                        for trade in closed:
                            self._log_trade_closed(trade)
                            if self._alert_manager:
                                try:
                                    self._alert_manager.send_trade_closed(trade)
                                except Exception:
                                    pass
                    except Exception as e:
                        logger.error("Error monitoring positions while paused: %s", e)

                    time.sleep(self._scan_interval)
                    continue

                # ── Pre-check 1: Trading Day ─────────────────────────
                if not is_trading_day():
                    logger.info("📅 Not a trading day — sleeping 5 min")
                    time.sleep(300)
                    continue

                # ── Pre-check 2: Market Hours ────────────────────────
                if not is_market_open():
                    self._handle_market_closed()
                    time.sleep(60)
                    continue
                else:
                    # Market just opened — send alert
                    if not self._market_open_alerted:
                        self._handle_market_opened()

                # ── Pre-check 3: Position Close Window ───────────────
                if should_close_all_positions():
                    self._handle_close_window()
                    time.sleep(self._scan_interval)
                    continue

                # ── Pre-check 4: Circuit Breaker ─────────────────────
                if not self._circuit_breaker.is_safe():
                    self._handle_circuit_breaker()
                    time.sleep(self._scan_interval)
                    continue

                # ════════════════════════════════════════════════════
                # MAIN TRADING LOGIC
                # ════════════════════════════════════════════════════

                # ── Step A: Scan each instrument ─────────────────────
                for symbol in self._instruments:
                    try:
                        self._process_instrument(symbol)
                    except Exception as e:
                        logger.error(
                            "Error processing %s: %s",
                            symbol, e
                        )
                        continue

                # ── Step B: Update existing positions ────────────────
                try:
                    closed_trades = self._paper_engine.update_positions()

                    for trade in closed_trades:
                        self._log_trade_closed(trade)

                        # Send Telegram alert
                        if self._alert_manager:
                            try:
                                self._alert_manager.send_trade_closed(trade)
                            except Exception as e:
                                logger.error("Failed to send trade closed alert: %s", e)

                except Exception as e:
                    logger.error("Error updating positions: %s", e)

                # ── Step C: Log loop stats (every 10 loops) ──────────
                if self._loop_count % 10 == 0:
                    self._log_loop_stats()

                # ── Step D: Sleep until next scan ────────────────────
                elapsed = (get_ist_now() - loop_start).total_seconds()
                sleep_time = max(1, self._scan_interval - elapsed)

                logger.debug(
                    "Loop %d complete (%.1fs) — sleeping %.1fs",
                    self._loop_count, elapsed, sleep_time
                )

                time.sleep(sleep_time)

            except KeyboardInterrupt:
                raise

            except Exception as e:
                logger.error(
                    "❌ Error in main loop (iteration %d): %s",
                    self._loop_count, e,
                    exc_info=True
                )

                # Send error alert (rate limited in AlertManager)
                if self._alert_manager:
                    try:
                        self._alert_manager.send_error_alert(
                            "Error in main loop",
                            str(e)[:200]
                        )
                    except Exception:
                        pass

                # Sleep and continue — don't crash the bot
                time.sleep(self._scan_interval)

    # ================================================================ #
    #  INSTRUMENT PROCESSING                                            #
    # ================================================================ #

    def _process_instrument(self, symbol: str) -> None:
        """
        Process a single instrument: analyze and potentially trade.

        This runs all 3 brains through the coordinator:
        - TechnicalBrain: RSI, MACD, SMA, EMA, Bollinger, Volume
        - SentimentBrain: News analysis, keyword scoring
        - PatternBrain: Support/Resistance, trends, candlesticks

        Parameters
        ----------
        symbol : str
            The instrument symbol (e.g., 'NIFTY', 'BANKNIFTY').
        """
        # ── Step 1: Run brain analysis ───────────────────────────────
        try:
            consensus = self._coordinator.analyze_symbol(symbol, self._market_data)
        except Exception as e:
            logger.error("Brain error for %s: %s", symbol, e)
            return

        action = consensus.get("action", constants.SIGNAL_HOLD)
        confidence = consensus.get("confidence", 0.0)
        brain_count = consensus.get("brain_count", 0)

        # Enhanced logging with brain details
        logger.info(
            "🧠 %s: %s (%.0f%%) [%d brains] | %s",
            symbol,
            action,
            confidence * 100,
            brain_count,
            consensus.get("reasoning", "")[:60],
        )

        # Log individual brain signals if debug enabled
        if logger.isEnabledFor(logging.DEBUG):
            brain_signals = consensus.get("brain_signals", [])
            for sig in brain_signals:
                brain_name = sig.get("brain", "?")
                brain_action = sig.get("action", "?")
                brain_conf = sig.get("confidence", 0)
                logger.debug(
                    "  └─ %s: %s (%.0f%%)",
                    brain_name, brain_action, brain_conf * 100
                )

        # ── Step 2: Skip if HOLD ─────────────────────────────────────
        if action == constants.SIGNAL_HOLD:
            return

        # ── Step 3: Check if we can take new trades ──────────────────
        if not can_take_new_trades():
            logger.debug(
                "%s: %s signal but past trade cutoff",
                symbol, action
            )
            return

        # ── Step 4: Execute trade through paper engine ───────────────
        try:
            trade = self._paper_engine.execute_trade(consensus)

            if trade:
                self._log_trade_opened(trade)

                # Send Telegram alert
                if self._alert_manager:
                    try:
                        self._alert_manager.send_trade_opened(trade)
                    except Exception as e:
                        logger.error("Failed to send trade opened alert: %s", e)

        except Exception as e:
            logger.error("Trade execution error for %s: %s", symbol, e)

    # ================================================================ #
    #  MARKET STATE HANDLERS                                            #
    # ================================================================ #

    def _handle_market_opened(self) -> None:
        """Handle when market opens."""
        self._market_open_alerted = True
        self._market_close_alerted = False
        self._market_was_open = True

        logger.info("🔔 Market OPEN — starting scans")
        
        # Log brain status at market open
        brain_list = self._coordinator.list_brains()
        logger.info("🧠 Brains ready: %s", 
                   ", ".join(f"{b['name']}" for b in brain_list))

        # Send market open alert
        if self._alert_manager:
            try:
                self._alert_manager.send_market_open()
            except Exception as e:
                logger.error("Failed to send market open alert: %s", e)

        # Reset paper engine for new day if needed
        now = get_ist_now()
        if self._paper_engine._today != now.date():
            self._paper_engine.start_new_day()

    def _handle_market_closed(self) -> None:
        """Handle when market is closed."""
        now = get_ist_now()
        market_open_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)

        if now.time() < market_open_time.time():
            # Before market open
            is_open, time_msg, _ = get_time_to_market_open()
            logger.info("⏰ Market closed — %s", time_msg)

            # Check if new day
            if self._paper_engine._today != now.date():
                self._paper_engine.start_new_day()
                self._market_open_alerted = False
                self._market_close_alerted = False

        elif now.time() > market_close_time.time():
            # After market close
            if not self._market_close_alerted and self._market_was_open:
                self._market_close_alerted = True
                logger.info("🌙 Market closed for the day")

                # Save snapshot and send report
                try:
                    self._paper_engine.save_daily_snapshot()
                    summary = self._paper_engine.get_daily_summary()

                    if self._alert_manager:
                        try:
                            self._alert_manager.send_market_close(summary)
                            self._alert_manager.send_daily_report(summary)
                        except Exception as e:
                            logger.error("Failed to send market close alert: %s", e)

                except Exception as e:
                    logger.error("Error saving snapshot: %s", e)

    def _handle_close_window(self) -> None:
        """Handle the position close window (near market close)."""
        logger.info("⏰ Close window active — closing all positions")

        try:
            closed = self._paper_engine.close_all_positions("TIME")

            for trade in closed:
                self._log_trade_closed(trade)

                # Send alert
                if self._alert_manager:
                    try:
                        self._alert_manager.send_trade_closed(trade)
                    except Exception:
                        pass

            if closed:
                logger.info(
                    "📊 Closed %d positions | Daily P&L: %s",
                    len(closed),
                    format_pnl(self._paper_engine.daily_pnl),
                )

        except Exception as e:
            logger.error("Error closing positions: %s", e)

    def _handle_circuit_breaker(self) -> None:
        """Handle when circuit breaker is triggered."""
        status = self._circuit_breaker.get_status()

        logger.warning(
            "🚨 Circuit breaker ACTIVE: %s | "
            "Cooldown: %ds | Consecutive losses: %d",
            status.get("reason", "Unknown"),
            status.get("cooldown_remaining_seconds", 0),
            status.get("consecutive_losses", 0),
        )

        # Send alert (only once per trigger)
        if self._alert_manager and not hasattr(self, '_cb_alert_sent'):
            try:
                self._alert_manager.send_circuit_breaker_alert(
                    status.get("reason", "Unknown"),
                    status
                )
                self._cb_alert_sent = True
            except Exception as e:
                logger.error("Failed to send circuit breaker alert: %s", e)

        # Reset flag when circuit breaker resets
        if not self._circuit_breaker.triggered:
            self._cb_alert_sent = False

    # ================================================================ #
    #  LOGGING HELPERS                                                  #
    # ================================================================ #

    def _log_trade_opened(self, trade) -> None:
        """Log a newly opened trade."""
        instrument = getattr(trade, "instrument", "?")
        entry_price = float(getattr(trade, "entry_price", 0))
        stop_loss = float(getattr(trade, "stop_loss", 0))
        take_profit = float(getattr(trade, "take_profit", 0))
        quantity = int(getattr(trade, "quantity", 0))

        logger.info(
            "🎯 TRADE OPENED | %s @ ₹%.2f | Qty: %d | "
            "SL: ₹%.2f | TP: ₹%.2f",
            instrument,
            entry_price,
            quantity,
            stop_loss,
            take_profit,
        )

    def _log_trade_closed(self, trade) -> None:
        """Log a closed trade."""
        instrument = getattr(trade, "instrument", "?")
        exit_reason = getattr(trade, "exit_reason", "?")
        pnl = float(getattr(trade, "pnl", 0))

        emoji = "🟢" if pnl >= 0 else "🔴"

        logger.info(
            "%s TRADE CLOSED | %s | %s | P&L: %s",
            emoji,
            instrument,
            exit_reason,
            format_pnl(pnl),
        )

    def _log_loop_stats(self) -> None:
        """Log periodic loop statistics."""
        portfolio = self._paper_engine.get_portfolio()
        brain_count = len(self._coordinator.list_brains())

        logger.info(
            "📊 Loop %d | Capital: %s | Daily P&L: %s | "
            "Positions: %d | Trades: %d | Brains: %d",
            self._loop_count,
            format_currency(portfolio["capital"]["current"]),
            format_pnl(portfolio["pnl"]["daily"]),
            portfolio["positions"]["open_count"],
            portfolio["trades"]["today"],
            brain_count,
        )

    # ================================================================ #
    #  STATUS & REPORTING                                               #
    # ================================================================ #

    def get_status(self) -> dict:
        """
        Get comprehensive bot status.

        Returns
        -------
        dict
            Complete status snapshot including brain information.
        """
        now = get_ist_now()

        uptime_seconds = 0
        uptime_str = "N/A"
        if self._start_time:
            uptime_delta = now - self._start_time
            uptime_seconds = uptime_delta.total_seconds()
            uptime_str = format_duration(uptime_seconds)

        portfolio = self._paper_engine.get_portfolio()
        cb_status = self._circuit_breaker.get_status()
        
        # Get brain information
        brain_list = self._coordinator.list_brains()
        brain_info = {
            "count": len(brain_list),
            "total_weight": self._coordinator.get_total_weight(),
            "brains": [
                {
                    "name": b["name"],
                    "weight": b["weight"],
                    "status": b.get("status", "active"),
                }
                for b in brain_list
            ],
        }

        return {
            "timestamp": now.isoformat(),
            "state": self._state,
            "mode": self._mode,
            "uptime": uptime_str,
            "uptime_seconds": int(uptime_seconds),
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "loop_count": self._loop_count,
            "last_scan": self._last_scan_time.isoformat() if self._last_scan_time else None,
            "capital": {
                "initial": portfolio["capital"]["initial"],
                "current": portfolio["capital"]["current"],
                "available": portfolio["capital"]["available"],
            },
            "pnl": {
                "daily": portfolio["pnl"]["daily"],
                "total": portfolio["pnl"]["total"],
            },
            "positions": {
                "open": portfolio["positions"]["open_count"],
                "max": int(getattr(self._settings, "MAX_OPEN_POSITIONS", 4)),
            },
            "trades": {
                "today": portfolio["trades"]["today"],
                "max": int(getattr(self._settings, "MAX_TRADES_PER_DAY", 20)),
                "wins": portfolio["trades"]["wins"],
                "losses": portfolio["trades"]["losses"],
                "win_rate": portfolio["trades"]["win_rate"],
            },
            "circuit_breaker": {
                "triggered": cb_status.get("triggered", False),
                "reason": cb_status.get("reason", ""),
                "consecutive_losses": cb_status.get("consecutive_losses", 0),
            },
            "brains": brain_info,
            "market": {
                "status": get_market_status(),
                "is_open": is_market_open(),
                "is_trading_day": is_trading_day(),
                "can_trade": can_take_new_trades(),
            },
            "telegram": {
                "enabled": self._telegram_bot is not None,
                "running": self._telegram_bot.is_running if self._telegram_bot else False,
            },
            "next_scan_in": self._scan_interval,
            "errors": self._errors[-5:] if self._errors else [],
        }

    def get_portfolio(self) -> dict:
        """Proxy to paper engine portfolio."""
        return self._paper_engine.get_portfolio()

    def get_daily_summary(self) -> dict:
        """Proxy to paper engine daily summary."""
        return self._paper_engine.get_daily_summary()

    def get_brain_status(self) -> dict:
        """
        Get detailed brain status and performance.
        
        Returns
        -------
        dict
            Brain information including:
            - List of active brains with weights
            - Total weight
            - Performance stats for each brain
            - Coordinator stats
        """
        brain_list = self._coordinator.list_brains()
        brain_performance = self._coordinator.get_brain_performance()
        coordinator_stats = self._coordinator.get_stats()
        
        return {
            "brains": [
                {
                    "name": b["name"],
                    "weight": b["weight"],
                    "weight_percent": f"{b['weight'] * 100:.0f}%",
                    "status": b.get("status", "active"),
                    "stats": b.get("stats", {}),
                }
                for b in brain_list
            ],
            "total_weight": coordinator_stats.get("total_weight", 0),
            "brain_count": coordinator_stats.get("brain_count", 0),
            "analysis_count": coordinator_stats.get("analysis_count", 0),
            "last_analysis": coordinator_stats.get("last_analysis"),
            "performance": brain_performance,
        }

    # ================================================================ #
    #  EMERGENCY CONTROLS                                               #
    # ================================================================ #

    def emergency_stop(self, reason: str = "Emergency") -> None:
        """
        Emergency stop — immediately halt all trading.

        This will:
        1. Trigger the circuit breaker
        2. Close all positions
        3. Send alerts
        4. Stop the bot

        Parameters
        ----------
        reason : str
            Reason for emergency stop (for logging).
        """
        logger.critical("🆘 EMERGENCY STOP: %s", reason)

        # Trigger circuit breaker
        try:
            self._circuit_breaker.manual_trigger(f"Emergency: {reason}")
        except Exception as e:
            logger.error("Error triggering circuit breaker: %s", e)

        # Send circuit breaker alert
        if self._alert_manager:
            try:
                self._alert_manager.send_circuit_breaker_alert(
                    f"Emergency: {reason}",
                    self._circuit_breaker.get_status()
                )
            except Exception as e:
                logger.error("Error sending circuit breaker alert: %s", e)

        # Close all positions
        try:
            closed = self._paper_engine.close_all_positions("EMERGENCY")
            logger.info("Emergency closed %d positions", len(closed))

            for trade in closed:
                if self._alert_manager:
                    try:
                        self._alert_manager.send_trade_closed(trade)
                    except Exception:
                        pass
        except Exception as e:
            logger.error("Error closing positions: %s", e)

        # Stop the bot
        self.stop()

    def force_close_all(self) -> List[Any]:
        """
        Force close all positions immediately.

        Returns
        -------
        list
            List of closed trades.
        """
        logger.warning("⚠️  Force closing all positions")
        closed = self._paper_engine.close_all_positions("MANUAL")

        # Send alerts
        for trade in closed:
            if self._alert_manager:
                try:
                    self._alert_manager.send_trade_closed(trade)
                except Exception:
                    pass

        return closed

    # ================================================================ #
    #  DUNDER METHODS                                                   #
    # ================================================================ #

    def __repr__(self) -> str:
        brain_count = len(self._coordinator.list_brains()) if self._coordinator else 0
        return (
            f"TradingBot("
            f"state={self._state}, "
            f"mode={self._mode}, "
            f"capital={format_currency(self._paper_engine.capital)}, "
            f"positions={self._paper_engine.get_open_position_count()}, "
            f"brains={brain_count}, "
            f"telegram={'✅' if self._telegram_bot else '❌'})"
        )


# ====================================================================== #
#  Standalone test / demo                                                  #
# ====================================================================== #

if __name__ == "__main__":
    import sys
    import os

    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    print("\n" + "=" * 65)
    print("  TRADING BOT - Standalone Test")
    print("=" * 65)

    print("\n  This test initialises the bot but does NOT start the loop.")
    print("  To run the actual trading loop, use: python main.py")
    print()

    try:
        # ── Test 1: Initialisation ───────────────────────────────────
        print("-" * 65)
        print("  TEST 1: Bot Initialisation")
        print("-" * 65)

        bot = TradingBot()

        print(f"\n  {bot}")
        print(f"  State: {bot.state}")
        print(f"  Mode: {bot.mode}")

        # ── Test 2: Status ───────────────────────────────────────────
        print("\n" + "-" * 65)
        print("  TEST 2: Get Status")
        print("-" * 65)

        status = bot.get_status()

        print(f"\n  State: {status['state']}")
        print(f"  Mode: {status['mode']}")
        print(f"  Capital: {format_currency(status['capital']['current'])}")
        print(f"  Market: {status['market']['status']}")
        print(f"  Telegram: {'✅ Enabled' if status['telegram']['enabled'] else '❌ Disabled'}")
        
        # Brain info
        print(f"\n  Brains ({status['brains']['count']}):")
        for brain in status['brains']['brains']:
            print(f"    • {brain['name']}: {brain['weight']:.0%}")
        print(f"  Total Weight: {status['brains']['total_weight']:.0%}")

        # ── Test 3: Portfolio ────────────────────────────────────────
        print("\n" + "-" * 65)
        print("  TEST 3: Get Portfolio")
        print("-" * 65)

        portfolio = bot.get_portfolio()

        print(f"\n  Initial: {format_currency(portfolio['capital']['initial'])}")
        print(f"  Current: {format_currency(portfolio['capital']['current'])}")
        print(f"  Available: {format_currency(portfolio['capital']['available'])}")
        print(f"  Open Positions: {portfolio['positions']['open_count']}")

        # ── Test 4: Brain Status ─────────────────────────────────────
        print("\n" + "-" * 65)
        print("  TEST 4: Get Brain Status")
        print("-" * 65)

        brain_status = bot.get_brain_status()

        print(f"\n  Brain Count: {brain_status['brain_count']}")
        print(f"  Total Weight: {brain_status['total_weight']:.0%}")
        print(f"  Analysis Count: {brain_status['analysis_count']}")
        
        print("\n  Brain Details:")
        for brain in brain_status['brains']:
            print(f"    • {brain['name']}")
            print(f"      Weight: {brain['weight_percent']}")
            print(f"      Status: {brain['status']}")

        # ── Test 5: Coordinator Access ───────────────────────────────
        print("\n" + "-" * 65)
        print("  TEST 5: Coordinator Access")
        print("-" * 65)

        coordinator = bot.coordinator
        print(f"\n  Coordinator: {coordinator}")
        print(f"  Registered brains: {list(coordinator._brains.keys())}")

        # ── Note ─────────────────────────────────────────────────────
        print("\n" + "-" * 65)
        print("  NOTE: To test the actual trading loop:")
        print("-" * 65)
        print("\n  Run: python main.py")
        print("\n  The bot will:")
        print("    - Start Telegram polling (if configured)")
        print("    - Wait for market to open")
        print("    - Scan NIFTY and BANKNIFTY every 30 seconds")
        print("    - Run 3 brains: Technical (40%), Sentiment (35%), Pattern (25%)")
        print("    - Execute paper trades based on consensus signals")
        print("    - Send Telegram alerts for trades")
        print("    - Monitor positions for SL/TP/trailing exits")
        print("    - Close all positions before market close")
        print("    - Send daily report at market close")

        print("\n" + "=" * 65)
        print("  ✅ All TradingBot tests completed!")
        print("=" * 65 + "\n")

    except Exception as e:
        print(f"\n  ❌ Error: {e}")
        import traceback
        traceback.print_exc()            