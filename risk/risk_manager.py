"""
Risk Manager - The Gatekeeper
===============================

Every trade signal produced by the Brain (Phase 4) must pass through
the Risk Manager before it can become an actual order. This is the
single most important safety layer in the entire bot.

Pipeline (11 sequential checks — fail-fast)
--------------------------------------------
    Signal from Brain
        │
        ├── 1.  Market open & accepting new trades?
        ├── 2.  Circuit breaker safe?
        ├── 3.  Daily trade count within limit?
        ├── 4.  Daily P&L within loss limit?
        ├── 5.  Open position count within limit?
        ├── 6.  Sufficient capital available?
        ├── 7.  Signal confidence above threshold?
        ├── 8.  Option premium within bounds?
        ├── 9.  Implied volatility acceptable?
        ├── 10. Expiry valid & not too close?
        ├── 11. No duplicate open position?
        │
        ▼
    Approved → trade_params dict sent to Execution (Phase 6)

Position Exit Monitoring
-------------------------
For every open position the bot continuously checks:
- Stop-loss hit           → exit reason ``SL``
- Take-profit hit         → exit reason ``TP``
- Trailing stop hit       → exit reason ``TRAIL``
- Market close window     → exit reason ``TIME``
"""

import logging
from typing import Dict, List, Optional, Tuple

from config import constants
from config.settings import settings
from risk.circuit_breaker import CircuitBreaker
from utils.exceptions import (
    CircuitBreakerError,
    DailyLossLimitError,
    ExpiryTooCloseError,
    InsufficientFundsError,
    MarketClosedError,
    MaxPositionsError,
    MaxTradesError,
    PremiumTooHighError,
)
from utils.helpers import (
    format_currency,
    format_pnl,
    generate_order_id,
    generate_trade_id,
    get_atm_strike,
    get_ist_now,
    safe_divide,
)
from utils.indian_market import (
    can_take_new_trades,
    get_days_to_expiry,
    get_weekly_expiry,
    is_market_open,
    should_close_all_positions,
)

logger = logging.getLogger(__name__)

# ── Hours before expiry where we refuse new trades ───────────────────
CLOSE_BEFORE_EXPIRY_HOURS = 2.0


