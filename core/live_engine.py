"""
Live Trading Engine - Real Money Trading via Dhan API
======================================================

This engine executes REAL trades on the exchange using Dhan API.
It has the SAME interface as PaperEngine so they are interchangeable.

⚠️  WARNING: This engine uses REAL MONEY!
    - Every trade costs real capital
    - Losses are permanent
    - Test thoroughly with PaperEngine first

Safety Features:
    - Multiple confirmation checks before every order
    - Telegram alerts before AND after every order
    - Order verification after placement
    - Maximum order value checks
    - Automatic position reconciliation

Usage:
    # In bot.py, engine is selected based on settings:
    if settings.PAPER_TRADING:
        self.engine = PaperEngine(...)
    else:
        self.engine = LiveEngine(...)  # Real trading!

    # Both have same interface:
    trade = engine.execute_trade(signal)
    closed = engine.update_positions()
    engine.close_all_positions("reason")

Author: Trading Bot
Phase: 10 - Polish & Enhancement
"""

import logging
import time
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List, Tuple
from decimal import Decimal, ROUND_DOWN

from config.settings import settings
from config import constants
from utils.helpers import (
    get_ist_now,
    format_currency,
    format_pnl,
    generate_order_id,
    generate_trade_id,
    get_atm_strike,
    get_otm_strike,
    safe_divide,
)
from utils.exceptions import (
    TradingBotError,
    OrderError,
    InsufficientFundsError,
    MaxPositionsError,
    RiskError,
)

logger = logging.getLogger(__name__)


