"""
Paper Trading Engine - Simulated Trading Simulator
====================================================

The PaperEngine simulates real trading without risking actual money.
It tracks capital, executes simulated trades, monitors positions,
calculates P&L, and manages daily snapshots.

Responsibilities
----------------
1. Capital Management:
   - Track initial, current, and available capital
   - Deduct capital on trade entry
   - Add capital back on trade exit (with P&L)

2. Trade Execution:
   - Receive consensus signals from BrainCoordinator
   - Pass through RiskManager for approval
   - Execute via OrderManager

3. Position Monitoring:
   - Continuously check all open positions
   - Update current prices
   - Check SL/TP/Trailing/Time exits
   - Close positions when exit conditions met

4. Daily Lifecycle:
   - Reset counters at start of day
   - Save snapshots at end of day
   - Track daily P&L separately from total P&L

Capital Flow
------------
    INITIAL_CAPITAL (₹10,000)
           │
           ▼
    ┌──────────────────┐
    │ Available Capital│ ← Decreases on entry
    │    (₹10,000)     │ ← Increases on exit (with P&L)
    └──────────────────┘
           │
           ▼
    On Entry: available -= (premium × quantity)
    On Exit:  available += (exit_premium × quantity)
              P&L = exit_value - entry_value
"""

import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any

from config.settings import settings
from config import constants
from utils.helpers import (
    format_currency,
    format_pnl,
    format_percentage,
    get_ist_now,
    safe_divide,
)
from utils.indian_market import (
    is_market_open,
    should_close_all_positions,
)

logger = logging.getLogger(__name__)