class RiskManager:
    """
    Central risk gatekeeper for the options trading bot.

    Parameters
    ----------
    settings : object
        Application settings from ``config.settings``.
    trade_repository : TradeRepository
        Access to trade history (today's trades, P&L).
    position_repository : PositionRepository
        Access to currently open positions.
    circuit_breaker : CircuitBreaker
        Emergency shutdown controller.

    Examples
    --------
    >>> rm = RiskManager(settings, trade_repo, pos_repo, cb)
    >>> ok, reason, params = rm.can_trade(signal, 10_000.0)
    >>> if ok:
    ...     execute_trade(params)
    """

    def __init__(
        self,
        settings,
        trade_repository,
        position_repository,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        self._settings = settings
        self._trade_repo = trade_repository
        self._position_repo = position_repository
        self._circuit_breaker = circuit_breaker

        # ── Capital tracking ─────────────────────────────────────────
        self._current_capital: float = float(
            getattr(settings, "INITIAL_CAPITAL", 10_000)
        )
        self._initial_capital: float = self._current_capital

        # ── Settings shortcuts (with safe defaults) ──────────────────
        self._max_capital_per_trade: float = float(
            getattr(settings, "MAX_CAPITAL_PER_TRADE", 2500)
        )
        self._max_open_positions: int = int(
            getattr(settings, "MAX_OPEN_POSITIONS", 4)
        )
        self._max_trades_per_day: int = int(
            getattr(settings, "MAX_TRADES_PER_DAY", 20)
        )
        self._max_daily_loss_pct: float = float(
            getattr(settings, "MAX_DAILY_LOSS", 0.03)
        )
        self._stop_loss_pct: float = float(
            getattr(settings, "STOP_LOSS_PERCENTAGE", constants.DEFAULT_STOP_LOSS_PCT)
        )
        self._take_profit_pct: float = float(
            getattr(settings, "TAKE_PROFIT_PERCENTAGE", constants.DEFAULT_TAKE_PROFIT_PCT)
        )
        self._trailing_stop_pct: float = float(
            getattr(settings, "TRAILING_STOP_PERCENTAGE", constants.DEFAULT_TRAILING_STOP_PCT)
        )
        self._max_premium_per_lot: float = float(
            getattr(settings, "MAX_PREMIUM_PER_LOT", 250)
        )
        self._min_premium_per_lot: float = float(
            getattr(settings, "MIN_PREMIUM_PER_LOT", 20)
        )
        self._max_iv_threshold: float = float(
            getattr(settings, "MAX_IV_THRESHOLD", 30)
        )
        self._max_lots_per_trade: int = int(
            getattr(settings, "MAX_LOTS_PER_TRADE", 1)
        )
        self._min_confidence: float = float(
            getattr(settings, "MIN_CONFIDENCE_THRESHOLD", constants.MIN_CONFIDENCE_THRESHOLD)
        )
        self._risk_per_trade: float = float(
            getattr(settings, "RISK_PER_TRADE", 0.02)
        )

        logger.info(
            "Risk Manager initialised | "
            "Capital: %s | Max/trade: %s | "
            "Positions: %d | Trades/day: %d | "
            "SL: %.1f%% | TP: %.1f%% | Trail: %.1f%%",
            format_currency(self._current_capital),
            format_currency(self._max_capital_per_trade),
            self._max_open_positions,
            self._max_trades_per_day,
            self._stop_loss_pct,
            self._take_profit_pct,
            self._trailing_stop_pct,
        )

    # ================================================================ #
    #  PROPERTY ACCESSORS                                                #
    # ================================================================ #

    @property
    def current_capital(self) -> float:
        """Available capital after accounting for open positions."""
        return self._current_capital

    @property
    def initial_capital(self) -> float:
        """Starting capital — used for loss-limit percentages."""
        return self._initial_capital

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Underlying circuit-breaker instance."""
        return self._circuit_breaker

    # ================================================================ #
    #  MAIN GATEKEEPER — can_trade()                                     #
    # ================================================================ #

    def can_trade(
        self, signal: dict, current_capital: float
    ) -> Tuple[bool, str, Optional[dict]]:
        """
        Run every risk check against a brain signal.

        Parameters
        ----------
        signal : dict
            Output from ``BrainCoordinator.analyze_symbol()``.
            Expected keys: ``symbol``, ``action``, ``confidence``,
            ``option_recommendation`` (with ``type``, ``strike_preference``,
            ``expiry``), ``reasoning``.
        current_capital : float
            Capital currently available for new trades.

        Returns
        -------
        tuple[bool, str, dict | None]
            ``(approved, reason, trade_params)``
            If rejected, ``trade_params`` is ``None``.
        """
        self._current_capital = current_capital
        symbol = signal.get("symbol", "UNKNOWN")
        action = signal.get("action", constants.SIGNAL_HOLD)
        confidence = signal.get("confidence", 0.0)
        option_rec = signal.get("option_recommendation", {})

        logger.info(
            "━━━ Risk check START | %s | %s | confidence %.2f ━━━",
            symbol,
            action,
            confidence,
        )

        # Fast-exit for HOLD signals — nothing to evaluate
        if action == constants.SIGNAL_HOLD:
            return self._reject("Signal is HOLD — no trade action required")

        # ── Check 1: Market open ─────────────────────────────────────
        try:
            self._check_market_open()
        except MarketClosedError as exc:
            return self._reject(f"Check 1 FAIL — {exc}")

        # ── Check 2: Circuit breaker ────────────────────────────────
        try:
            self._check_circuit_breaker()
        except CircuitBreakerError as exc:
            return self._reject(f"Check 2 FAIL — {exc}")

        # ── Check 3: Daily trade limit ──────────────────────────────
        try:
            trades_today = self._check_daily_trade_limit()
        except MaxTradesError as exc:
            return self._reject(f"Check 3 FAIL — {exc}")

        # ── Check 4: Daily loss limit ───────────────────────────────
        try:
            daily_pnl = self._check_daily_loss_limit()
        except DailyLossLimitError as exc:
            return self._reject(f"Check 4 FAIL — {exc}")

        # ── Check 5: Max open positions ─────────────────────────────
        try:
            open_positions = self._check_max_positions()
        except MaxPositionsError as exc:
            return self._reject(f"Check 5 FAIL — {exc}")

        # ── Check 6: Capital available ──────────────────────────────
        try:
            self._check_capital(current_capital)
        except InsufficientFundsError as exc:
            return self._reject(f"Check 6 FAIL — {exc}")

        # ── Check 7: Confidence threshold ───────────────────────────
        passed, msg = self._check_confidence(confidence)
        if not passed:
            return self._reject(f"Check 7 FAIL — {msg}")

        # ── Check 8: Premium bounds ─────────────────────────────────
        premium = option_rec.get("premium", 0.0)
        try:
            self._check_premium(premium)
        except PremiumTooHighError as exc:
            return self._reject(f"Check 8 FAIL — {exc}")

        # ── Check 9: IV threshold ───────────────────────────────────
        iv = option_rec.get("iv", 0.0)
        passed, msg = self._check_iv(iv)
        if not passed:
            return self._reject(f"Check 9 FAIL — {msg}")

        # ── Check 10: Expiry valid ──────────────────────────────────
        expiry = option_rec.get("expiry")
        try:
            self._check_expiry(expiry)
        except ExpiryTooCloseError as exc:
            return self._reject(f"Check 10 FAIL — {exc}")

        # ── Check 11: Duplicate position ────────────────────────────
        option_type = option_rec.get("type", constants.OPTION_TYPE_CALL)
        strike = option_rec.get("strike_preference", 0)
        passed, msg = self._check_duplicate_position(
            symbol, strike, option_type, expiry
        )
        if not passed:
            return self._reject(f"Check 11 FAIL — {msg}")

        # ── ALL CHECKS PASSED — build trade_params ──────────────────
        trade_params = self._build_trade_params(
            signal=signal,
            symbol=symbol,
            action=action,
            confidence=confidence,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            premium=premium,
            current_capital=current_capital,
        )

        logger.info(
            "✅ TRADE APPROVED | %s | %s %s %s @ ₹%.2f | "
            "SL: ₹%.2f | TP: ₹%.2f | Qty: %d",
            symbol,
            trade_params["instrument"],
            trade_params["side"],
            option_type,
            premium,
            trade_params["stop_loss"],
            trade_params["take_profit"],
            trade_params["quantity"],
        )

        return True, "All risk checks passed", trade_params

    # ================================================================ #
    #  INDIVIDUAL CHECKS (private)                                       #
    # ================================================================ #

    def _check_market_open(self) -> None:
        """Check 1 — Market must be open and accepting new trades."""
        if not is_market_open():
            raise MarketClosedError("Market is closed")
        if not can_take_new_trades():
            raise MarketClosedError(
                "Past new-trade cutoff — no new trades accepted"
            )

    def _check_circuit_breaker(self) -> None:
        """Check 2 — Circuit breaker must be in safe state."""
        if not self._circuit_breaker.is_safe():
            status = self._circuit_breaker.get_status()
            raise CircuitBreakerError(
                reason=status.get("reason", "Circuit breaker triggered"),
                cooldown=status.get("cooldown_remaining_seconds", 0),
            )

    def _check_daily_trade_limit(self) -> int:
        """
        Check 3 — Must not exceed max trades per day.

        Returns
        -------
        int
            Number of trades placed today.
        """
        trades_today = self._trade_repo.get_trades_today()
        count = len(trades_today) if isinstance(trades_today, list) else int(trades_today)

        if count >= self._max_trades_per_day:
            raise MaxTradesError(
                current=count,
                maximum=self._max_trades_per_day,
            )

        logger.debug(
            "Check 3 OK — trades today: %d / %d",
            count,
            self._max_trades_per_day,
        )
        return count

    def _check_daily_loss_limit(self) -> float:
        """
        Check 4 — Daily P&L must not exceed allowed loss.

        Returns
        -------
        float
            Today's net P&L.
        """
        daily_pnl = self._trade_repo.get_total_pnl()
        if isinstance(daily_pnl, dict):
            daily_pnl = daily_pnl.get("total_pnl", 0.0)
        daily_pnl = float(daily_pnl or 0.0)

        max_loss = self._initial_capital * self._max_daily_loss_pct
        # max_loss is a positive number; daily_pnl is negative when losing
        if daily_pnl < 0 and abs(daily_pnl) >= max_loss:
            raise DailyLossLimitError(
                current_loss=abs(daily_pnl),
                max_loss=max_loss,
            )

        logger.debug(
            "Check 4 OK — daily P&L: %s / max loss: %s",
            format_pnl(daily_pnl),
            format_currency(max_loss),
        )
        return daily_pnl

    def _check_max_positions(self) -> list:
        """
        Check 5 — Must not exceed max open positions.

        Returns
        -------
        list
            Currently open positions.
        """
        open_positions = self._position_repo.get_open_positions()
        if not isinstance(open_positions, list):
            open_positions = list(open_positions) if open_positions else []

        count = len(open_positions)
        if count >= self._max_open_positions:
            raise MaxPositionsError(
                current=count,
                maximum=self._max_open_positions,
            )

        logger.debug(
            "Check 5 OK — open positions: %d / %d",
            count,
            self._max_open_positions,
        )
        return open_positions

    def _check_capital(self, current_capital: float) -> None:
        """Check 6 — Must have enough capital for at least one trade."""
        if current_capital < self._max_capital_per_trade:
            raise InsufficientFundsError(
                required=self._max_capital_per_trade,
                available=current_capital,
            )
        logger.debug(
            "Check 6 OK — capital: %s / required: %s",
            format_currency(current_capital),
            format_currency(self._max_capital_per_trade),
        )

    def _check_confidence(self, confidence: float) -> Tuple[bool, str]:
        """Check 7 — Signal confidence must meet minimum threshold."""
        if confidence < self._min_confidence:
            msg = (
                f"Confidence {confidence:.2f} below "
                f"threshold {self._min_confidence:.2f}"
            )
            return False, msg

        logger.debug(
            "Check 7 OK — confidence: %.2f / min: %.2f",
            confidence,
            self._min_confidence,
        )
        return True, ""

    def _check_premium(self, premium: float) -> None:
        """Check 8 — Option premium must be within acceptable range."""
        if premium <= 0:
            # premium not available in signal — skip this check
            logger.debug(
                "Check 8 SKIP — premium not provided (%.2f)", premium
            )
            return

        if premium > self._max_premium_per_lot:
            raise PremiumTooHighError(
                premium=premium,
                max_premium=self._max_premium_per_lot,
            )

        if premium < self._min_premium_per_lot:
            # Not a custom exception — just reject with message
            raise PremiumTooHighError(
                premium=premium,
                max_premium=self._min_premium_per_lot,
            )

        logger.debug(
            "Check 8 OK — premium: ₹%.2f (range: ₹%.2f - ₹%.2f)",
            premium,
            self._min_premium_per_lot,
            self._max_premium_per_lot,
        )

    def _check_iv(self, iv: float) -> Tuple[bool, str]:
        """Check 9 — Implied volatility must not be excessively high."""
        if iv <= 0:
            # IV not available in signal — skip this check
            logger.debug("Check 9 SKIP — IV not provided (%.2f)", iv)
            return True, ""

        if iv > self._max_iv_threshold:
            msg = (
                f"IV {iv:.1f}% exceeds threshold {self._max_iv_threshold:.1f}% "
                f"— premiums likely inflated"
            )
            return False, msg

        logger.debug(
            "Check 9 OK — IV: %.1f%% / max: %.1f%%",
            iv,
            self._max_iv_threshold,
        )
        return True, ""

    def _check_expiry(self, expiry) -> None:
        """Check 10 — Expiry must exist and not be too close."""
        if expiry is None:
            # No expiry in signal — try weekly expiry
            logger.debug("Check 10 SKIP — no expiry in signal, will use weekly")
            return

        days = get_days_to_expiry(expiry)

        if days < 0:
            raise ExpiryTooCloseError(hours_to_expiry=days * 24)

        hours_to_expiry = days * 24.0
        if hours_to_expiry < CLOSE_BEFORE_EXPIRY_HOURS:
            raise ExpiryTooCloseError(hours_to_expiry=hours_to_expiry)

        logger.debug(
            "Check 10 OK — days to expiry: %.1f (%.1f hours)",
            days,
            hours_to_expiry,
        )

    def _check_duplicate_position(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        expiry,
    ) -> Tuple[bool, str]:
        """Check 11 — Must not already hold a position in same instrument."""
        open_positions = self._position_repo.get_open_positions()
        if not isinstance(open_positions, list):
            open_positions = list(open_positions) if open_positions else []

        instrument_key = self._make_instrument_key(
            symbol, strike, option_type, expiry
        )

        for position in open_positions:
            existing_key = self._make_instrument_key(
                getattr(position, "symbol", ""),
                getattr(position, "strike", 0),
                getattr(position, "option_type", ""),
                getattr(position, "expiry", None),
            )
            if existing_key == instrument_key:
                msg = f"Duplicate position — already holding {instrument_key}"
                return False, msg

        logger.debug("Check 11 OK — no duplicate for %s", instrument_key)
        return True, ""

    # ================================================================ #
    #  TRADE PARAMS BUILDER                                              #
    # ================================================================ #

    def _build_trade_params(
        self,
        signal: dict,
        symbol: str,
        action: str,
        confidence: float,
        option_type: str,
        strike: float,
        expiry,
        premium: float,
        current_capital: float,
    ) -> dict:
        """
        Construct the complete trade-parameters dictionary.

        Called only after all 11 checks have passed.
        """
        # ── Determine lot size ───────────────────────────────────────
        lot_size = self._get_lot_size(symbol)
        lots = self._max_lots_per_trade
        quantity = lot_size * lots

        # ── Use premium from signal or estimate ──────────────────────
        entry_price = premium if premium > 0 else 0.0

        # ── Calculate SL / TP ────────────────────────────────────────
        stop_loss = self.calculate_stop_loss(entry_price, option_type)
        take_profit = self.calculate_take_profit(entry_price, option_type)

        # ── Risk / reward calculations ───────────────────────────────
        sl_distance = max(0.0, entry_price - stop_loss)
        tp_distance = max(0.0, take_profit - entry_price)
        max_loss = quantity * sl_distance
        max_profit = quantity * tp_distance
        capital_required = quantity * entry_price
        risk_amount = min(
            max_loss,
            current_capital * self._risk_per_trade,
        )

        # ── Resolve expiry ───────────────────────────────────────────
        if expiry is None:
            expiry = get_weekly_expiry(symbol)

        # ── Build instrument name ────────────────────────────────────
        strike_display = int(strike) if strike == int(strike) else strike
        instrument = f"{symbol} {strike_display} {option_type}"

        # ── Determine side ───────────────────────────────────────────
        side = "BUY"  # options buying strategy — always BUY premium

        return {
            "approved": True,
            "trade_id": generate_trade_id(),
            "order_id": generate_order_id(),
            "symbol": symbol,
            "instrument": instrument,
            "strike": strike,
            "option_type": option_type,
            "expiry": str(expiry) if expiry else None,
            "side": side,
            "action": action,
            "quantity": quantity,
            "lots": lots,
            "lot_size": lot_size,
            "entry_price": round(entry_price, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "trailing_stop": round(stop_loss, 2),  # starts at SL
            "sl_distance": round(sl_distance, 2),
            "tp_distance": round(tp_distance, 2),
            "max_loss": round(max_loss, 2),
            "max_profit": round(max_profit, 2),
            "risk_amount": round(risk_amount, 2),
            "capital_required": round(capital_required, 2),
            "confidence": round(confidence, 4),
            "reasoning": signal.get("reasoning", ""),
            "brain_signals": signal.get("brain_signals", {}),
            "timestamp": get_ist_now().isoformat(),
        }

    # ================================================================ #
    #  STOP-LOSS / TAKE-PROFIT / TRAILING                                #
    # ================================================================ #

    def calculate_stop_loss(self, entry_price: float, option_type: str) -> float:
        """
        Calculate stop-loss price for an option position.

        For option buying: SL = entry × (1 − SL_PCT / 100)

        Example
        -------
        entry = 100, SL_PCT = 30
        → SL at 70  (exit if premium drops to 70)

        Parameters
        ----------
        entry_price : float
            Premium paid per unit.
        option_type : str
            ``CE`` or ``PE`` — currently same logic for both.

        Returns
        -------
        float
            Stop-loss price (always >= 0).
        """
        if entry_price <= 0:
            return 0.0
        sl = entry_price * (1.0 - self._stop_loss_pct / 100.0)
        return max(0.0, round(sl, 2))

    def calculate_take_profit(
        self, entry_price: float, option_type: str
    ) -> float:
        """
        Calculate take-profit price for an option position.

        For option buying: TP = entry × (1 + TP_PCT / 100)

        Example
        -------
        entry = 100, TP_PCT = 50
        → TP at 150  (exit when premium reaches 150)

        Parameters
        ----------
        entry_price : float
            Premium paid per unit.
        option_type : str
            ``CE`` or ``PE`` — currently same logic for both.

        Returns
        -------
        float
            Take-profit price.
        """
        if entry_price <= 0:
            return 0.0
        tp = entry_price * (1.0 + self._take_profit_pct / 100.0)
        return round(tp, 2)

    def calculate_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        highest_price: float,
    ) -> float:
        """
        Calculate trailing stop-loss that ratchets upward.

        The trailing stop is computed from the *highest* price seen
        since entry. It only ever moves **up**, never down.

        Logic
        -----
        trailing_sl = highest_price × (1 − TRAILING_PCT / 100)
        Return max(trailing_sl, original_stop_loss) so we never
        lower protection below the original stop.

        Example
        -------
        entry = 100, SL = 70, highest = 160, TRAIL = 20%
        → trailing_sl = 160 × 0.80 = 128
        → 128 > 70 (original SL) → return 128

        Parameters
        ----------
        entry_price : float
            Original premium paid.
        current_price : float
            Current option premium (used for logging / awareness).
        highest_price : float
            Highest premium observed since entry.

        Returns
        -------
        float
            Updated trailing stop (never lower than original SL).
        """
        if entry_price <= 0 or highest_price <= 0:
            return 0.0

        original_sl = self.calculate_stop_loss(entry_price, "")

        # Only compute trailing once price has moved above entry
        if highest_price <= entry_price:
            return original_sl

        trailing_sl = highest_price * (1.0 - self._trailing_stop_pct / 100.0)

        # Ratchet — never go below original SL
        final_sl = max(original_sl, trailing_sl)

        logger.debug(
            "Trailing SL | entry: ₹%.2f | current: ₹%.2f | "
            "highest: ₹%.2f | trail: ₹%.2f | original SL: ₹%.2f | "
            "final: ₹%.2f",
            entry_price,
            current_price,
            highest_price,
            trailing_sl,
            original_sl,
            final_sl,
        )

        return round(final_sl, 2)

    # ================================================================ #
    #  POSITION EXIT MONITOR                                             #
    # ================================================================ #

    def check_position_exit(
        self, trade, current_price: float
    ) -> Tuple[bool, str]:
        """
        Determine whether an open position should be closed.

        Parameters
        ----------
        trade : Trade
            Database trade model with ``entry_price``, ``stop_loss``,
            ``take_profit``, and optionally ``highest_price``.
        current_price : float
            Current market premium of the option.

        Returns
        -------
        tuple[bool, str]
            ``(should_exit, reason)``
            Reason codes: ``SL``, ``TP``, ``TRAIL``, ``TIME``, or ``""``.
        """
        entry_price = float(getattr(trade, "entry_price", 0))
        stop_loss = float(getattr(trade, "stop_loss", 0))
        take_profit = float(getattr(trade, "take_profit", 0))
        highest_price = float(
            getattr(trade, "highest_price", entry_price)
        )

        if current_price <= 0:
            logger.warning(
                "Position exit check — invalid current price: %.2f",
                current_price,
            )
            return False, ""

        # ── Check 1: Stop-loss hit ───────────────────────────────────
        if stop_loss > 0 and current_price <= stop_loss:
            logger.warning(
                "🛑 STOP LOSS HIT | price ₹%.2f <= SL ₹%.2f | "
                "entry ₹%.2f | loss %.1f%%",
                current_price,
                stop_loss,
                entry_price,
                safe_divide(
                    (current_price - entry_price), entry_price, 0
                ) * 100,
            )
            return True, "SL"

        # ── Check 2: Take-profit hit ────────────────────────────────
        if take_profit > 0 and current_price >= take_profit:
            logger.info(
                "🎯 TAKE PROFIT HIT | price ₹%.2f >= TP ₹%.2f | "
                "entry ₹%.2f | gain %.1f%%",
                current_price,
                take_profit,
                entry_price,
                safe_divide(
                    (current_price - entry_price), entry_price, 0
                ) * 100,
            )
            return True, "TP"

        # ── Check 3: Time-based exit (close before market end) ──────
        if should_close_all_positions():
            logger.info(
                "⏰ TIME EXIT | Market close window reached | "
                "price ₹%.2f | entry ₹%.2f",
                current_price,
                entry_price,
            )
            return True, "TIME"

        # ── Check 4: Trailing stop hit ──────────────────────────────
        if highest_price > entry_price:
            trailing_sl = self.calculate_trailing_stop(
                entry_price, current_price, highest_price
            )
            if trailing_sl > stop_loss and current_price <= trailing_sl:
                logger.info(
                    "📉 TRAILING STOP HIT | price ₹%.2f <= trail ₹%.2f | "
                    "highest ₹%.2f | entry ₹%.2f",
                    current_price,
                    trailing_sl,
                    highest_price,
                    entry_price,
                )
                return True, "TRAIL"

        return False, ""

    # ================================================================ #
    #  CAPITAL MANAGEMENT                                                #
    # ================================================================ #

    def update_capital(self, new_capital: float) -> None:
        """
        Update available capital after a trade is opened or closed.

        Parameters
        ----------
        new_capital : float
            New total available capital.
        """
        old = self._current_capital
        self._current_capital = new_capital
        logger.info(
            "Capital updated: %s → %s (%s)",
            format_currency(old),
            format_currency(new_capital),
            format_pnl(new_capital - old),
        )

    # ================================================================ #
    #  RISK SUMMARY                                                      #
    # ================================================================ #

    def get_risk_summary(self) -> dict:
        """
        Comprehensive snapshot of the current risk landscape.

        Returns
        -------
        dict
            Ready for logging, Telegram status, or dashboard display.
        """
        # ── Gather data from repos ───────────────────────────────────
        trades_today = self._trade_repo.get_trades_today()
        trade_count = (
            len(trades_today) if isinstance(trades_today, list)
            else int(trades_today or 0)
        )

        daily_pnl = self._trade_repo.get_total_pnl()
        if isinstance(daily_pnl, dict):
            daily_pnl = daily_pnl.get("total_pnl", 0.0)
        daily_pnl = float(daily_pnl or 0.0)

        open_positions = self._position_repo.get_open_positions()
        if not isinstance(open_positions, list):
            open_positions = list(open_positions) if open_positions else []
        position_count = len(open_positions)

        max_loss = self._initial_capital * self._max_daily_loss_pct
        cb_status = self._circuit_breaker.get_status()

        # ── Can we trade right now? ──────────────────────────────────
        can_trade_now = (
            is_market_open()
            and can_take_new_trades()
            and self._circuit_breaker.is_safe()
            and trade_count < self._max_trades_per_day
            and position_count < self._max_open_positions
            and self._current_capital >= self._max_capital_per_trade
            and not (daily_pnl < 0 and abs(daily_pnl) >= max_loss)
        )

        return {
            "timestamp": get_ist_now().isoformat(),
            "capital": {
                "initial": round(self._initial_capital, 2),
                "current": round(self._current_capital, 2),
                "change": round(
                    self._current_capital - self._initial_capital, 2
                ),
                "change_pct": round(
                    safe_divide(
                        self._current_capital - self._initial_capital,
                        self._initial_capital,
                        0.0,
                    ) * 100,
                    2,
                ),
            },
            "daily": {
                "pnl": round(daily_pnl, 2),
                "pnl_formatted": format_pnl(daily_pnl),
                "trades": trade_count,
                "max_trades": self._max_trades_per_day,
                "trades_remaining": max(
                    0, self._max_trades_per_day - trade_count
                ),
                "loss_limit": round(max_loss, 2),
                "loss_remaining": round(
                    max(0.0, max_loss + daily_pnl), 2
                ),
            },
            "positions": {
                "open": position_count,
                "max": self._max_open_positions,
                "slots_remaining": max(
                    0, self._max_open_positions - position_count
                ),
            },
            "circuit_breaker": cb_status,
            "risk_params": {
                "stop_loss_pct": self._stop_loss_pct,
                "take_profit_pct": self._take_profit_pct,
                "trailing_stop_pct": self._trailing_stop_pct,
                "max_capital_per_trade": self._max_capital_per_trade,
                "max_premium_per_lot": self._max_premium_per_lot,
                "min_premium_per_lot": self._min_premium_per_lot,
                "max_iv_threshold": self._max_iv_threshold,
                "min_confidence": self._min_confidence,
                "risk_per_trade": self._risk_per_trade,
            },
            "can_trade": can_trade_now,
            "market_open": is_market_open(),
            "accepting_new_trades": can_take_new_trades(),
        }

    # ================================================================ #
    #  PRIVATE HELPERS                                                   #
    # ================================================================ #

    def _reject(self, reason: str) -> Tuple[bool, str, None]:
        """Log rejection and return standardised rejection tuple."""
        logger.warning("❌ TRADE REJECTED — %s", reason)
        return False, reason, None

    def _get_lot_size(self, symbol: str) -> int:
        """
        Return the lot size for the given index symbol.

        Parameters
        ----------
        symbol : str
            ``NIFTY`` or ``BANKNIFTY``.

        Returns
        -------
        int
        """
        symbol_upper = symbol.upper()
        if "BANKNIFTY" in symbol_upper or "BANK" in symbol_upper:
            return int(
                getattr(
                    self._settings,
                    "BANKNIFTY_LOT_SIZE",
                    constants.LOT_SIZE_BANKNIFTY,
                )
            )
        return int(
            getattr(
                self._settings,
                "NIFTY_LOT_SIZE",
                constants.LOT_SIZE_NIFTY,
            )
        )

    @staticmethod
    def _make_instrument_key(
        symbol: str,
        strike: float,
        option_type: str,
        expiry,
    ) -> str:
        """
        Build a unique key for position deduplication.

        Format: ``NIFTY_24500_CE_2024-01-25``
        """
        strike_int = int(strike) if strike == int(strike) else strike
        return (
            f"{str(symbol).upper()}_"
            f"{strike_int}_"
            f"{str(option_type).upper()}_"
            f"{str(expiry)}"
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
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── Helpers ──────────────────────────────────────────────────────
    def header(title: str) -> None:
        print(f"\n{'─' * 65}")
        print(f"  {title}")
        print(f"{'─' * 65}")

    # ── Mock Settings ────────────────────────────────────────────────
    class MockSettings:
        INITIAL_CAPITAL = 10_000.0
        MAX_CAPITAL_PER_TRADE = 2_500.0
        MAX_OPEN_POSITIONS = 4
        MAX_TRADES_PER_DAY = 20
        MAX_DAILY_LOSS = 0.03
        PAPER_TRADING = True
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

    # ── Mock Trade Repository ────────────────────────────────────────
    class MockTradeRepo:
        def __init__(self):
            self._trades = []
            self._pnl = 0.0

        def get_trades_today(self):
            return self._trades

        def get_total_pnl(self):
            return self._pnl

        def set_trades(self, count: int):
            self._trades = [f"trade_{i}" for i in range(count)]

        def set_pnl(self, pnl: float):
            self._pnl = pnl

    # ── Mock Position Repository ─────────────────────────────────────
    class MockPosition:
        def __init__(self, symbol, strike, option_type, expiry):
            self.symbol = symbol
            self.strike = strike
            self.option_type = option_type
            self.expiry = expiry

    class MockPositionRepo:
        def __init__(self):
            self._positions = []

        def get_open_positions(self):
            return self._positions

        def add_position(self, symbol, strike, option_type, expiry):
            self._positions.append(
                MockPosition(symbol, strike, option_type, expiry)
            )

        def clear(self):
            self._positions = []

    # ── Mock Trade (for position exit tests) ─────────────────────────
    class MockTrade:
        def __init__(
            self, entry_price, stop_loss, take_profit, highest_price=None
        ):
            self.entry_price = entry_price
            self.stop_loss = stop_loss
            self.take_profit = take_profit
            self.highest_price = (
                highest_price if highest_price else entry_price
            )

    # ── Create instances ─────────────────────────────────────────────
    mock_settings = MockSettings()
    trade_repo = MockTradeRepo()
    position_repo = MockPositionRepo()
    cb = CircuitBreaker(
        max_consecutive_losses=5,
        cooldown_seconds=3600,
        max_daily_loss_pct=3.0,
        initial_capital=10_000.0,
    )
    rm = RiskManager(mock_settings, trade_repo, position_repo, cb)

    # ── Sample signal ────────────────────────────────────────────────
    def make_signal(
        symbol="NIFTY",
        action=constants.SIGNAL_BUY,
        confidence=0.75,
        option_type="CE",
        strike=24500,
        premium=120.0,
        iv=18.0,
        expiry="2025-01-30",
    ):
        return {
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "reasoning": "Test signal",
            "brain_signals": {"technical": {"action": action}},
            "option_recommendation": {
                "type": option_type,
                "strike_preference": strike,
                "expiry": expiry,
                "premium": premium,
                "iv": iv,
            },
        }

    # ── TEST 1: SL / TP / Trailing calculations ─────────────────────
    header("1 · Stop-Loss / Take-Profit / Trailing Calculations")
    entry = 100.0
    sl = rm.calculate_stop_loss(entry, "CE")
    tp = rm.calculate_take_profit(entry, "CE")
    print(f"  Entry   : ₹{entry}")
    print(f"  SL (30%): ₹{sl}  (exit if premium drops to {sl})")
    print(f"  TP (50%): ₹{tp}  (exit when premium reaches {tp})")

    print()
    highest = 160.0
    trail = rm.calculate_trailing_stop(entry, 145.0, highest)
    print(f"  Trailing (entry=100, highest=160, trail_pct=20%)")
    print(f"  Trailing SL : ₹{trail}")
    print(f"  Original SL : ₹{sl}")
    print(f"  Active SL   : ₹{max(sl, trail)} (higher wins)")

    # ── TEST 2: Position exit scenarios ──────────────────────────────
    header("2 · Position Exit Checks")
    trade = MockTrade(entry_price=100, stop_loss=70, take_profit=150)

    scenarios = [
        (65.0, "Below SL"),
        (70.0, "At SL"),
        (100.0, "At entry"),
        (130.0, "In profit, no exit"),
        (150.0, "At TP"),
        (200.0, "Above TP"),
    ]
    for price, label in scenarios:
        should_exit, reason = rm.check_position_exit(trade, price)
        status = f"EXIT ({reason})" if should_exit else "HOLD"
        print(f"  Price ₹{price:>6.1f} — {label:<25s} → {status}")

    # Trailing stop scenario
    print()
    trade_trail = MockTrade(
        entry_price=100, stop_loss=70, take_profit=200, highest_price=160
    )
    price = 125.0  # 160 * 0.80 = 128 trailing SL, 125 < 128
    should_exit, reason = rm.check_position_exit(trade_trail, price)
    print(
        f"  Trailing: entry=100, highest=160, current=125 "
        f"→ {'EXIT (' + reason + ')' if should_exit else 'HOLD'}"
    )

    # ── TEST 3: Confidence check ─────────────────────────────────────
    header("3 · Confidence Threshold")
    for conf in [0.50, 0.59, 0.60, 0.75, 0.90]:
        sig = make_signal(confidence=conf)
        ok, reason, params = rm.can_trade(sig, 10_000.0)
        status = "✅ APPROVED" if ok else f"❌ REJECTED"
        print(f"  Confidence {conf:.2f} → {status}")

    # ── TEST 4: Premium bounds ───────────────────────────────────────
    header("4 · Premium Bounds (₹20 – ₹250)")
    for prem in [10.0, 20.0, 120.0, 250.0, 300.0]:
        sig = make_signal(premium=prem)
        ok, reason, params = rm.can_trade(sig, 10_000.0)
        status = "✅" if ok else "❌"
        print(f"  Premium ₹{prem:>6.1f} → {status} {reason[:50] if not ok else ''}")

    # ── TEST 5: IV threshold ─────────────────────────────────────────
    header("5 · IV Threshold (max 30%)")
    for iv in [15.0, 25.0, 30.0, 35.0, 50.0]:
        sig = make_signal(iv=iv)
        ok, reason, params = rm.can_trade(sig, 10_000.0)
        status = "✅" if ok else "❌"
        print(f"  IV {iv:>5.1f}% → {status}")

    # ── TEST 6: Capital check ────────────────────────────────────────
    header("6 · Capital Check (need ₹2500)")
    for cap in [1_000.0, 2_499.0, 2_500.0, 5_000.0, 10_000.0]:
        sig = make_signal()
        ok, reason, params = rm.can_trade(sig, cap)
        status = "✅" if ok else "❌"
        print(f"  Capital ₹{cap:>8.0f} → {status}")

    # ── TEST 7: Trade limit ──────────────────────────────────────────
    header("7 · Daily Trade Limit (max 20)")
    trade_repo.set_trades(19)
    sig = make_signal()
    ok, reason, _ = rm.can_trade(sig, 10_000.0)
    print(f"  19 trades done → {'✅' if ok else '❌'}")
    trade_repo.set_trades(20)
    ok, reason, _ = rm.can_trade(sig, 10_000.0)
    print(f"  20 trades done → {'✅' if ok else '❌'} {reason[:50] if not ok else ''}")
    trade_repo.set_trades(0)

    # ── TEST 8: Daily loss limit ─────────────────────────────────────
    header("8 · Daily Loss Limit (3% of ₹10000 = ₹300)")
    trade_repo.set_pnl(-200.0)
    ok, reason, _ = rm.can_trade(make_signal(), 10_000.0)
    print(f"  P&L -₹200 → {'✅' if ok else '❌'}")
    trade_repo.set_pnl(-300.0)
    ok, reason, _ = rm.can_trade(make_signal(), 10_000.0)
    print(f"  P&L -₹300 → {'✅' if ok else '❌'} {reason[:50] if not ok else ''}")
    trade_repo.set_pnl(0.0)

    # ── TEST 9: Max positions ────────────────────────────────────────
    header("9 · Max Positions (limit 4)")
    position_repo.clear()
    for i in range(3):
        position_repo.add_position("NIFTY", 24000 + i * 100, "CE", "2025-01-30")
    ok, _, _ = rm.can_trade(make_signal(), 10_000.0)
    print(f"  3 open positions → {'✅' if ok else '❌'}")
    position_repo.add_position("NIFTY", 24300, "CE", "2025-01-30")
    ok, reason, _ = rm.can_trade(make_signal(), 10_000.0)
    print(f"  4 open positions → {'✅' if ok else '❌'} {reason[:50] if not ok else ''}")
    position_repo.clear()

    # ── TEST 10: Duplicate position ──────────────────────────────────
    header("10 · Duplicate Position Check")
    position_repo.add_position("NIFTY", 24500, "CE", "2025-01-30")
    sig = make_signal(strike=24500, option_type="CE", expiry="2025-01-30")
    ok, reason, _ = rm.can_trade(sig, 10_000.0)
    print(f"  Same instrument → {'✅' if ok else '❌'} {reason[:60] if not ok else ''}")
    sig2 = make_signal(strike=24600, option_type="CE", expiry="2025-01-30")
    ok, reason, _ = rm.can_trade(sig2, 10_000.0)
    print(f"  Different strike → {'✅' if ok else '❌'}")
    position_repo.clear()

    # ── TEST 11: Circuit breaker integration ─────────────────────────
    header("11 · Circuit Breaker Integration")
    cb.manual_trigger("Test emergency stop")
    ok, reason, _ = rm.can_trade(make_signal(), 10_000.0)
    print(f"  CB triggered → {'✅' if ok else '❌'} {reason[:50] if not ok else ''}")
    cb.force_reset()
    ok, reason, _ = rm.can_trade(make_signal(), 10_000.0)
    print(f"  CB reset     → {'✅' if ok else '❌'}")

    # ── TEST 12: HOLD signal (no trade needed) ───────────────────────
    header("12 · HOLD Signal Passthrough")
    sig_hold = make_signal(action=constants.SIGNAL_HOLD)
    ok, reason, _ = rm.can_trade(sig_hold, 10_000.0)
    print(f"  HOLD signal → {'✅ (no trade)' if not ok else '❌ (should not trade)'}")

    # ── TEST 13: Full approved trade params ──────────────────────────
    header("13 · Approved Trade — Full Params")
    sig = make_signal(
        symbol="NIFTY",
        action=constants.SIGNAL_BUY,
        confidence=0.82,
        option_type="CE",
        strike=24500,
        premium=120.0,
        iv=18.0,
        expiry="2025-01-30",
    )
    ok, reason, params = rm.can_trade(sig, 10_000.0)
    if ok and params:
        print(json.dumps(params, indent=2, default=str))
    else:
        print(f"  Rejected: {reason}")

    # ── TEST 14: Risk summary ────────────────────────────────────────
    header("14 · Risk Summary")
    summary = rm.get_risk_summary()
    print(json.dumps(summary, indent=2, default=str))

    # ── TEST 15: Capital update ──────────────────────────────────────
    header("15 · Capital Updates")
    rm.update_capital(9_500.0)
    print(f"  Capital: {format_currency(rm.current_capital)}")
    rm.update_capital(10_200.0)
    print(f"  Capital: {format_currency(rm.current_capital)}")

    print(f"\n{'═' * 65}")
    print("  ✅  All risk manager scenarios tested!")
    print(f"{'═' * 65}\n")