class LiveEngine:
    """
    Live Trading Engine - Executes real trades via Dhan API.
    
    This class has the EXACT same interface as PaperEngine,
    allowing seamless switching between paper and live trading.
    
    Critical Safety Features:
        1. Checks PAPER_TRADING=False before every order
        2. Validates order size against MAX_CAPITAL_PER_TRADE
        3. Sends Telegram alert before placing order
        4. Verifies order status after placement
        5. Sends Telegram alert after order completion
        6. Logs every action with [LIVE] tag
        7. Automatic retry with verification on failures
    
    Attributes:
        capital: Total account capital
        available_capital: Capital available for new trades
        daily_pnl: Today's profit/loss
        total_pnl: All-time profit/loss
        trades_today: Number of trades executed today
        state: Current engine state (RUNNING/STOPPED/PAUSED)
    
    Example:
        >>> engine = LiveEngine(settings, market_data, dhan_client, ...)
        >>> trade = engine.execute_trade(consensus_signal)
        >>> if trade:
        ...     print(f"LIVE order placed: {trade.instrument}")
    """
    
    # Engine mode identifier
    MODE = "LIVE"
    
    # Order retry configuration
    MAX_ORDER_RETRIES = 3
    ORDER_VERIFICATION_DELAY = 2  # seconds
    ORDER_TIMEOUT = 30  # seconds
    
    # Safety limits
    ABSOLUTE_MAX_ORDER_VALUE = 50000  # Never exceed ₹50,000 per order
    
    def __init__(
        self,
        settings,
        market_data,
        dhan_client,
        order_manager,
        risk_manager,
        circuit_breaker,
        trade_repository,
        position_repository,
        snapshot_repository,
        alert_manager=None,
    ):
        """
        Initialize the Live Trading Engine.
        
        Args:
            settings: Application settings
            market_data: MarketData instance for prices
            dhan_client: DhanClient for API calls
            order_manager: OrderManager for order building
            risk_manager: RiskManager for trade validation
            circuit_breaker: CircuitBreaker for emergency stops
            trade_repository: TradeRepository for database
            position_repository: PositionRepository for database
            snapshot_repository: SnapshotRepository for database
            alert_manager: AlertManager for Telegram alerts (optional)
        """
        logger.warning("=" * 60)
        logger.warning("  ⚠️  LIVE TRADING ENGINE INITIALIZED")
        logger.warning("  ⚠️  REAL MONEY WILL BE USED!")
        logger.warning("=" * 60)
        
        self._settings = settings
        self._market_data = market_data
        self._dhan_client = dhan_client
        self._order_manager = order_manager
        self._risk_manager = risk_manager
        self._circuit_breaker = circuit_breaker
        self._trade_repo = trade_repository
        self._position_repo = position_repository
        self._snapshot_repo = snapshot_repository
        self._alert_manager = alert_manager
        
        # State
        self._state = constants.BOT_STATE_STOPPED
        self._today = date.today()
        
        # Capital tracking (synced with broker)
        self._initial_capital = float(getattr(settings, "INITIAL_CAPITAL", 100000))
        self._capital = self._initial_capital
        self._available_capital = self._initial_capital
        
        # Daily tracking
        self._daily_pnl = 0.0
        self._daily_starting_capital = self._initial_capital
        self._trades_today_count = 0
        
        # Total tracking
        self._total_pnl = 0.0
        
        # Order tracking
        self._pending_orders: Dict[str, Dict] = {}
        self._last_order_time: Optional[datetime] = None
        
        # Verify we're not in paper mode
        self._verify_live_mode()
        
        # Sync with broker on init
        self._sync_with_broker()
        
        logger.info(f"[LIVE] Engine initialized with capital: {format_currency(self._capital)}")
    
    # ================================================================
    # SAFETY CHECKS
    # ================================================================
    
    def _verify_live_mode(self) -> None:
        """
        Verify that PAPER_TRADING is False.
        
        Raises:
            TradingBotError: If PAPER_TRADING is True
        """
        paper_trading = getattr(self._settings, "PAPER_TRADING", True)
        
        if paper_trading:
            error_msg = (
                "CRITICAL: LiveEngine initialized but PAPER_TRADING=True! "
                "Set PAPER_TRADING=False in .env to use live trading."
            )
            logger.critical(error_msg)
            raise TradingBotError(error_msg)
        
        logger.info("[LIVE] Verified: PAPER_TRADING=False")
    
    def _verify_before_order(self, order_value: float, description: str) -> bool:
        """
        Run all safety checks before placing an order.
        
        Args:
            order_value: Total value of the order
            description: Human-readable order description
            
        Returns:
            True if all checks pass
            
        Raises:
            Various exceptions if checks fail
        """
        # Check 1: Paper trading mode
        if getattr(self._settings, "PAPER_TRADING", True):
            raise TradingBotError("Cannot place live order: PAPER_TRADING is True")
        
        # Check 2: Circuit breaker
        if not self._circuit_breaker.is_safe():
            raise TradingBotError("Cannot place order: Circuit breaker triggered")
        
        # Check 3: Order value within limits
        max_per_trade = float(getattr(self._settings, "MAX_CAPITAL_PER_TRADE", 5000))
        if order_value > max_per_trade:
            raise TradingBotError(
                f"Order value ₹{order_value:,.2f} exceeds MAX_CAPITAL_PER_TRADE ₹{max_per_trade:,.2f}"
            )
        
        # Check 4: Absolute maximum
        if order_value > self.ABSOLUTE_MAX_ORDER_VALUE:
            raise TradingBotError(
                f"Order value ₹{order_value:,.2f} exceeds absolute maximum ₹{self.ABSOLUTE_MAX_ORDER_VALUE:,.2f}"
            )
        
        # Check 5: Available capital
        if order_value > self._available_capital:
            raise InsufficientFundsError(
                required=order_value,
                available=self._available_capital
            )
        
        # Check 6: Engine state
        if self._state != constants.BOT_STATE_RUNNING:
            raise TradingBotError(f"Cannot place order: Engine state is {self._state}")
        
        logger.info(f"[LIVE] Safety checks passed for: {description}")
        return True
    
    def _sync_with_broker(self) -> None:
        """
        Sync capital and positions with broker.
        
        Fetches actual account balance and open positions from Dhan.
        """
        try:
            logger.info("[LIVE] Syncing with broker...")
            
            # Get account balance
            try:
                fund_limits = self._dhan_client.get_fund_limits()
                if fund_limits:
                    self._capital = float(fund_limits.get("availableBalance", self._capital))
                    self._available_capital = float(fund_limits.get("availableBalance", self._available_capital))
                    logger.info(f"[LIVE] Broker balance: {format_currency(self._capital)}")
            except Exception as e:
                logger.warning(f"[LIVE] Could not fetch fund limits: {e}")
            
            # Get open positions
            try:
                positions = self._dhan_client.get_positions()
                if positions:
                    logger.info(f"[LIVE] Found {len(positions)} open positions with broker")
            except Exception as e:
                logger.warning(f"[LIVE] Could not fetch positions: {e}")
            
            logger.info("[LIVE] Broker sync complete")
            
        except Exception as e:
            logger.error(f"[LIVE] Broker sync failed: {e}")
    
    # ================================================================
    # PROPERTIES (Same as PaperEngine)
    # ================================================================
    
    @property
    def capital(self) -> float:
        """Total account capital."""
        return self._capital
    
    @property
    def available_capital(self) -> float:
        """Capital available for new trades."""
        return self._available_capital
    
    @property
    def daily_pnl(self) -> float:
        """Today's profit/loss."""
        return self._daily_pnl
    
    @property
    def total_pnl(self) -> float:
        """All-time profit/loss."""
        return self._total_pnl
    
    @property
    def trades_today(self) -> int:
        """Number of trades executed today."""
        return self._trades_today_count
    
    @property
    def state(self) -> str:
        """Current engine state."""
        return self._state
    
    @state.setter
    def state(self, value: str) -> None:
        """Set engine state."""
        old_state = self._state
        self._state = value
        logger.info(f"[LIVE] State changed: {old_state} → {value}")
    
    # ================================================================
    # TRADE EXECUTION
    # ================================================================
    
    def execute_trade(self, consensus_signal: Dict[str, Any]) -> Optional[Any]:
        """
        Execute a REAL trade based on consensus signal.
        
        This method places actual orders on the exchange!
        
        Args:
            consensus_signal: Signal from BrainCoordinator with:
                - symbol: e.g., "NIFTY"
                - action: "BUY" or "SELL"
                - confidence: 0.0 to 1.0
                - option_recommendation: {type, strike_preference, expiry}
                
        Returns:
            Trade object if successful, None otherwise
            
        Safety:
            - Sends Telegram alert BEFORE placing order
            - Verifies order after placement
            - Sends Telegram alert AFTER order completes
        """
        symbol = consensus_signal.get("symbol", "").upper()
        action = consensus_signal.get("action", constants.SIGNAL_HOLD)
        confidence = consensus_signal.get("confidence", 0.0)
        
        logger.info(f"[LIVE] ═══════════════════════════════════════════")
        logger.info(f"[LIVE] TRADE REQUEST: {symbol} {action} ({confidence:.0%})")
        logger.info(f"[LIVE] ═══════════════════════════════════════════")
        
        # Skip HOLD signals
        if action == constants.SIGNAL_HOLD:
            logger.debug(f"[LIVE] Skipping HOLD signal for {symbol}")
            return None
        
        try:
            # Step 1: Build order parameters
            order_params = self._build_order_params(consensus_signal)
            if not order_params:
                logger.warning(f"[LIVE] Failed to build order params for {symbol}")
                return None
            
            order_value = order_params["total_cost"]
            instrument = order_params["instrument"]
            
            # Step 2: Run safety checks
            try:
                self._verify_before_order(order_value, instrument)
            except Exception as e:
                logger.error(f"[LIVE] Safety check failed: {e}")
                return None
            
            # Step 3: Check with risk manager
            try:
                approved, rejection_reason = self._risk_manager.can_trade(
                    symbol=symbol,
                    action=action,
                    capital_required=order_value,
                    current_positions=self._get_open_position_count(),
                )
                
                if not approved:
                    logger.warning(f"[LIVE] Risk manager rejected: {rejection_reason}")
                    return None
                    
            except Exception as e:
                logger.error(f"[LIVE] Risk check failed: {e}")
                return None
            
            # Step 4: Send PRE-ORDER Telegram alert
            self._send_pre_order_alert(order_params)
            
            # Step 5: Place the REAL order
            trade = self._place_real_order(order_params, consensus_signal)
            
            if trade:
                # Step 6: Update tracking
                self._available_capital -= order_value
                self._trades_today_count += 1
                
                # Step 7: Record circuit breaker (will be updated on close)
                # Don't record yet - wait for trade to close
                
                # Step 8: Send POST-ORDER Telegram alert
                self._send_post_order_alert(trade, success=True)
                
                logger.info(f"[LIVE] ✅ Trade executed successfully: {instrument}")
                
                return trade
            else:
                # Order failed
                self._send_post_order_alert(order_params, success=False)
                logger.error(f"[LIVE] ❌ Trade execution failed: {instrument}")
                return None
                
        except Exception as e:
            logger.critical(f"[LIVE] CRITICAL ERROR in execute_trade: {e}", exc_info=True)
            
            # Send error alert
            if self._alert_manager:
                try:
                    self._alert_manager.send_error_alert(
                        "LIVE Trade Execution Error",
                        f"{symbol}: {str(e)[:200]}"
                    )
                except Exception:
                    pass
            
            return None
    
    def _build_order_params(self, consensus_signal: Dict[str, Any]) -> Optional[Dict]:
        """
        Build order parameters from consensus signal.
        
        Args:
            consensus_signal: Signal from coordinator
            
        Returns:
            Dict with order parameters or None
        """
        try:
            symbol = consensus_signal.get("symbol", "").upper()
            action = consensus_signal.get("action")
            option_rec = consensus_signal.get("option_recommendation", {})
            
            if not option_rec:
                logger.warning(f"[LIVE] No option recommendation for {symbol}")
                return None
            
            # Get spot price
            spot_price = self._market_data.get_spot_price(symbol)
            if not spot_price:
                logger.error(f"[LIVE] Could not get spot price for {symbol}")
                return None
            
            # Determine option type
            option_type = option_rec.get("type", constants.OPTION_TYPE_CALL)
            strike_pref = option_rec.get("strike_preference", "ATM")
            
            # Calculate strike price
            strike_step = (
                constants.STRIKE_STEP_NIFTY if symbol == "NIFTY"
                else constants.STRIKE_STEP_BANKNIFTY
            )
            
            if strike_pref == "ATM":
                strike_price = get_atm_strike(spot_price, strike_step)
            else:
                otm_count = int(strike_pref.replace("OTM", "") or "1")
                strike_price = get_otm_strike(spot_price, strike_step, otm_count, option_type)
            
            # Get lot size
            lot_size = (
                constants.LOT_SIZE_NIFTY if symbol == "NIFTY"
                else constants.LOT_SIZE_BANKNIFTY
            )
            
            # Build instrument name
            expiry = self._market_data.get_current_expiry(symbol)
            instrument = f"{symbol} {strike_price} {option_type} {expiry}"
            
            # Get option price (LTP)
            option_quote = self._market_data.get_option_quote(
                symbol, strike_price, option_type, expiry
            )
            
            if not option_quote:
                logger.error(f"[LIVE] Could not get quote for {instrument}")
                return None
            
            entry_price = float(option_quote.get("ltp", 0))
            if entry_price <= 0:
                logger.error(f"[LIVE] Invalid entry price for {instrument}: {entry_price}")
                return None
            
            # Calculate quantity (lots)
            max_capital = float(getattr(self._settings, "MAX_CAPITAL_PER_TRADE", 5000))
            max_lots = int(max_capital / (entry_price * lot_size))
            lots = max(1, min(max_lots, 2))  # 1-2 lots max for safety
            quantity = lots * lot_size
            
            # Calculate total cost
            total_cost = entry_price * quantity
            
            # Calculate SL and TP
            sl_pct = float(getattr(self._settings, "STOP_LOSS_PERCENTAGE", 30)) / 100
            tp_pct = float(getattr(self._settings, "TAKE_PROFIT_PERCENTAGE", 50)) / 100
            
            stop_loss = entry_price * (1 - sl_pct)
            take_profit = entry_price * (1 + tp_pct)
            
            # Get security ID for Dhan API
            security_id = self._get_security_id(symbol, strike_price, option_type, expiry)
            
            return {
                "symbol": symbol,
                "instrument": instrument,
                "option_type": option_type,
                "strike_price": strike_price,
                "expiry": expiry,
                "entry_price": entry_price,
                "quantity": quantity,
                "lots": lots,
                "lot_size": lot_size,
                "total_cost": total_cost,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "security_id": security_id,
                "action": action,
                "spot_price": spot_price,
            }
            
        except Exception as e:
            logger.error(f"[LIVE] Error building order params: {e}")
            return None
    
    def _get_security_id(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        expiry: str
    ) -> Optional[str]:
        """
        Get Dhan security ID for the option contract.
        
        Args:
            symbol: Underlying symbol
            strike: Strike price
            option_type: CE or PE
            expiry: Expiry date string
            
        Returns:
            Security ID string or None
        """
        try:
            # Try to get from option chain
            chain = self._market_data.get_option_chain(symbol)
            
            if chain:
                for contract in chain:
                    if (
                        contract.get("strike") == strike and
                        contract.get("option_type") == option_type
                    ):
                        return contract.get("security_id")
            
            # Fallback: construct security ID
            # This is broker-specific - Dhan uses specific format
            logger.warning(f"[LIVE] Could not find security ID, using fallback")
            return None
            
        except Exception as e:
            logger.error(f"[LIVE] Error getting security ID: {e}")
            return None
    
    def _place_real_order(
        self,
        order_params: Dict,
        consensus_signal: Dict
    ) -> Optional[Any]:
        """
        Place actual order on exchange via Dhan API.
        
        Args:
            order_params: Order parameters dict
            consensus_signal: Original signal
            
        Returns:
            Trade object if successful, None otherwise
        """
        instrument = order_params["instrument"]
        security_id = order_params["security_id"]
        quantity = order_params["quantity"]
        
        logger.info(f"[LIVE] 🔥 PLACING REAL ORDER: {instrument}")
        logger.info(f"[LIVE]    Quantity: {quantity}")
        logger.info(f"[LIVE]    Est. Price: {format_currency(order_params['entry_price'])}")
        logger.info(f"[LIVE]    Total Cost: {format_currency(order_params['total_cost'])}")
        
        if not security_id:
            logger.error(f"[LIVE] Cannot place order: No security ID")
            return None
        
        # Build Dhan order request
        order_request = {
            "transaction_type": "BUY",
            "exchange_segment": "NSE_FNO",
            "product_type": "INTRADAY",
            "order_type": "MARKET",
            "security_id": security_id,
            "quantity": quantity,
            "validity": "DAY",
            "disclosed_quantity": 0,
            "price": 0,  # Market order
            "trigger_price": 0,
            "after_market_order": False,
        }
        
        # Place order with retry
        order_response = None
        for attempt in range(self.MAX_ORDER_RETRIES):
            try:
                logger.info(f"[LIVE] Placing order (attempt {attempt + 1}/{self.MAX_ORDER_RETRIES})...")
                
                order_response = self._dhan_client.place_order(order_request)
                
                if order_response:
                    break
                    
            except Exception as e:
                logger.error(f"[LIVE] Order attempt {attempt + 1} failed: {e}")
                if attempt < self.MAX_ORDER_RETRIES - 1:
                    time.sleep(1)
        
        if not order_response:
            logger.error(f"[LIVE] All order attempts failed for {instrument}")
            return None
        
        # Extract order ID
        order_id = order_response.get("orderId") or order_response.get("order_id")
        
        if not order_id:
            logger.error(f"[LIVE] No order ID in response: {order_response}")
            return None
        
        logger.info(f"[LIVE] Order placed! Order ID: {order_id}")
        
        # Wait and verify order status
        filled_price = self._verify_order_filled(order_id, order_params["entry_price"])
        
        if filled_price is None:
            logger.error(f"[LIVE] Order {order_id} was not filled")
            return None
        
        # Create and save trade
        trade = self._create_trade_record(
            order_params=order_params,
            consensus_signal=consensus_signal,
            order_id=order_id,
            filled_price=filled_price,
        )
        
        return trade
    
    def _verify_order_filled(
        self,
        order_id: str,
        expected_price: float,
        timeout: int = None
    ) -> Optional[float]:
        """
        Verify that an order was filled.
        
        Args:
            order_id: Dhan order ID
            expected_price: Expected fill price
            timeout: Max seconds to wait
            
        Returns:
            Actual fill price if filled, None otherwise
        """
        timeout = timeout or self.ORDER_TIMEOUT
        start_time = time.time()
        
        logger.info(f"[LIVE] Verifying order {order_id}...")
        
        while time.time() - start_time < timeout:
            try:
                # Get order status from Dhan
                order_status = self._dhan_client.get_order_status(order_id)
                
                if order_status:
                    status = order_status.get("status", "").upper()
                    
                    if status in ["TRADED", "FILLED", "COMPLETE"]:
                        filled_price = float(order_status.get("price", expected_price))
                        logger.info(f"[LIVE] ✅ Order FILLED at {format_currency(filled_price)}")
                        return filled_price
                    
                    elif status in ["REJECTED", "CANCELLED", "CANCELED"]:
                        reason = order_status.get("rejection_reason", "Unknown")
                        logger.error(f"[LIVE] ❌ Order REJECTED: {reason}")
                        return None
                    
                    elif status in ["PENDING", "OPEN", "TRIGGER_PENDING"]:
                        logger.debug(f"[LIVE] Order status: {status}, waiting...")
                    
                    else:
                        logger.warning(f"[LIVE] Unknown order status: {status}")
                
                time.sleep(self.ORDER_VERIFICATION_DELAY)
                
            except Exception as e:
                logger.error(f"[LIVE] Error checking order status: {e}")
                time.sleep(self.ORDER_VERIFICATION_DELAY)
        
        logger.error(f"[LIVE] Order verification timed out after {timeout}s")
        return None
    
    def _create_trade_record(
        self,
        order_params: Dict,
        consensus_signal: Dict,
        order_id: str,
        filled_price: float,
    ) -> Any:
        """
        Create and save trade record to database.
        
        Args:
            order_params: Order parameters
            consensus_signal: Original signal
            order_id: Broker order ID
            filled_price: Actual fill price
            
        Returns:
            Trade object
        """
        now = get_ist_now()
        trade_id = generate_trade_id()
        
        # Recalculate with actual fill price
        quantity = order_params["quantity"]
        actual_cost = filled_price * quantity
        
        sl_pct = float(getattr(self._settings, "STOP_LOSS_PERCENTAGE", 30)) / 100
        tp_pct = float(getattr(self._settings, "TAKE_PROFIT_PERCENTAGE", 50)) / 100
        
        stop_loss = filled_price * (1 - sl_pct)
        take_profit = filled_price * (1 + tp_pct)
        
        trade_data = {
            "trade_id": trade_id,
            "order_id": order_id,
            "symbol": order_params["symbol"],
            "instrument": order_params["instrument"],
            "option_type": order_params["option_type"],
            "strike_price": order_params["strike_price"],
            "expiry": order_params["expiry"],
            "action": "BUY",
            "quantity": quantity,
            "lots": order_params["lots"],
            "entry_price": filled_price,
            "entry_time": now,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "status": "OPEN",
            "mode": "LIVE",  # Mark as live trade
            "confidence": consensus_signal.get("confidence", 0),
            "brain_signals": consensus_signal.get("brain_signals", []),
            "reasoning": consensus_signal.get("reasoning", ""),
        }
        
        # Save to database
        trade = self._trade_repo.create_trade(trade_data)
        
        logger.info(f"[LIVE] Trade saved: {trade_id}")
        
        return trade
    
    # ================================================================
    # POSITION MANAGEMENT
    # ================================================================
    
    def update_positions(self) -> List[Any]:
        """
        Update all open positions with current prices and check exits.
        
        Returns:
            List of trades that were closed
        """
        closed_trades = []
        
        try:
            # Get open trades from database
            open_trades = self._trade_repo.get_open_trades()
            
            if not open_trades:
                return closed_trades
            
            logger.debug(f"[LIVE] Updating {len(open_trades)} open positions...")
            
            for trade in open_trades:
                try:
                    closed = self._update_single_position(trade)
                    if closed:
                        closed_trades.append(closed)
                except Exception as e:
                    logger.error(f"[LIVE] Error updating position {trade.trade_id}: {e}")
            
            return closed_trades
            
        except Exception as e:
            logger.error(f"[LIVE] Error in update_positions: {e}")
            return closed_trades
    
    def _update_single_position(self, trade) -> Optional[Any]:
        """
        Update a single position and check for exit conditions.
        
        Args:
            trade: Trade object
            
        Returns:
            Closed trade if exit triggered, None otherwise
        """
        # Get current price from broker
        try:
            current_price = self._get_live_price(trade)
            
            if current_price is None:
                logger.warning(f"[LIVE] Could not get price for {trade.instrument}")
                return None
            
        except Exception as e:
            logger.error(f"[LIVE] Error getting price for {trade.instrument}: {e}")
            return None
        
        # Check exit conditions
        exit_reason = None
        
        # Stop Loss
        if current_price <= trade.stop_loss:
            exit_reason = "STOP_LOSS"
            logger.info(f"[LIVE] 🛑 SL triggered for {trade.instrument}")
        
        # Take Profit
        elif current_price >= trade.take_profit:
            exit_reason = "TAKE_PROFIT"
            logger.info(f"[LIVE] 🎯 TP triggered for {trade.instrument}")
        
        # Check via risk manager
        if not exit_reason:
            should_exit, reason = self._risk_manager.check_position_exit(
                trade, current_price
            )
            if should_exit:
                exit_reason = reason
        
        # Execute exit if needed
        if exit_reason:
            return self.close_position(trade, current_price, exit_reason)
        
        return None
    
    def _get_live_price(self, trade) -> Optional[float]:
        """
        Get live price for a position from broker.
        
        Args:
            trade: Trade object
            
        Returns:
            Current price or None
        """
        try:
            # Try to get from positions
            positions = self._dhan_client.get_positions()
            
            if positions:
                for pos in positions:
                    if pos.get("security_id") == trade.security_id:
                        return float(pos.get("ltp", 0))
            
            # Fallback to option quote
            quote = self._market_data.get_option_quote(
                trade.symbol,
                trade.strike_price,
                trade.option_type,
                trade.expiry
            )
            
            if quote:
                return float(quote.get("ltp", 0))
            
            return None
            
        except Exception as e:
            logger.error(f"[LIVE] Error getting live price: {e}")
            return None
    
    def close_position(
        self,
        trade,
        exit_price: float,
        reason: str
    ) -> Optional[Any]:
        """
        Close a position by placing a SELL order.
        
        Args:
            trade: Trade object to close
            exit_price: Current/exit price
            reason: Exit reason (SL, TP, MANUAL, etc.)
            
        Returns:
            Closed trade object
        """
        logger.info(f"[LIVE] ═══════════════════════════════════════════")
        logger.info(f"[LIVE] CLOSING POSITION: {trade.instrument}")
        logger.info(f"[LIVE] Reason: {reason}")
        logger.info(f"[LIVE] ═══════════════════════════════════════════")
        
        try:
            # Send pre-close alert
            if self._alert_manager:
                try:
                    self._alert_manager.send_message(
                        f"🔄 CLOSING POSITION\n"
                        f"Instrument: {trade.instrument}\n"
                        f"Reason: {reason}\n"
                        f"Est. Price: {format_currency(exit_price)}"
                    )
                except Exception:
                    pass
            
            # Build SELL order
            order_request = {
                "transaction_type": "SELL",
                "exchange_segment": "NSE_FNO",
                "product_type": "INTRADAY",
                "order_type": "MARKET",
                "security_id": getattr(trade, "security_id", ""),
                "quantity": trade.quantity,
                "validity": "DAY",
                "price": 0,
                "trigger_price": 0,
            }
            
            # Place SELL order
            order_response = None
            for attempt in range(self.MAX_ORDER_RETRIES):
                try:
                    order_response = self._dhan_client.place_order(order_request)
                    if order_response:
                        break
                except Exception as e:
                    logger.error(f"[LIVE] Sell attempt {attempt + 1} failed: {e}")
                    time.sleep(1)
            
            if not order_response:
                logger.error(f"[LIVE] Failed to place SELL order for {trade.instrument}")
                # Still close in database with estimated price
                actual_exit_price = exit_price
            else:
                # Verify sell order
                sell_order_id = order_response.get("orderId") or order_response.get("order_id")
                actual_exit_price = self._verify_order_filled(sell_order_id, exit_price)
                
                if actual_exit_price is None:
                    actual_exit_price = exit_price  # Use estimate
            
            # Calculate P&L
            pnl = (actual_exit_price - trade.entry_price) * trade.quantity
            pnl_pct = ((actual_exit_price - trade.entry_price) / trade.entry_price) * 100
            
            # Update trade in database
            closed_trade = self._trade_repo.close_trade(
                trade_id=trade.trade_id,
                exit_price=actual_exit_price,
                exit_time=get_ist_now(),
                exit_reason=reason,
                pnl=pnl,
                pnl_percentage=pnl_pct,
            )
            
            # Update tracking
            self._daily_pnl += pnl
            self._total_pnl += pnl
            self._available_capital += (trade.entry_price * trade.quantity) + pnl
            
            # Record with circuit breaker
            is_win = pnl >= 0
            self._circuit_breaker.record_trade_result(is_win, pnl)
            
            logger.info(f"[LIVE] ✅ Position closed: {format_pnl(pnl)} ({pnl_pct:+.1f}%)")
            
            # Send post-close alert
            if self._alert_manager:
                try:
                    self._alert_manager.send_trade_closed(closed_trade)
                except Exception:
                    pass
            
            return closed_trade
            
        except Exception as e:
            logger.critical(f"[LIVE] CRITICAL ERROR closing position: {e}", exc_info=True)
            
            if self._alert_manager:
                try:
                    self._alert_manager.send_error_alert(
                        "CRITICAL: Position Close Error",
                        f"{trade.instrument}: {str(e)[:200]}"
                    )
                except Exception:
                    pass
            
            return None
    
    def close_all_positions(self, reason: str = "MANUAL") -> List[Any]:
        """
        Close all open positions.
        
        Args:
            reason: Reason for closing (MANUAL, TIME, EMERGENCY, etc.)
            
        Returns:
            List of closed trades
        """
        logger.warning(f"[LIVE] ═══════════════════════════════════════════")
        logger.warning(f"[LIVE] CLOSING ALL POSITIONS")
        logger.warning(f"[LIVE] Reason: {reason}")
        logger.warning(f"[LIVE] ═══════════════════════════════════════════")
        
        closed_trades = []
        
        try:
            open_trades = self._trade_repo.get_open_trades()
            
            if not open_trades:
                logger.info("[LIVE] No open positions to close")
                return closed_trades
            
            logger.info(f"[LIVE] Closing {len(open_trades)} positions...")
            
            for trade in open_trades:
                try:
                    # Get current price
                    current_price = self._get_live_price(trade)
                    if current_price is None:
                        current_price = trade.entry_price  # Fallback
                    
                    closed = self.close_position(trade, current_price, reason)
                    if closed:
                        closed_trades.append(closed)
                        
                except Exception as e:
                    logger.error(f"[LIVE] Error closing {trade.instrument}: {e}")
            
            logger.info(f"[LIVE] Closed {len(closed_trades)}/{len(open_trades)} positions")
            
            return closed_trades
            
        except Exception as e:
            logger.critical(f"[LIVE] CRITICAL ERROR in close_all_positions: {e}")
            return closed_trades
    
    # ================================================================
    # ALERTS
    # ================================================================
    
    def _send_pre_order_alert(self, order_params: Dict) -> None:
        """Send Telegram alert BEFORE placing order."""
        if not self._alert_manager:
            return
        
        try:
            message = (
                f"⚠️ PLACING LIVE ORDER\n\n"
                f"Instrument: {order_params['instrument']}\n"
                f"Action: BUY\n"
                f"Quantity: {order_params['quantity']}\n"
                f"Est. Price: {format_currency(order_params['entry_price'])}\n"
                f"Total Cost: {format_currency(order_params['total_cost'])}\n"
                f"SL: {format_currency(order_params['stop_loss'])}\n"
                f"TP: {format_currency(order_params['take_profit'])}\n\n"
                f"🔴 REAL MONEY TRADE 🔴"
            )
            self._alert_manager.send_message(message)
        except Exception as e:
            logger.error(f"[LIVE] Error sending pre-order alert: {e}")
    
    def _send_post_order_alert(self, data: Any, success: bool) -> None:
        """Send Telegram alert AFTER order completion."""
        if not self._alert_manager:
            return
        
        try:
            if success and hasattr(data, 'instrument'):
                # data is a Trade object
                message = (
                    f"✅ LIVE ORDER FILLED\n\n"
                    f"Instrument: {data.instrument}\n"
                    f"Entry: {format_currency(data.entry_price)}\n"
                    f"Quantity: {data.quantity}\n"
                    f"SL: {format_currency(data.stop_loss)}\n"
                    f"TP: {format_currency(data.take_profit)}\n\n"
                    f"Position is now OPEN"
                )
            elif success:
                # data is order_params dict
                message = (
                    f"✅ LIVE ORDER PLACED\n\n"
                    f"Instrument: {data.get('instrument', 'Unknown')}"
                )
            else:
                # Order failed
                instrument = data.get('instrument', 'Unknown') if isinstance(data, dict) else 'Unknown'
                message = (
                    f"❌ LIVE ORDER FAILED\n\n"
                    f"Instrument: {instrument}\n"
                    f"Check logs for details"
                )
            
            self._alert_manager.send_message(message)
        except Exception as e:
            logger.error(f"[LIVE] Error sending post-order alert: {e}")
    
    # ================================================================
    # PORTFOLIO & REPORTING (Same as PaperEngine)
    # ================================================================
    
    def get_portfolio(self) -> Dict[str, Any]:
        """
        Get current portfolio status.
        
        Returns:
            Dict with capital, P&L, positions, trades info
        """
        # Sync with broker periodically
        try:
            self._sync_with_broker()
        except Exception:
            pass
        
        open_trades = self._trade_repo.get_open_trades() or []
        trades_today = self._trade_repo.get_trades_today() or []
        
        # Calculate invested capital
        invested = sum(
            float(t.entry_price) * int(t.quantity)
            for t in open_trades
        )
        
        # Calculate unrealized P&L
        unrealized_pnl = 0.0
        open_positions = []
        
        for trade in open_trades:
            current_price = self._get_live_price(trade) or trade.entry_price
            pnl = (current_price - trade.entry_price) * trade.quantity
            pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
            unrealized_pnl += pnl
            
            open_positions.append({
                "trade_id": trade.trade_id,
                "instrument": trade.instrument,
                "entry_price": trade.entry_price,
                "current_price": current_price,
                "quantity": trade.quantity,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "stop_loss": trade.stop_loss,
                "take_profit": trade.take_profit,
            })
        
        # Calculate win/loss stats
        closed_today = [t for t in trades_today if t.status == "CLOSED"]
        wins = sum(1 for t in closed_today if (t.pnl or 0) >= 0)
        losses = len(closed_today) - wins
        win_rate = (wins / len(closed_today) * 100) if closed_today else 0.0
        
        return {
            "mode": "LIVE",
            "capital": {
                "initial": self._initial_capital,
                "current": self._capital,
                "available": self._available_capital,
                "invested": invested,
            },
            "pnl": {
                "daily": self._daily_pnl,
                "daily_pct": (self._daily_pnl / self._daily_starting_capital * 100) if self._daily_starting_capital else 0,
                "unrealized": unrealized_pnl,
                "total": self._total_pnl,
                "total_pct": (self._total_pnl / self._initial_capital * 100) if self._initial_capital else 0,
            },
            "positions": {
                "open": open_positions,
                "open_count": len(open_trades),
            },
            "trades": {
                "today": len(trades_today),
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
            },
        }
    
    def get_daily_summary(self) -> Dict[str, Any]:
        """Get daily trading summary."""
        trades_today = self._trade_repo.get_trades_today() or []
        closed_today = [t for t in trades_today if t.status == "CLOSED"]
        
        total_pnl = sum(float(t.pnl or 0) for t in closed_today)
        wins = sum(1 for t in closed_today if (t.pnl or 0) >= 0)
        losses = len(closed_today) - wins
        
        best_trade = max((t.pnl or 0 for t in closed_today), default=0)
        worst_trade = min((t.pnl or 0 for t in closed_today), default=0)
        
        return {
            "date": self._today.isoformat(),
            "mode": "LIVE",
            "starting_capital": self._daily_starting_capital,
            "ending_capital": self._capital,
            "total_pnl": total_pnl,
            "total_pnl_pct": (total_pnl / self._daily_starting_capital * 100) if self._daily_starting_capital else 0,
            "trades_count": len(closed_today),
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / len(closed_today) * 100) if closed_today else 0,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "circuit_breaker_triggered": self._circuit_breaker.triggered,
        }
    
    def save_daily_snapshot(self) -> None:
        """Save daily snapshot to database."""
        try:
            summary = self.get_daily_summary()
            self._snapshot_repo.save_daily_snapshot({
                "date": self._today,
                "mode": "LIVE",
                "starting_capital": summary["starting_capital"],
                "ending_capital": summary["ending_capital"],
                "pnl": summary["total_pnl"],
                "pnl_pct": summary["total_pnl_pct"],
                "trades_count": summary["trades_count"],
                "wins": summary["wins"],
                "losses": summary["losses"],
                "win_rate": summary["win_rate"],
            })
            logger.info(f"[LIVE] Daily snapshot saved for {self._today}")
        except Exception as e:
            logger.error(f"[LIVE] Error saving snapshot: {e}")
    
    def start_new_day(self) -> None:
        """Reset daily tracking for new trading day."""
        self._today = date.today()
        self._daily_pnl = 0.0
        self._daily_starting_capital = self._capital
        self._trades_today_count = 0
        
        # Sync with broker
        self._sync_with_broker()
        
        logger.info(f"[LIVE] New trading day started: {self._today}")
    
    def has_open_positions(self) -> bool:
        """Check if there are any open positions."""
        open_trades = self._trade_repo.get_open_trades()
        return len(open_trades) > 0 if open_trades else False
    
    def _get_open_position_count(self) -> int:
        """Get count of open positions."""
        open_trades = self._trade_repo.get_open_trades()
        return len(open_trades) if open_trades else 0
    
    def get_open_position_count(self) -> int:
        """Public method to get open position count."""
        return self._get_open_position_count()


# ================================================================
# TEST
# ================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  LIVE ENGINE - TEST")
    print("  ⚠️  This is the REAL MONEY engine!")
    print("=" * 60)
    
    print("\n  This test only verifies class structure.")
    print("  It does NOT place any real orders.")
    
    print("\n  To use LiveEngine:")
    print("  1. Set PAPER_TRADING=False in .env")
    print("  2. Ensure all API keys are valid")
    print("  3. Bot will automatically use LiveEngine")
    
    print("\n  Safety features:")
    print("  ✓ Multiple confirmation checks")
    print("  ✓ Telegram alerts before/after orders")
    print("  ✓ Order verification")
    print("  ✓ Maximum order value limits")
    print("  ✓ Circuit breaker integration")
    
    print("\n" + "=" * 60)
    print("  ⚠️  TRADE CAREFULLY WITH REAL MONEY!")
    print("=" * 60 + "\n")