class PaperEngine:
    """
    Paper trading simulator — executes trades without real money.
    
    Parameters
    ----------
    settings : object
        Application settings.
    market_data : MarketData
        Market data provider for fetching prices.
    order_manager : OrderManager
        Handles order lifecycle.
    risk_manager : RiskManager
        Validates trades against risk rules.
    circuit_breaker : CircuitBreaker
        Emergency stop mechanism.
    trade_repository : TradeRepository
        Trade persistence.
    position_repository : PositionRepository
        Position tracking.
    snapshot_repository : SnapshotRepository
        Daily snapshot persistence.
    
    Examples
    --------
        engine = PaperEngine(settings, market_data, order_mgr, risk_mgr, ...)
        trade = engine.execute_trade(consensus_signal)
        closed_trades = engine.update_positions()
        portfolio = engine.get_portfolio()
    """
    
    def __init__(
        self,
        settings,
        market_data,
        order_manager,
        risk_manager,
        circuit_breaker,
        trade_repository,
        position_repository,
        snapshot_repository=None,
    ) -> None:
        self._settings = settings
        self._market_data = market_data
        self._order_manager = order_manager
        self._risk_manager = risk_manager
        self._circuit_breaker = circuit_breaker
        self._trade_repo = trade_repository
        self._position_repo = position_repository
        self._snapshot_repo = snapshot_repository
        
        # ── Capital tracking ─────────────────────────────────────────
        self._initial_capital: float = float(
            getattr(settings, "INITIAL_CAPITAL", 10_000)
        )
        self._capital: float = self._initial_capital
        self._available_capital: float = self._initial_capital
        
        # ── P&L tracking ─────────────────────────────────────────────
        self._daily_pnl: float = 0.0
        self._total_pnl: float = 0.0
        
        # ── Trade counters ───────────────────────────────────────────
        self._trades_today: int = 0
        self._wins_today: int = 0
        self._losses_today: int = 0
        
        # ── State ────────────────────────────────────────────────────
        self._state: str = constants.BOT_STATE_STOPPED
        self._today: date = get_ist_now().date()
        
        # ── Track highest prices for trailing stops ──────────────────
        self._highest_prices: Dict[str, float] = {}
        
        logger.info(
            "PaperEngine initialised | Capital: %s | Available: %s",
            format_currency(self._capital),
            format_currency(self._available_capital),
        )
    
    # ================================================================ #
    #  PROPERTIES                                                       #
    # ================================================================ #
    
    @property
    def capital(self) -> float:
        """Total capital (initial + realised P&L)."""
        return self._capital
    
    @property
    def available_capital(self) -> float:
        """Capital available for new trades."""
        return self._available_capital
    
    @property
    def invested_amount(self) -> float:
        """Capital currently invested in open positions."""
        return self._capital - self._available_capital
    
    @property
    def daily_pnl(self) -> float:
        """Today's realised P&L."""
        return self._daily_pnl
    
    @property
    def total_pnl(self) -> float:
        """Total realised P&L since start."""
        return self._total_pnl
    
    @property
    def trades_today(self) -> int:
        """Number of trades executed today."""
        return self._trades_today
    
    @property
    def state(self) -> str:
        """Current engine state: RUNNING, STOPPED, PAUSED."""
        return self._state
    
    @state.setter
    def state(self, value: str) -> None:
        """Set engine state."""
        old_state = self._state
        self._state = value
        if old_state != value:
            logger.info("PaperEngine state: %s → %s", old_state, value)
    
    # ================================================================ #
    #  TRADE EXECUTION                                                  #
    # ================================================================ #
    
    def execute_trade(self, consensus_signal: dict) -> Optional[Any]:
        """
        Execute a trade based on brain consensus signal.
        
        Parameters
        ----------
        consensus_signal : dict
            Output from BrainCoordinator.analyze_symbol() containing:
            symbol, action, confidence, option_recommendation, reasoning.
        
        Returns
        -------
        Trade or None
            The executed Trade object if successful, None if rejected/failed.
        
        Flow
        ----
        1. Extract option details from signal
        2. Fetch current premium from market data
        3. Run through risk manager
        4. If approved, create and execute order
        5. Update capital and counters
        """
        symbol = consensus_signal.get("symbol", "UNKNOWN")
        action = consensus_signal.get("action", constants.SIGNAL_HOLD)
        confidence = consensus_signal.get("confidence", 0.0)
        
        # Skip HOLD signals
        if action == constants.SIGNAL_HOLD:
            logger.debug("%s: HOLD signal — no trade", symbol)
            return None
        
        # ── Step 1: Extract option recommendation ────────────────────
        option_rec = consensus_signal.get("option_recommendation", {})
        option_type = option_rec.get("type", constants.OPTION_TYPE_CALL)
        strike = option_rec.get("strike_preference", 0)
        expiry = option_rec.get("expiry", "")
        
        # If strike is 0, we need to get ATM strike
        if strike == 0:
            try:
                quote = self._market_data.get_quote(symbol)
                spot_price = quote.get("ltp", 0)
                
                # Calculate ATM strike
                if "BANKNIFTY" in symbol.upper():
                    strike_step = constants.STRIKE_STEP_BANKNIFTY
                else:
                    strike_step = constants.STRIKE_STEP_NIFTY
                
                strike = round(spot_price / strike_step) * strike_step
                
            except Exception as e:
                logger.error("Could not determine ATM strike: %s", e)
                return None
        
        # ── Step 2: Fetch current premium ────────────────────────────
        try:
            option_quote = self._market_data.get_option_quote(
                symbol=symbol,
                strike=strike,
                option_type=option_type,
                expiry=expiry,
            )
            premium = option_quote.get("ltp", 0)
            iv = option_quote.get("iv", 0)
            
        except Exception as e:
            logger.error(
                "Could not fetch option quote for %s %s %s: %s",
                symbol, strike, option_type, e
            )
            return None
        
        if premium <= 0:
            logger.warning(
                "Invalid premium (%.2f) for %s %s %s — skipping",
                premium, symbol, strike, option_type
            )
            return None
        
        # ── Step 3: Enhance signal with premium/IV for risk check ────
        enhanced_signal = consensus_signal.copy()
        if "option_recommendation" not in enhanced_signal:
            enhanced_signal["option_recommendation"] = {}
        
        enhanced_signal["option_recommendation"]["strike_preference"] = strike
        enhanced_signal["option_recommendation"]["premium"] = premium
        enhanced_signal["option_recommendation"]["iv"] = iv
        enhanced_signal["option_recommendation"]["expiry"] = expiry
        
        # ── Step 4: Run through risk manager ─────────────────────────
        approved, reason, trade_params = self._risk_manager.can_trade(
            signal=enhanced_signal,
            current_capital=self._available_capital,
        )
        
        if not approved:
            logger.info(
                "❌ Trade REJECTED | %s %s %s @ ₹%.2f | Reason: %s",
                symbol, strike, option_type, premium, reason
            )
            return None
        
        # ── Step 5: Create order ─────────────────────────────────────
        try:
            order = self._order_manager.create_order(trade_params)
        except Exception as e:
            logger.error("Failed to create order: %s", e)
            return None
        
        # ── Step 6: Execute order ────────────────────────────────────
        try:
            trade = self._order_manager.execute_order(order)
        except Exception as e:
            logger.error("Failed to execute order: %s", e)
            return None
        
        if trade is None:
            logger.error("Order execution returned None")
            return None
        
        # ── Step 7: Update capital ───────────────────────────────────
        entry_price = float(getattr(trade, "entry_price", 0))
        quantity = int(getattr(trade, "quantity", 0))
        invested = entry_price * quantity
        
        self._available_capital -= invested
        
        # Track highest price for trailing stop
        trade_id = getattr(trade, "trade_id", "")
        self._highest_prices[trade_id] = entry_price
        
        # ── Step 8: Update counters ──────────────────────────────────
        self._trades_today += 1
        
        # ── Step 9: Update risk manager capital ──────────────────────
        self._risk_manager.update_capital(self._available_capital)
        
        instrument = getattr(trade, "instrument", f"{symbol} {strike} {option_type}")
        
        logger.info(
            "🎯 TRADE EXECUTED | %s | %s @ ₹%.2f | "
            "Qty: %d | Invested: %s | Available: %s",
            instrument,
            getattr(trade, "side", "BUY"),
            entry_price,
            quantity,
            format_currency(invested),
            format_currency(self._available_capital),
        )
        
        return trade
    
    # ================================================================ #
    #  POSITION MONITORING                                              #
    # ================================================================ #
    
    def update_positions(self) -> List[Any]:
        """
        Check all open positions and close if exit conditions met.
        
        Called every scan interval to:
        1. Fetch current prices for all open positions
        2. Update highest price (for trailing stops)
        3. Check exit conditions (SL/TP/TRAIL/TIME)
        4. Close positions that hit exit conditions
        
        Returns
        -------
        list
            List of closed Trade objects (empty if none closed).
        """
        closed_trades = []
        
        try:
            open_trades = self._trade_repo.get_open_trades()
            
            if not open_trades:
                return closed_trades
            
            if not isinstance(open_trades, list):
                open_trades = list(open_trades)
            
        except Exception as e:
            logger.error("Error fetching open trades: %s", e)
            return closed_trades
        
        for trade in open_trades:
            try:
                closed = self._check_and_update_position(trade)
                if closed:
                    closed_trades.append(closed)
            except Exception as e:
                trade_id = getattr(trade, "trade_id", "?")
                logger.error(
                    "Error updating position %s: %s",
                    trade_id[:8] if trade_id else "?",
                    e
                )
                continue
        
        return closed_trades
    
    def _check_and_update_position(self, trade) -> Optional[Any]:
        """
        Check single position and close if needed.
        
        Returns closed Trade or None.
        """
        trade_id = getattr(trade, "trade_id", "")
        symbol = getattr(trade, "symbol", "")
        strike = getattr(trade, "strike", 0)
        option_type = getattr(trade, "option_type", "CE")
        expiry = getattr(trade, "expiry", "")
        entry_price = float(getattr(trade, "entry_price", 0))
        quantity = int(getattr(trade, "quantity", 0))
        
        # ── Step 1: Fetch current price ──────────────────────────────
        try:
            quote = self._market_data.get_option_quote(
                symbol=symbol,
                strike=strike,
                option_type=option_type,
                expiry=expiry,
            )
            current_price = quote.get("ltp", 0)
            
        except Exception as e:
            logger.warning(
                "Could not fetch price for %s: %s — using last known",
                getattr(trade, "instrument", "?"), e
            )
            current_price = float(getattr(trade, "current_price", entry_price))
        
        if current_price <= 0:
            return None
        
        # ── Step 2: Update position with current price ───────────────
        try:
            self._position_repo.update_position_price(trade_id, current_price)
        except Exception as e:
            logger.debug("Could not update position price: %s", e)
        
        # ── Step 3: Update highest price for trailing stop ───────────
        highest_price = self._highest_prices.get(trade_id, entry_price)
        
        if current_price > highest_price:
            highest_price = current_price
            self._highest_prices[trade_id] = highest_price
            
            # Update trade object with new highest
            try:
                # If trade repo has update method
                if hasattr(self._trade_repo, "update_trade"):
                    self._trade_repo.update_trade(trade_id, {"highest_price": highest_price})
            except Exception:
                pass
        
        # Create a trade-like object with highest_price for risk check
        class TradeWithHighest:
            pass
        
        trade_obj = TradeWithHighest()
        trade_obj.entry_price = entry_price
        trade_obj.stop_loss = float(getattr(trade, "stop_loss", 0))
        trade_obj.take_profit = float(getattr(trade, "take_profit", 0))
        trade_obj.highest_price = highest_price
        
        # ── Step 4: Check exit conditions ────────────────────────────
        should_exit, exit_reason = self._risk_manager.check_position_exit(
            trade=trade_obj,
            current_price=current_price,
        )
        
        if should_exit:
            return self.close_position(trade, current_price, exit_reason)
        
        # Log position status periodically (every 10th check)
        if hasattr(self, "_position_check_count"):
            self._position_check_count += 1
        else:
            self._position_check_count = 1
        
        if self._position_check_count % 10 == 0:
            pnl = (current_price - entry_price) * quantity
            pnl_pct = safe_divide(current_price - entry_price, entry_price, 0) * 100
            
            logger.debug(
                "📊 Position | %s | Entry: ₹%.2f | Current: ₹%.2f | "
                "P&L: %s (%.1f%%) | High: ₹%.2f",
                getattr(trade, "instrument", "?"),
                entry_price,
                current_price,
                format_pnl(pnl),
                pnl_pct,
                highest_price,
            )
        
        return None
    
    # ================================================================ #
    #  POSITION CLOSING                                                 #
    # ================================================================ #
    
    def close_position(
        self,
        trade,
        exit_price: float,
        reason: str,
    ) -> Optional[Any]:
        """
        Close a specific position.
        
        Parameters
        ----------
        trade : Trade
            The trade/position to close.
        exit_price : float
            The exit price (current premium).
        reason : str
            Exit reason: 'SL', 'TP', 'TRAIL', 'TIME', 'MANUAL'.
        
        Returns
        -------
        Trade or None
            The closed Trade object with P&L calculated.
        """
        trade_id = getattr(trade, "trade_id", "")
        entry_price = float(getattr(trade, "entry_price", 0))
        quantity = int(getattr(trade, "quantity", 0))
        instrument = getattr(trade, "instrument", "?")
        
        # ── Step 1: Close via order manager ──────────────────────────
        try:
            closed_trade = self._order_manager.close_order(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_reason=reason,
            )
        except Exception as e:
            logger.error("Failed to close order %s: %s", trade_id[:8], e)
            return None
        
        if closed_trade is None:
            return None
        
        # ── Step 2: Calculate P&L ────────────────────────────────────
        pnl = (exit_price - entry_price) * quantity
        pnl_pct = safe_divide(exit_price - entry_price, entry_price, 0) * 100
        
        # ── Step 3: Update capital ───────────────────────────────────
        exit_value = exit_price * quantity
        self._available_capital += exit_value
        self._capital += pnl
        
        # ── Step 4: Update P&L tracking ──────────────────────────────
        self._daily_pnl += pnl
        self._total_pnl += pnl
        
        # ── Step 5: Update win/loss counters ─────────────────────────
        if pnl >= 0:
            self._wins_today += 1
        else:
            self._losses_today += 1
        
        # ── Step 6: Record in circuit breaker ────────────────────────
        try:
            self._circuit_breaker.record_trade_result(pnl)
        except Exception as e:
            logger.warning("Could not record trade result in circuit breaker: %s", e)
        
        # ── Step 7: Update risk manager capital ──────────────────────
        self._risk_manager.update_capital(self._available_capital)
        
        # ── Step 8: Clean up highest price tracking ──────────────────
        if trade_id in self._highest_prices:
            del self._highest_prices[trade_id]
        
        # ── Step 9: Log the close ────────────────────────────────────
        emoji = "🟢" if pnl >= 0 else "🔴"
        
        logger.info(
            "%s POSITION CLOSED | %s | %s | Entry: ₹%.2f → Exit: ₹%.2f | "
            "P&L: %s (%.1f%%) | Capital: %s",
            emoji,
            instrument,
            reason,
            entry_price,
            exit_price,
            format_pnl(pnl),
            pnl_pct,
            format_currency(self._capital),
        )
        
        return closed_trade
    
    def close_all_positions(self, reason: str = "MANUAL") -> List[Any]:
        """
        Close ALL open positions immediately.
        
        Used for:
        - End of day (TIME)
        - Emergency stop (EMERGENCY)
        - Manual close all (/closeall)
        
        Parameters
        ----------
        reason : str
            Reason for closing all: 'TIME', 'EMERGENCY', 'MANUAL'.
        
        Returns
        -------
        list
            List of closed Trade objects.
        """
        closed_trades = []
        
        try:
            open_trades = self._trade_repo.get_open_trades()
            
            if not open_trades:
                logger.info("No open positions to close")
                return closed_trades
            
            if not isinstance(open_trades, list):
                open_trades = list(open_trades)
            
            logger.info(
                "🔄 Closing ALL %d open positions | Reason: %s",
                len(open_trades),
                reason,
            )
            
        except Exception as e:
            logger.error("Error fetching open trades for close all: %s", e)
            return closed_trades
        
        for trade in open_trades:
            try:
                # Get current price
                symbol = getattr(trade, "symbol", "")
                strike = getattr(trade, "strike", 0)
                option_type = getattr(trade, "option_type", "CE")
                expiry = getattr(trade, "expiry", "")
                
                try:
                    quote = self._market_data.get_option_quote(
                        symbol=symbol,
                        strike=strike,
                        option_type=option_type,
                        expiry=expiry,
                    )
                    current_price = quote.get("ltp", 0)
                except Exception:
                    current_price = float(getattr(trade, "current_price", 0))
                    if current_price <= 0:
                        current_price = float(getattr(trade, "entry_price", 0))
                
                if current_price > 0:
                    closed = self.close_position(trade, current_price, reason)
                    if closed:
                        closed_trades.append(closed)
                
            except Exception as e:
                trade_id = getattr(trade, "trade_id", "?")
                logger.error(
                    "Error closing position %s: %s",
                    trade_id[:8] if trade_id else "?",
                    e,
                )
                continue
        
        logger.info(
            "✅ Closed %d / %d positions | Daily P&L: %s | Total P&L: %s",
            len(closed_trades),
            len(open_trades),
            format_pnl(self._daily_pnl),
            format_pnl(self._total_pnl),
        )
        
        return closed_trades
    
    # ================================================================ #
    #  PORTFOLIO & REPORTING                                            #
    # ================================================================ #
    
    def get_portfolio(self) -> dict:
        """
        Get current portfolio status.
        
        Returns
        -------
        dict
            Complete portfolio snapshot including capital, positions, P&L.
        """
        # Get open positions
        open_positions = []
        unrealised_pnl = 0.0
        
        try:
            open_trades = self._trade_repo.get_open_trades()
            
            if open_trades:
                if not isinstance(open_trades, list):
                    open_trades = list(open_trades)
                
                for trade in open_trades:
                    try:
                        symbol = getattr(trade, "symbol", "")
                        strike = getattr(trade, "strike", 0)
                        option_type = getattr(trade, "option_type", "CE")
                        expiry = getattr(trade, "expiry", "")
                        entry_price = float(getattr(trade, "entry_price", 0))
                        quantity = int(getattr(trade, "quantity", 0))
                        instrument = getattr(trade, "instrument", f"{symbol} {strike} {option_type}")
                        
                        # Fetch current price
                        try:
                            quote = self._market_data.get_option_quote(
                                symbol=symbol,
                                strike=strike,
                                option_type=option_type,
                                expiry=expiry,
                            )
                            current_price = quote.get("ltp", entry_price)
                        except Exception:
                            current_price = entry_price
                        
                        pnl = (current_price - entry_price) * quantity
                        pnl_pct = safe_divide(current_price - entry_price, entry_price, 0) * 100
                        unrealised_pnl += pnl
                        
                        open_positions.append({
                            "trade_id": getattr(trade, "trade_id", ""),
                            "instrument": instrument,
                            "side": getattr(trade, "side", "BUY"),
                            "quantity": quantity,
                            "entry_price": entry_price,
                            "current_price": current_price,
                            "stop_loss": float(getattr(trade, "stop_loss", 0)),
                            "take_profit": float(getattr(trade, "take_profit", 0)),
                            "pnl": round(pnl, 2),
                            "pnl_pct": round(pnl_pct, 2),
                            "entry_time": str(getattr(trade, "entry_time", "")),
                        })
                        
                    except Exception as e:
                        logger.debug("Error processing position: %s", e)
                        continue
        
        except Exception as e:
            logger.error("Error fetching portfolio positions: %s", e)
        
        # Calculate totals
        total_value = self._capital + unrealised_pnl
        total_pnl_pct = safe_divide(
            total_value - self._initial_capital,
            self._initial_capital,
            0,
        ) * 100
        
        daily_pnl_pct = safe_divide(
            self._daily_pnl,
            self._initial_capital,
            0,
        ) * 100
        
        # Win rate
        total_closed = self._wins_today + self._losses_today
        win_rate = safe_divide(self._wins_today, total_closed, 0) * 100
        
        return {
            "timestamp": get_ist_now().isoformat(),
            "capital": {
                "initial": round(self._initial_capital, 2),
                "current": round(self._capital, 2),
                "available": round(self._available_capital, 2),
                "invested": round(self.invested_amount, 2),
                "total_value": round(total_value, 2),
            },
            "pnl": {
                "realised": round(self._total_pnl, 2),
                "unrealised": round(unrealised_pnl, 2),
                "total": round(self._total_pnl + unrealised_pnl, 2),
                "total_pct": round(total_pnl_pct, 2),
                "daily": round(self._daily_pnl, 2),
                "daily_pct": round(daily_pnl_pct, 2),
            },
            "positions": {
                "open_count": len(open_positions),
                "open": open_positions,
            },
            "trades": {
                "today": self._trades_today,
                "wins": self._wins_today,
                "losses": self._losses_today,
                "win_rate": round(win_rate, 1),
            },
            "state": self._state,
        }
    
    def get_daily_summary(self) -> dict:
        """
        Get end-of-day summary.
        
        Returns
        -------
        dict
            Daily trading summary with stats and metrics.
        """
        # Get today's closed trades for detailed stats
        best_trade_pnl = 0.0
        worst_trade_pnl = 0.0
        
        try:
            trades_today = self._trade_repo.get_trades_today()
            
            if trades_today and isinstance(trades_today, list):
                for trade in trades_today:
                    pnl = float(getattr(trade, "pnl", 0))
                    if pnl > best_trade_pnl:
                        best_trade_pnl = pnl
                    if pnl < worst_trade_pnl:
                        worst_trade_pnl = pnl
        
        except Exception as e:
            logger.debug("Error fetching today's trades: %s", e)
        
        total_closed = self._wins_today + self._losses_today
        win_rate = safe_divide(self._wins_today, total_closed, 0) * 100
        
        # Calculate max drawdown (simplified — from starting capital)
        max_drawdown = 0.0
        if self._capital < self._initial_capital:
            max_drawdown = safe_divide(
                self._initial_capital - self._capital,
                self._initial_capital,
                0,
            ) * 100
        
        return {
            "date": self._today.isoformat(),
            "starting_capital": round(self._initial_capital, 2),
            "ending_capital": round(self._capital, 2),
            "available_capital": round(self._available_capital, 2),
            "total_pnl": round(self._daily_pnl, 2),
            "total_pnl_pct": round(
                safe_divide(self._daily_pnl, self._initial_capital, 0) * 100, 2
            ),
            "trades_count": self._trades_today,
            "wins": self._wins_today,
            "losses": self._losses_today,
            "win_rate": round(win_rate, 1),
            "best_trade": round(best_trade_pnl, 2),
            "worst_trade": round(worst_trade_pnl, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "circuit_breaker_triggered": self._circuit_breaker.triggered,
        }
    
    # ================================================================ #
    #  DAILY LIFECYCLE                                                  #
    # ================================================================ #
    
    def save_daily_snapshot(self) -> bool:
        """
        Save end-of-day snapshot to database.
        
        Returns
        -------
        bool
            True if saved successfully, False otherwise.
        """
        if self._snapshot_repo is None:
            logger.warning("Snapshot repository not available — skipping save")
            return False
        
        try:
            summary = self.get_daily_summary()
            
            snapshot_data = {
                "date": self._today,
                "starting_capital": summary["starting_capital"],
                "ending_capital": summary["ending_capital"],
                "daily_pnl": summary["total_pnl"],
                "daily_pnl_pct": summary["total_pnl_pct"],
                "trades_count": summary["trades_count"],
                "wins": summary["wins"],
                "losses": summary["losses"],
                "win_rate": summary["win_rate"],
                "best_trade": summary["best_trade"],
                "worst_trade": summary["worst_trade"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
            }
            
            self._snapshot_repo.save_daily_snapshot(snapshot_data)
            
            logger.info(
                "📸 Daily snapshot saved | Date: %s | P&L: %s | Trades: %d",
                self._today.isoformat(),
                format_pnl(summary["total_pnl"]),
                summary["trades_count"],
            )
            
            return True
        
        except Exception as e:
            logger.error("Failed to save daily snapshot: %s", e)
            return False
    
    def start_new_day(self) -> None:
        """
        Reset counters for a new trading day.
        
        Called at market open each morning.
        """
        previous_day = self._today
        previous_pnl = self._daily_pnl
        previous_trades = self._trades_today
        
        # Update date
        self._today = get_ist_now().date()
        
        # Reset daily counters
        self._daily_pnl = 0.0
        self._trades_today = 0
        self._wins_today = 0
        self._losses_today = 0
        
        # Reset circuit breaker daily counters
        try:
            self._circuit_breaker.start_new_day()
        except Exception as e:
            logger.warning("Error resetting circuit breaker: %s", e)
        
        logger.info(
            "🌅 NEW TRADING DAY | Date: %s | "
            "Previous: %s | Trades: %d | P&L: %s | "
            "Starting Capital: %s",
            self._today.isoformat(),
            previous_day.isoformat(),
            previous_trades,
            format_pnl(previous_pnl),
            format_currency(self._capital),
        )
    
    # ================================================================ #
    #  UTILITY METHODS                                                  #
    # ================================================================ #
    
    def get_open_position_count(self) -> int:
        """Get count of open positions."""
        try:
            open_trades = self._trade_repo.get_open_trades()
            if open_trades is None:
                return 0
            return len(list(open_trades))
        except Exception:
            return 0
    
    def has_open_positions(self) -> bool:
        """Check if there are any open positions."""
        return self.get_open_position_count() > 0
    
    def reset(self) -> None:
        """
        Reset engine to initial state.
        
        WARNING: This clears all tracking but NOT the database.
        """
        self._capital = self._initial_capital
        self._available_capital = self._initial_capital
        self._daily_pnl = 0.0
        self._total_pnl = 0.0
        self._trades_today = 0
        self._wins_today = 0
        self._losses_today = 0
        self._highest_prices.clear()
        self._today = get_ist_now().date()
        
        logger.info(
            "🔄 PaperEngine RESET | Capital: %s",
            format_currency(self._capital),
        )
    
    # ================================================================ #
    #  DUNDER METHODS                                                   #
    # ================================================================ #
    
    def __repr__(self) -> str:
        return (
            f"PaperEngine("
            f"capital={format_currency(self._capital)}, "
            f"available={format_currency(self._available_capital)}, "
            f"daily_pnl={format_pnl(self._daily_pnl)}, "
            f"positions={self.get_open_position_count()}, "
            f"state={self._state})"
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
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    
    print("\n" + "=" * 65)
    print("  PAPER ENGINE - Standalone Test")
    print("=" * 65)
    
    # ── Mock classes ─────────────────────────────────────────────────
    class MockSettings:
        PAPER_TRADING = True
        INITIAL_CAPITAL = 10_000.0
        MAX_CAPITAL_PER_TRADE = 2_500.0
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
    
    class MockMarketData:
        def __init__(self):
            self._prices = {"NIFTY": 24500, "BANKNIFTY": 52000}
            self._option_price = 120.0
        
        def get_quote(self, symbol):
            return {"ltp": self._prices.get(symbol, 24500)}
        
        def get_option_quote(self, symbol, strike, option_type, expiry):
            return {"ltp": self._option_price, "iv": 18.0}
        
        def set_option_price(self, price):
            self._option_price = price
    
    class MockTrade:
        def __init__(self, data):
            for key, value in data.items():
                setattr(self, key, value)
    
    class MockTradeRepo:
        def __init__(self):
            self._trades = {}
        
        def save_trade(self, data):
            trade = MockTrade(data)
            self._trades[data.get("trade_id", "")] = trade
            return trade
        
        def get_trade(self, trade_id):
            return self._trades.get(trade_id)
        
        def get_open_trades(self):
            return [t for t in self._trades.values()
                    if getattr(t, "status", "") in ["OPEN", constants.ORDER_STATUS_OPEN]]
        
        def get_trades_today(self):
            return list(self._trades.values())
        
        def close_trade(self, trade_id, exit_price, exit_reason):
            trade = self._trades.get(trade_id)
            if trade:
                trade.status = "CLOSED"
                trade.exit_price = exit_price
                trade.exit_reason = exit_reason
                entry = getattr(trade, "entry_price", 0)
                qty = getattr(trade, "quantity", 0)
                trade.pnl = (exit_price - entry) * qty
            return trade
    
    class MockPositionRepo:
        def __init__(self):
            self._positions = {}
        
        def save_position(self, data):
            self._positions[data.get("trade_id", "")] = data
        
        def update_position_price(self, trade_id, price):
            if trade_id in self._positions:
                self._positions[trade_id]["current_price"] = price
        
        def close_position(self, trade_id):
            if trade_id in self._positions:
                del self._positions[trade_id]
        
        def get_open_positions(self):
            return list(self._positions.values())
    
    class MockSnapshotRepo:
        def __init__(self):
            self._snapshots = []
        
        def save_daily_snapshot(self, data):
            self._snapshots.append(data)
    
    class MockOrderManager:
        def __init__(self, trade_repo, position_repo):
            self._trade_repo = trade_repo
            self._position_repo = position_repo
            self._order_count = 0
        
        def create_order(self, trade_params):
            self._order_count += 1
            return {
                "order_id": f"ORD{self._order_count:04d}",
                "trade_id": trade_params.get("trade_id", f"TRD{self._order_count:04d}"),
                **trade_params,
            }
        
        def execute_order(self, order):
            trade_data = {
                "trade_id": order.get("trade_id"),
                "symbol": order.get("symbol"),
                "instrument": order.get("instrument"),
                "strike": order.get("strike"),
                "option_type": order.get("option_type"),
                "expiry": order.get("expiry"),
                "side": order.get("side", "BUY"),
                "quantity": order.get("quantity"),
                "entry_price": order.get("entry_price", order.get("price", 0)),
                "stop_loss": order.get("stop_loss"),
                "take_profit": order.get("take_profit"),
                "status": "OPEN",
            }
            return self._trade_repo.save_trade(trade_data)
        
        def close_order(self, trade_id, exit_price, exit_reason):
            return self._trade_repo.close_trade(trade_id, exit_price, exit_reason)
    
    class MockRiskManager:
        def __init__(self):
            self._capital = 10_000.0
        
        def can_trade(self, signal, current_capital):
            # Always approve for testing
            option_rec = signal.get("option_recommendation", {})
            return True, "Approved", {
                "trade_id": f"TRD{hash(str(signal)) % 10000:04d}",
                "symbol": signal.get("symbol", "NIFTY"),
                "instrument": f"{signal.get('symbol', 'NIFTY')} {option_rec.get('strike_preference', 24500)} {option_rec.get('type', 'CE')}",
                "strike": option_rec.get("strike_preference", 24500),
                "option_type": option_rec.get("type", "CE"),
                "expiry": option_rec.get("expiry", "2025-01-30"),
                "side": "BUY",
                "quantity": 25,
                "lots": 1,
                "entry_price": option_rec.get("premium", 120.0),
                "stop_loss": 84.0,
                "take_profit": 180.0,
            }
        
        def check_position_exit(self, trade, current_price):
            entry = getattr(trade, "entry_price", 0)
            sl = getattr(trade, "stop_loss", 0)
            tp = getattr(trade, "take_profit", 0)
            
            if current_price <= sl:
                return True, "SL"
            if current_price >= tp:
                return True, "TP"
            return False, ""
        
        def update_capital(self, capital):
            self._capital = capital
    
    class MockCircuitBreaker:
        def __init__(self):
            self.triggered = False
        
        def record_trade_result(self, pnl):
            pass
        
        def start_new_day(self):
            pass
    
    # ── Create components ────────────────────────────────────────────
    mock_settings = MockSettings()
    market_data = MockMarketData()
    trade_repo = MockTradeRepo()
    position_repo = MockPositionRepo()
    snapshot_repo = MockSnapshotRepo()
    order_manager = MockOrderManager(trade_repo, position_repo)
    risk_manager = MockRiskManager()
    circuit_breaker = MockCircuitBreaker()
    
    engine = PaperEngine(
        settings=mock_settings,
        market_data=market_data,
        order_manager=order_manager,
        risk_manager=risk_manager,
        circuit_breaker=circuit_breaker,
        trade_repository=trade_repo,
        position_repository=position_repo,
        snapshot_repository=snapshot_repo,
    )
    
    print(f"\n  {engine}")
    
    # ── Test 1: Execute Trade ────────────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 1: Execute Trade")
    print("-" * 65)
    
    signal = {
        "symbol": "NIFTY",
        "action": constants.SIGNAL_BUY,
        "confidence": 0.75,
        "reasoning": "RSI oversold",
        "option_recommendation": {
            "type": "CE",
            "strike_preference": 24500,
            "expiry": "2025-01-30",
        },
    }
    
    trade = engine.execute_trade(signal)
    
    if trade:
        print(f"\n  Trade executed: {trade.instrument}")
        print(f"  Entry: ₹{trade.entry_price}")
        print(f"  Capital: {format_currency(engine.capital)}")
        print(f"  Available: {format_currency(engine.available_capital)}")
        print(f"  Trades today: {engine.trades_today}")
    
    # ── Test 2: Update Positions (no exit) ───────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 2: Update Positions (price at 130, no exit)")
    print("-" * 65)
    
    market_data.set_option_price(130.0)  # Price moved up
    closed = engine.update_positions()
    
    print(f"\n  Closed positions: {len(closed)}")
    print(f"  Open positions: {engine.get_open_position_count()}")
    
    # ── Test 3: Update Positions (TP hit) ────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 3: Update Positions (price at 185, TP hit)")
    print("-" * 65)
    
    market_data.set_option_price(185.0)  # Above TP
    closed = engine.update_positions()
    
    print(f"\n  Closed positions: {len(closed)}")
    if closed:
        for c in closed:
            print(f"    - {c.instrument}: {format_pnl(c.pnl)}")
    print(f"  Open positions: {engine.get_open_position_count()}")
    print(f"  Daily P&L: {format_pnl(engine.daily_pnl)}")
    print(f"  Capital: {format_currency(engine.capital)}")
    
    # ── Test 4: Portfolio ────────────────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 4: Get Portfolio")
    print("-" * 65)
    
    portfolio = engine.get_portfolio()
    print(f"\n  Capital: {format_currency(portfolio['capital']['current'])}")
    print(f"  Available: {format_currency(portfolio['capital']['available'])}")
    print(f"  Realised P&L: {format_pnl(portfolio['pnl']['realised'])}")
    print(f"  Trades today: {portfolio['trades']['today']}")
    print(f"  Wins: {portfolio['trades']['wins']}")
    
    # ── Test 5: Multiple Trades + SL ─────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 5: Execute another trade and hit SL")
    print("-" * 65)
    
    market_data.set_option_price(100.0)
    
    signal2 = {
        "symbol": "BANKNIFTY",
        "action": constants.SIGNAL_BUY,
        "confidence": 0.80,
        "option_recommendation": {
            "type": "PE",
            "strike_preference": 52000,
            "expiry": "2025-01-30",
        },
    }
    
    trade2 = engine.execute_trade(signal2)
    if trade2:
        print(f"\n  Trade 2 executed: {trade2.instrument}")
    
    # Hit SL
    market_data.set_option_price(75.0)
    closed = engine.update_positions()
    
    if closed:
        for c in closed:
            print(f"  SL hit: {c.instrument}: {format_pnl(c.pnl)}")
    
    print(f"\n  Daily P&L: {format_pnl(engine.daily_pnl)}")
    print(f"  Wins: {engine._wins_today} | Losses: {engine._losses_today}")
    
    # ── Test 6: Daily Summary ────────────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 6: Daily Summary")
    print("-" * 65)
    
    summary = engine.get_daily_summary()
    print(f"\n  Date: {summary['date']}")
    print(f"  Trades: {summary['trades_count']}")
    print(f"  Wins: {summary['wins']} | Losses: {summary['losses']}")
    print(f"  Win Rate: {summary['win_rate']}%")
    print(f"  P&L: {format_pnl(summary['total_pnl'])}")
    print(f"  Best Trade: {format_pnl(summary['best_trade'])}")
    print(f"  Worst Trade: {format_pnl(summary['worst_trade'])}")
    
    # ── Test 7: Save Snapshot ────────────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 7: Save Daily Snapshot")
    print("-" * 65)
    
    saved = engine.save_daily_snapshot()
    print(f"\n  Snapshot saved: {saved}")
    print(f"  Snapshots in repo: {len(snapshot_repo._snapshots)}")
    
    # ── Test 8: New Day ──────────────────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 8: Start New Day")
    print("-" * 65)
    
    print(f"\n  Before: Daily P&L = {format_pnl(engine.daily_pnl)}")
    print(f"  Before: Trades today = {engine.trades_today}")
    
    engine.start_new_day()
    
    print(f"  After: Daily P&L = {format_pnl(engine.daily_pnl)}")
    print(f"  After: Trades today = {engine.trades_today}")
    print(f"  Capital preserved: {format_currency(engine.capital)}")
    
    # ── Test 9: Close All Positions ──────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 9: Close All Positions")
    print("-" * 65)
    
    # Open a few positions first
    market_data.set_option_price(110.0)
    engine.execute_trade(signal)
    engine.execute_trade(signal2)
    
    print(f"\n  Open positions: {engine.get_open_position_count()}")
    
    closed_all = engine.close_all_positions("TIME")
    
    print(f"  Closed: {len(closed_all)}")
    print(f"  Open now: {engine.get_open_position_count()}")
    
    print("\n" + "=" * 65)
    print("  ✅ All PaperEngine tests completed!")
    print("=" * 65 + "\n")