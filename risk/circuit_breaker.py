"""
Circuit Breaker - Emergency Shutdown System
=============================================

Monitors trading activity and automatically halts all trading when
dangerous patterns are detected. Acts as the last line of defense
before catastrophic losses occur.

Trigger Conditions
------------------
1. **Consecutive Losses** — X losing trades in a row.
   Default: 5. Rationale: strategy may be wrong for current market.

2. **Daily Loss Limit** — Net daily P&L exceeds allowed threshold.
   Default: 3 % of initial capital. Rationale: preserve capital for tomorrow.

Manual Control (Telegram integration — Phase 7)
------------------------------------------------
- ``/kill``   → manual_trigger()  — halt trading immediately
- ``/resume`` → force_reset()     — resume trading (admin override)

Cooldown Behaviour
------------------
After triggering, a cooldown period begins (default 3 600 s = 1 h).
Once the cooldown expires, ``is_safe()`` auto-resets the breaker:

- Consecutive-loss trigger  → resets loss counter (fresh start)
- Daily-loss trigger        → preserves daily P&L (risk manager also guards)
- Manual trigger            → requires cooldown expiry or force_reset()

Day Boundary
------------
Call ``start_new_day()`` at market open each morning:

- Resets daily P&L and trade counts to zero
- Clears trigger ONLY if it was daily-loss based
- Preserves consecutive-loss count (carries across days)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from utils.helpers import get_ist_now

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """
    Emergency shutdown system for the options trading bot.

    Parameters
    ----------
    max_consecutive_losses : int
        Number of back-to-back losing trades before triggering.
    cooldown_seconds : int
        Seconds to wait after triggering before auto-reset.
    max_daily_loss_pct : float
        Maximum daily loss as a percentage of *initial_capital*
        (e.g. 3.0 means 3 %).
    initial_capital : float
        Starting capital — used to compute the absolute daily loss limit.

    Raises
    ------
    ValueError
        If any parameter is out of its valid range.

    Examples
    --------
    >>> cb = CircuitBreaker(5, 3600, 3.0, 10_000.0)
    >>> cb.is_safe()
    True
    >>> cb.record_trade_result(-50.0)   # 1st loss
    True
    >>> cb.record_trade_result(120.0)   # win — streak reset
    True
    """

    # ── Category constants (used by start_new_day to decide what to clear) ──
    REASON_CONSECUTIVE_LOSSES = "consecutive_losses"
    REASON_DAILY_LOSS = "daily_loss_limit"
    REASON_MANUAL = "manual"

    # ------------------------------------------------------------------ #
    #  Initialisation                                                      #
    # ------------------------------------------------------------------ #

    def __init__(
        self,
        max_consecutive_losses: int,
        cooldown_seconds: int,
        max_daily_loss_pct: float,
        initial_capital: float,
    ) -> None:
        # ── Validate inputs ──────────────────────────────────────────
        if max_consecutive_losses < 1:
            raise ValueError(
                f"max_consecutive_losses must be >= 1, got {max_consecutive_losses}"
            )
        if cooldown_seconds < 0:
            raise ValueError(
                f"cooldown_seconds must be >= 0, got {cooldown_seconds}"
            )
        if max_daily_loss_pct <= 0.0:
            raise ValueError(
                f"max_daily_loss_pct must be > 0, got {max_daily_loss_pct}"
            )
        if initial_capital <= 0.0:
            raise ValueError(
                f"initial_capital must be > 0, got {initial_capital}"
            )

        # ── Configuration (immutable after init) ─────────────────────
        self._max_consecutive_losses: int = max_consecutive_losses
        self._cooldown_seconds: int = cooldown_seconds
        self._max_daily_loss_pct: float = max_daily_loss_pct
        self._initial_capital: float = initial_capital
        self._daily_loss_limit: float = initial_capital * (max_daily_loss_pct / 100.0)

        # ── Mutable state ────────────────────────────────────────────
        self._triggered: bool = False
        self._trigger_reason: str = ""
        self._trigger_category: str = ""
        self._triggered_at: Optional[datetime] = None
        self._cooldown_until: Optional[datetime] = None

        self._consecutive_losses: int = 0
        self._daily_pnl: float = 0.0
        self._total_trades_today: int = 0
        self._winning_trades_today: int = 0
        self._losing_trades_today: int = 0

        logger.info(
            "Circuit breaker initialised | "
            "Max consecutive losses: %d | Cooldown: %d s | "
            "Daily loss limit: ₹%.2f (%.1f%% of ₹%.2f)",
            max_consecutive_losses,
            cooldown_seconds,
            self._daily_loss_limit,
            max_daily_loss_pct,
            initial_capital,
        )

    # ------------------------------------------------------------------ #
    #  Read-only properties                                                #
    # ------------------------------------------------------------------ #

    @property
    def triggered(self) -> bool:
        """Whether the circuit breaker is currently active."""
        return self._triggered

    @property
    def trigger_reason(self) -> str:
        """Human-readable reason for the current (or last) trigger."""
        return self._trigger_reason

    @property
    def triggered_at(self) -> Optional[datetime]:
        """IST timestamp when the breaker was last triggered."""
        return self._triggered_at

    @property
    def cooldown_until(self) -> Optional[datetime]:
        """IST timestamp when the cooldown period expires."""
        return self._cooldown_until

    @property
    def consecutive_losses(self) -> int:
        """Running count of consecutive losing trades."""
        return self._consecutive_losses

    @property
    def daily_pnl(self) -> float:
        """Net profit / loss for the current trading day."""
        return self._daily_pnl

    # ------------------------------------------------------------------ #
    #  Core — record, check, trigger                                       #
    # ------------------------------------------------------------------ #

    def record_trade_result(self, pnl: float) -> bool:
        """
        Record the P&L of a completed trade and re-evaluate triggers.

        Parameters
        ----------
        pnl : float
            Realised profit (positive) or loss (negative) of the trade.

        Returns
        -------
        bool
            ``True`` if trading is still safe after this trade,
            ``False`` if the circuit breaker has been triggered.
        """
        self._total_trades_today += 1
        self._daily_pnl += pnl

        if pnl < 0.0:
            self._consecutive_losses += 1
            self._losing_trades_today += 1
            logger.warning(
                "📉 Loss recorded: ₹%.2f | "
                "Consecutive losses: %d / %d | "
                "Daily P&L: ₹%.2f (limit: -₹%.2f)",
                pnl,
                self._consecutive_losses,
                self._max_consecutive_losses,
                self._daily_pnl,
                self._daily_loss_limit,
            )
        else:
            if self._consecutive_losses > 0:
                logger.info(
                    "📈 Win recorded: ₹%.2f | "
                    "Consecutive-loss streak of %d broken | "
                    "Daily P&L: ₹%.2f",
                    pnl,
                    self._consecutive_losses,
                    self._daily_pnl,
                )
            else:
                logger.info(
                    "📈 Win recorded: ₹%.2f | Daily P&L: ₹%.2f",
                    pnl,
                    self._daily_pnl,
                )
            self._consecutive_losses = 0
            self._winning_trades_today += 1

        return self.check_triggers()

    def check_triggers(self) -> bool:
        """
        Evaluate every trigger condition.

        Called automatically by :meth:`record_trade_result`. Can also be
        called independently for a point-in-time safety check.

        Returns
        -------
        bool
            ``True`` → safe to continue trading.
            ``False`` → circuit breaker has fired (or was already active).
        """
        if self._triggered:
            return False

        # Trigger 1 — consecutive losses
        if self._consecutive_losses >= self._max_consecutive_losses:
            self.trigger(
                reason=(
                    f"{self._consecutive_losses} consecutive losses "
                    f"(limit: {self._max_consecutive_losses})"
                ),
                category=self.REASON_CONSECUTIVE_LOSSES,
            )
            return False

        # Trigger 2 — daily loss limit
        if self._daily_pnl <= -self._daily_loss_limit:
            self.trigger(
                reason=(
                    f"Daily loss ₹{abs(self._daily_pnl):.2f} exceeded "
                    f"limit ₹{self._daily_loss_limit:.2f}"
                ),
                category=self.REASON_DAILY_LOSS,
            )
            return False

        return True

    def trigger(self, reason: str, category: str = "") -> None:
        """
        Activate the circuit breaker.

        Parameters
        ----------
        reason : str
            Human-readable explanation.
        category : str, optional
            Programmatic category (``REASON_CONSECUTIVE_LOSSES``,
            ``REASON_DAILY_LOSS``, or ``REASON_MANUAL``).
            Defaults to ``REASON_MANUAL`` when omitted.
        """
        now = get_ist_now()
        self._triggered = True
        self._trigger_reason = reason
        self._trigger_category = category or self.REASON_MANUAL
        self._triggered_at = now
        self._cooldown_until = now + timedelta(seconds=self._cooldown_seconds)

        logger.critical(
            "🚨 CIRCUIT BREAKER TRIGGERED 🚨\n"
            "    Reason     : %s\n"
            "    Category   : %s\n"
            "    Time       : %s\n"
            "    Cooldown   : %d s (until %s)\n"
            "    Daily P&L  : ₹%.2f\n"
            "    Consec. L  : %d",
            reason,
            self._trigger_category,
            now.strftime("%H:%M:%S %Z"),
            self._cooldown_seconds,
            self._cooldown_until.strftime("%H:%M:%S"),
            self._daily_pnl,
            self._consecutive_losses,
        )

    # ------------------------------------------------------------------ #
    #  Safety check + auto-reset                                           #
    # ------------------------------------------------------------------ #

    def is_safe(self) -> bool:
        """
        Can the bot place new trades right now?

        Logic
        -----
        1. Not triggered → ``True``.
        2. Triggered, cooldown expired → auto-reset, then ``True``.
        3. Triggered, cooldown active → ``False``.

        Returns
        -------
        bool
        """
        if not self._triggered:
            return True

        now = get_ist_now()
        if self._cooldown_until is not None and now >= self._cooldown_until:
            self._auto_reset()
            return True

        # Still in cooldown — log remaining time
        remaining = 0.0
        if self._cooldown_until is not None:
            remaining = max(0.0, (self._cooldown_until - now).total_seconds())
        logger.debug(
            "Circuit breaker active | %s | Cooldown remaining: %d s",
            self._trigger_reason,
            int(remaining),
        )
        return False

    def _auto_reset(self) -> None:
        """
        Internal reset called when cooldown expires.

        - Clears the triggered flag and metadata.
        - Resets ``consecutive_losses`` to 0 (fresh start after cool-off).
        - Preserves ``daily_pnl`` — the risk manager's own daily-loss
          check acts as an independent guard.
        """
        previous_reason = self._trigger_reason
        previous_category = self._trigger_category

        self._triggered = False
        self._trigger_reason = ""
        self._trigger_category = ""
        self._triggered_at = None
        self._cooldown_until = None
        self._consecutive_losses = 0          # fresh start

        logger.info(
            "✅ Circuit breaker auto-reset after cooldown | "
            "Previous: %s (%s) | Daily P&L preserved: ₹%.2f",
            previous_reason,
            previous_category,
            self._daily_pnl,
        )

    # ------------------------------------------------------------------ #
    #  Manual control (Telegram /kill  and  /resume)                       #
    # ------------------------------------------------------------------ #

    def manual_trigger(self, reason: str = "Manual emergency stop") -> None:
        """
        Immediately halt trading — intended for Telegram ``/kill``.

        Parameters
        ----------
        reason : str, optional
            Why the admin is stopping the bot.
        """
        logger.warning(
            "⚠️  Manual circuit-breaker trigger requested: %s", reason
        )
        self.trigger(reason, category=self.REASON_MANUAL)

    def reset(self) -> None:
        """
        Full reset — clears trigger **and** all counters.

        After calling this the breaker is in the same state as a
        freshly constructed instance (minus configuration).
        """
        self._triggered = False
        self._trigger_reason = ""
        self._trigger_category = ""
        self._triggered_at = None
        self._cooldown_until = None
        self._consecutive_losses = 0
        self._daily_pnl = 0.0
        self._total_trades_today = 0
        self._winning_trades_today = 0
        self._losing_trades_today = 0

        logger.info("🔄 Circuit breaker fully reset — all state cleared")

    def force_reset(self) -> None:
        """
        Admin override — works even during an active cooldown.

        Intended for Telegram ``/resume`` command.
        """
        was_triggered = self._triggered
        old_reason = self._trigger_reason

        self.reset()

        if was_triggered:
            logger.warning(
                "⚠️  Circuit breaker FORCE RESET by admin | "
                "Was triggered for: %s",
                old_reason,
            )
        else:
            logger.info(
                "Force reset requested but circuit breaker was not triggered"
            )

    # ------------------------------------------------------------------ #
    #  Day boundary                                                        #
    # ------------------------------------------------------------------ #

    def start_new_day(self) -> None:
        """
        Prepare for a new trading session — call at market open.

        Resets
        ------
        - ``daily_pnl`` → 0
        - ``total / winning / losing trades today`` → 0

        Preserves
        ---------
        - ``consecutive_losses`` (carries across days by design)

        Trigger Handling
        ----------------
        - If trigger was **daily-loss** based → cleared (new day, fresh limit).
        - If trigger was **consecutive-loss** or **manual** → kept active
          (cooldown or admin reset required).
        """
        previous_pnl = self._daily_pnl
        previous_trades = self._total_trades_today

        # Reset daily counters
        self._daily_pnl = 0.0
        self._total_trades_today = 0
        self._winning_trades_today = 0
        self._losing_trades_today = 0

        # Clear trigger ONLY when it was daily-loss based
        if self._triggered and self._trigger_category == self.REASON_DAILY_LOSS:
            logger.info(
                "🌅 Daily-loss trigger cleared for new trading day | "
                "Yesterday's P&L: ₹%.2f",
                previous_pnl,
            )
            self._triggered = False
            self._trigger_reason = ""
            self._trigger_category = ""
            self._triggered_at = None
            self._cooldown_until = None

        logger.info(
            "🌅 New trading day started | "
            "Previous day: %d trades, P&L ₹%.2f | "
            "Consecutive losses carried forward: %d | "
            "Triggered: %s",
            previous_trades,
            previous_pnl,
            self._consecutive_losses,
            self._triggered,
        )

    # ------------------------------------------------------------------ #
    #  Status / reporting                                                  #
    # ------------------------------------------------------------------ #

    def get_status(self) -> dict:
        """
        Comprehensive snapshot of every circuit-breaker metric.

        Returns
        -------
        dict
            Keys: ``triggered``, ``reason``, ``category``,
            ``consecutive_losses``, ``max_consecutive_losses``,
            ``daily_pnl``, ``daily_loss_limit``, ``daily_loss_remaining``,
            ``total_trades_today``, ``winning_trades_today``,
            ``losing_trades_today``, ``cooldown_remaining_seconds``,
            ``cooldown_seconds``, ``triggered_at``, ``auto_reset_at``.
        """
        now = get_ist_now()

        cooldown_remaining = 0.0
        if self._triggered and self._cooldown_until is not None:
            cooldown_remaining = max(
                0.0, (self._cooldown_until - now).total_seconds()
            )

        return {
            "triggered": self._triggered,
            "reason": self._trigger_reason,
            "category": self._trigger_category,
            "consecutive_losses": self._consecutive_losses,
            "max_consecutive_losses": self._max_consecutive_losses,
            "daily_pnl": round(self._daily_pnl, 2),
            "daily_loss_limit": round(self._daily_loss_limit, 2),
            "daily_loss_remaining": round(
                max(0.0, self._daily_loss_limit + self._daily_pnl), 2
            ),
            "total_trades_today": self._total_trades_today,
            "winning_trades_today": self._winning_trades_today,
            "losing_trades_today": self._losing_trades_today,
            "cooldown_remaining_seconds": int(cooldown_remaining),
            "cooldown_seconds": self._cooldown_seconds,
            "triggered_at": (
                self._triggered_at.isoformat() if self._triggered_at else None
            ),
            "auto_reset_at": (
                self._cooldown_until.isoformat()
                if self._cooldown_until
                else None
            ),
        }

    # ------------------------------------------------------------------ #
    #  Dunder helpers                                                      #
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        status = "TRIGGERED" if self._triggered else "SAFE"
        return (
            f"CircuitBreaker("
            f"status={status}, "
            f"consecutive={self._consecutive_losses}/{self._max_consecutive_losses}, "
            f"daily_pnl=₹{self._daily_pnl:.2f}/"
            f"-₹{self._daily_loss_limit:.2f})"
        )

    def __str__(self) -> str:
        if self._triggered:
            return f"🚨 Circuit Breaker TRIGGERED: {self._trigger_reason}"
        return (
            f"✅ Circuit Breaker SAFE | "
            f"Losses: {self._consecutive_losses}/{self._max_consecutive_losses} | "
            f"Daily P&L: ₹{self._daily_pnl:.2f}"
        )


# ====================================================================== #
#  Standalone test / demo                                                  #
# ====================================================================== #

if __name__ == "__main__":
    import json
    import os
    import sys

    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── helpers ──────────────────────────────────────────────────────
    def header(title: str) -> None:
        print(f"\n{'─' * 60}")
        print(f"  {title}")
        print(f"{'─' * 60}")

    def show(cb: CircuitBreaker) -> None:
        print(f"  {cb}")
        print(f"  {repr(cb)}")

    # ── create breaker with fast settings for testing ────────────────
    cb = CircuitBreaker(
        max_consecutive_losses=3,      # trigger after 3 losses in a row
        cooldown_seconds=3600,         # 1 h (we will simulate expiry)
        max_daily_loss_pct=3.0,        # 3 % of 10 000 = ₹300
        initial_capital=10_000.0,
    )

    header("1 · Normal Trading")
    print("  Recording: +100, -30, +50")
    cb.record_trade_result(100.0)
    cb.record_trade_result(-30.0)
    cb.record_trade_result(50.0)
    show(cb)
    print(f"  Daily P&L : ₹{cb.daily_pnl:.2f}")
    print(f"  Consec. L : {cb.consecutive_losses}")
    # daily_pnl = 120, consecutive = 0

    header("2 · Consecutive-Loss Trigger")
    print("  Recording: -40, -50, -60  (3 in a row)")
    cb.record_trade_result(-40.0)
    cb.record_trade_result(-50.0)
    safe = cb.record_trade_result(-60.0)
    print(f"  safe after 3rd loss? {safe}")
    show(cb)
    print(f"  is_safe()  : {cb.is_safe()}")
    # daily_pnl = -30, consecutive = 3, TRIGGERED

    header("3 · Cooldown Active")
    print(f"  is_safe()  : {cb.is_safe()}")
    status = cb.get_status()
    print(f"  Cooldown remaining : {status['cooldown_remaining_seconds']} s")
    print(f"  Reason : {status['reason']}")

    header("4 · Simulate Cooldown Expiry → Auto-Reset")
    # Move cooldown_until into the past so is_safe() auto-resets
    cb._cooldown_until = get_ist_now() - timedelta(seconds=1)
    print(f"  (cooldown_until moved to past)")
    print(f"  is_safe()  : {cb.is_safe()}")
    show(cb)
    print(f"  Consec. L after reset : {cb.consecutive_losses}")
    # triggered = False, consecutive = 0, daily_pnl = -30

    header("5 · Daily-Loss Trigger")
    # Need to lose ₹270 more (already at -30, limit is -300)
    remaining = cb._daily_loss_limit + cb.daily_pnl
    print(f"  Current daily P&L : ₹{cb.daily_pnl:.2f}")
    print(f"  Loss remaining    : ₹{remaining:.2f}")
    print("  Recording: -100, +20, -100, -100")
    cb.record_trade_result(-100.0)       # daily = -130, consec = 1
    cb.record_trade_result(20.0)         # daily = -110, consec = 0
    cb.record_trade_result(-100.0)       # daily = -210, consec = 1
    safe = cb.record_trade_result(-100.0)  # daily = -310, consec = 2 → TRIGGER
    print(f"  safe? {safe}")
    show(cb)
    # Triggered on daily loss (consec=2 < 3, but -310 > -300)

    header("6 · Force Reset (Admin /resume)")
    cb.force_reset()
    show(cb)

    header("7 · Manual Trigger (Admin /kill)")
    cb.manual_trigger("Volatility too high — admin stop")
    show(cb)
    cb.force_reset()

    header("8 · New Day — Daily Counters Reset, Consecutive Preserved")
    cb.record_trade_result(-25.0)
    cb.record_trade_result(-25.0)
    print(f"  Before new day : consec = {cb.consecutive_losses}, "
          f"daily P&L = ₹{cb.daily_pnl:.2f}")
    cb.start_new_day()
    print(f"  After new day  : consec = {cb.consecutive_losses}, "
          f"daily P&L = ₹{cb.daily_pnl:.2f}")

    header("9 · New Day Clears Daily-Loss Trigger (not consecutive)")
    cb.reset()
    cb.record_trade_result(-150.0)
    cb.record_trade_result(-160.0)       # daily = -310 → TRIGGER
    print(f"  Triggered      : {cb.triggered}")
    print(f"  Category       : {cb.get_status()['category']}")
    cb.start_new_day()
    print(f"  After new day  : triggered = {cb.triggered}, "
          f"daily P&L = ₹{cb.daily_pnl:.2f}")

    header("10 · New Day Does NOT Clear Consecutive-Loss Trigger")
    cb.reset()
    cb.record_trade_result(-10.0)
    cb.record_trade_result(-10.0)
    cb.record_trade_result(-10.0)        # 3 consecutive → TRIGGER
    print(f"  Triggered      : {cb.triggered}")
    print(f"  Category       : {cb.get_status()['category']}")
    cb.start_new_day()
    print(f"  After new day  : triggered = {cb.triggered}  "
          f"(consecutive trigger survives new day)")

    header("Final Status (JSON)")
    cb.force_reset()
    print(json.dumps(cb.get_status(), indent=2, default=str))

    print(f"\n{'═' * 60}")
    print("  ✅  All circuit-breaker scenarios passed!")
    print(f"{'═' * 60}\n")