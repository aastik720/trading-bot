"""
Order Manager - Order Lifecycle Management
============================================

Handles the complete lifecycle of an order:
    CREATE → EXECUTE → MONITOR → CLOSE/CANCEL

In PAPER mode, orders are instantly filled at current market price.
In LIVE mode (future), orders are sent to Dhan API.

Order Flow
----------
    1. RiskManager.can_trade() approves signal → returns trade_params
    2. OrderManager.create_order(trade_params) → returns order dict
    3. OrderManager.execute_order(order) → saves Trade & Position to DB
    4. ... position is monitored by PaperEngine ...
    5. OrderManager.close_order(trade_id, exit_price, reason) → closes Trade

Order Statuses
--------------
    PENDING   → Order created but not yet executed
    OPEN      → Order executed, position is open (alias for FILLED)
    FILLED    → Order filled, position is active
    CLOSED    → Position closed (SL/TP/TRAIL/TIME/MANUAL)
    CANCELLED → Order cancelled before execution
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from config.settings import settings
from config import constants
from utils.helpers import (
    generate_order_id,
    generate_trade_id,
    format_currency,
    format_pnl,
    get_ist_now,
)

logger = logging.getLogger(__name__)


class OrderManager:
    """
    Manages the complete lifecycle of trading orders.
    
    Parameters
    ----------
    settings : object
        Application settings from config.settings.
    market_data : MarketData
        Market data provider for fetching current prices.
    trade_repository : TradeRepository
        Repository for persisting trade records.
    position_repository : PositionRepository
        Repository for tracking open positions.
    
    Examples
    --------
        order = order_manager.create_order(trade_params)
        trade = order_manager.execute_order(order)
        # ... later ...
        closed_trade = order_manager.close_order(trade.trade_id, 150.0, "TP")
    """
    
    def __init__(
        self,
        settings,
        market_data,
        trade_repository,
        position_repository,
    ) -> None:
        self._settings = settings
        self._market_data = market_data
        self._trade_repo = trade_repository
        self._position_repo = position_repository
        
        # Track pending orders (not yet executed)
        self._pending_orders: Dict[str, dict] = {}
        
        # Determine mode
        self._paper_mode = getattr(settings, "PAPER_TRADING", True)
        self._mode = "PAPER" if self._paper_mode else "LIVE"
        
        logger.info(
            "OrderManager initialised | Mode: %s | "
            "Trade repo: %s | Position repo: %s",
            self._mode,
            type(trade_repository).__name__,
            type(position_repository).__name__,
        )
    
    # ================================================================ #
    #  PROPERTIES                                                       #
    # ================================================================ #
    
    @property
    def mode(self) -> str:
        """Current trading mode: 'PAPER' or 'LIVE'."""
        return self._mode
    
    @property
    def is_paper_mode(self) -> bool:
        """Whether we're in paper trading mode."""
        return self._paper_mode
    
    @property
    def pending_orders(self) -> Dict[str, dict]:
        """Dictionary of pending (unexecuted) orders."""
        return self._pending_orders.copy()
    
    # ================================================================ #
    #  CREATE ORDER                                                     #
    # ================================================================ #
    
    def create_order(self, trade_params: dict) -> dict:
        """
        Create an order from risk-approved trade parameters.
        
        Takes the trade_params dict from RiskManager.can_trade() output
        and creates a fully populated order ready for execution.
        
        Parameters
        ----------
        trade_params : dict
            Output from RiskManager.can_trade() containing:
            symbol, instrument, strike, option_type, expiry, side,
            quantity, lots, entry_price, stop_loss, take_profit, etc.
        
        Returns
        -------
        dict
            Complete order dict ready for execution.
        
        Examples
        --------
            approved, reason, trade_params = risk_manager.can_trade(signal, capital)
            if approved:
                order = order_manager.create_order(trade_params)
        """
        now = get_ist_now()
        
        # Generate unique IDs
        order_id = generate_order_id()
        trade_id = trade_params.get("trade_id") or generate_trade_id()
        
        # Extract fields from trade_params
        symbol = trade_params.get("symbol", "UNKNOWN")
        instrument = trade_params.get("instrument", "")
        strike = trade_params.get("strike", 0)
        option_type = trade_params.get("option_type", constants.OPTION_TYPE_CALL)
        expiry = trade_params.get("expiry", "")
        side = trade_params.get("side", "BUY")
        quantity = trade_params.get("quantity", 0)
        lots = trade_params.get("lots", 1)
        
        # Get current premium from market data
        try:
            quote = self._market_data.get_option_quote(
                symbol=symbol,
                strike=strike,
                option_type=option_type,
                expiry=expiry,
            )
            current_price = quote.get("ltp", trade_params.get("entry_price", 0))
        except Exception as e:
            logger.warning(
                "Could not fetch live quote for %s: %s | Using trade_params price",
                instrument, e
            )
            current_price = trade_params.get("entry_price", 0)
        
        # Risk parameters
        stop_loss = trade_params.get("stop_loss", 0)
        take_profit = trade_params.get("take_profit", 0)
        trailing_stop = trade_params.get("trailing_stop", stop_loss)
        
        # Build order dict
        order = {
            "order_id": order_id,
            "trade_id": trade_id,
            "symbol": symbol,
            "instrument": instrument,
            "strike": strike,
            "option_type": option_type,
            "expiry": str(expiry) if expiry else "",
            "side": side,
            "quantity": quantity,
            "lots": lots,
            "lot_size": trade_params.get("lot_size", quantity // lots if lots > 0 else quantity),
            "order_type": "MARKET",
            "price": round(current_price, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "trailing_stop": round(trailing_stop, 2),
            "status": constants.ORDER_STATUS_PENDING,
            "created_at": now.isoformat(),
            "executed_at": None,
            "mode": self._mode,
            "confidence": trade_params.get("confidence", 0),
            "reasoning": trade_params.get("reasoning", ""),
            "brain_signals": trade_params.get("brain_signals", {}),
            "max_loss": trade_params.get("max_loss", 0),
            "max_profit": trade_params.get("max_profit", 0),
            "capital_required": trade_params.get("capital_required", 0),
        }
        
        # Store in pending orders
        self._pending_orders[order_id] = order
        
        logger.info(
            "📝 Order CREATED | %s | %s | %s @ ₹%.2f | "
            "Qty: %d | SL: ₹%.2f | TP: ₹%.2f | Mode: %s",
            order_id[:8],
            instrument,
            side,
            current_price,
            quantity,
            stop_loss,
            take_profit,
            self._mode,
        )
        
        return order
    
    # ================================================================ #
    #  EXECUTE ORDER                                                    #
    # ================================================================ #
    
    def execute_order(self, order: dict) -> Optional[Any]:
        """
        Execute a pending order.
        
        In PAPER mode: Instantly fill at current market price, save to DB.
        In LIVE mode: Send to Dhan API (to be implemented).
        
        Parameters
        ----------
        order : dict
            Order dict from create_order().
        
        Returns
        -------
        Trade or None
            The saved Trade object if successful, None if failed.
        """
        order_id = order.get("order_id", "")
        instrument = order.get("instrument", "")
        
        try:
            if self._paper_mode:
                return self._execute_paper_order(order)
            else:
                return self._execute_live_order(order)
        
        except Exception as e:
            logger.error(
                "❌ Order EXECUTION FAILED | %s | %s | Error: %s",
                order_id[:8] if order_id else "?",
                instrument,
                str(e),
            )
            
            # Update order status to failed
            if order_id in self._pending_orders:
                self._pending_orders[order_id]["status"] = "FAILED"
                self._pending_orders[order_id]["error"] = str(e)
            
            return None
    
    def _execute_paper_order(self, order: dict) -> Optional[Any]:
        """
        Execute order in PAPER mode — instant fill at market price.
        """
        order_id = order.get("order_id", "")
        trade_id = order.get("trade_id", "")
        now = get_ist_now()
        
        # Get fresh price at execution time
        try:
            quote = self._market_data.get_option_quote(
                symbol=order.get("symbol", ""),
                strike=order.get("strike", 0),
                option_type=order.get("option_type", "CE"),
                expiry=order.get("expiry", ""),
            )
            fill_price = quote.get("ltp", order.get("price", 0))
        except Exception as e:
            logger.warning(
                "Could not fetch execution price: %s | Using order price",
                e
            )
            fill_price = order.get("price", 0)
        
        # Prepare trade data for database
        trade_data = {
            "trade_id": trade_id,
            "order_id": order_id,
            "symbol": order.get("symbol", ""),
            "instrument": order.get("instrument", ""),
            "strike": order.get("strike", 0),
            "option_type": order.get("option_type", "CE"),
            "expiry": order.get("expiry", ""),
            "side": order.get("side", "BUY"),
            "quantity": order.get("quantity", 0),
            "lots": order.get("lots", 1),
            "entry_price": round(fill_price, 2),
            "current_price": round(fill_price, 2),
            "highest_price": round(fill_price, 2),
            "stop_loss": order.get("stop_loss", 0),
            "take_profit": order.get("take_profit", 0),
            "trailing_stop": order.get("trailing_stop", order.get("stop_loss", 0)),
            "status": constants.ORDER_STATUS_OPEN,
            "entry_time": now,
            "mode": "PAPER",
            "confidence": order.get("confidence", 0),
            "reasoning": order.get("reasoning", ""),
            "brain_signals": order.get("brain_signals", {}),
        }
        
        # Save trade to database
        trade = self._trade_repo.save_trade(trade_data)
        
        if trade is None:
            logger.error("Failed to save trade to database")
            return None
        
        # Save position to database
        position_data = {
            "trade_id": trade_id,
            "symbol": order.get("symbol", ""),
            "instrument": order.get("instrument", ""),
            "strike": order.get("strike", 0),
            "option_type": order.get("option_type", "CE"),
            "expiry": order.get("expiry", ""),
            "side": order.get("side", "BUY"),
            "quantity": order.get("quantity", 0),
            "lots": order.get("lots", 1),
            "entry_price": round(fill_price, 2),
            "current_price": round(fill_price, 2),
            "highest_price": round(fill_price, 2),
            "stop_loss": order.get("stop_loss", 0),
            "take_profit": order.get("take_profit", 0),
            "status": "OPEN",
            "opened_at": now,
        }
        
        try:
            self._position_repo.save_position(position_data)
        except Exception as e:
            logger.warning("Could not save position: %s", e)
        
        # Update order status
        order["status"] = constants.ORDER_STATUS_FILLED
        order["executed_at"] = now.isoformat()
        order["fill_price"] = round(fill_price, 2)
        
        # Remove from pending
        if order_id in self._pending_orders:
            del self._pending_orders[order_id]
        
        logger.info(
            "✅ Order FILLED [PAPER] | %s | %s | %s @ ₹%.2f | "
            "Qty: %d | Value: %s",
            order_id[:8],
            order.get("instrument", ""),
            order.get("side", "BUY"),
            fill_price,
            order.get("quantity", 0),
            format_currency(fill_price * order.get("quantity", 0)),
        )
        
        return trade
    
    def _execute_live_order(self, order: dict) -> Optional[Any]:
        """
        Execute order in LIVE mode — send to Dhan API.
        
        TODO: Implement when ready for live trading.
        """
        logger.warning(
            "⚠️ LIVE order execution not yet implemented | %s",
            order.get("instrument", ""),
        )
        
        # Placeholder for future implementation:
        # 1. Call self._dhan_client.place_order(...)
        # 2. Handle response
        # 3. Wait for fill confirmation
        # 4. Save to database
        
        raise NotImplementedError("Live order execution not yet implemented")
    
    # ================================================================ #
    #  CLOSE ORDER                                                      #
    # ================================================================ #
    
    def close_order(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str,
    ) -> Optional[Any]:
        """
        Close an existing open trade.
        
        Parameters
        ----------
        trade_id : str
            The trade_id of the open trade to close.
        exit_price : float
            The price at which to close (current premium).
        exit_reason : str
            Reason for closing: 'SL', 'TP', 'TRAIL', 'TIME', 'MANUAL'.
        
        Returns
        -------
        Trade or None
            The updated Trade object with exit details and P&L.
        """
        try:
            # Get the trade from database
            trade = self._trade_repo.get_trade(trade_id)
            
            if trade is None:
                logger.error("Trade not found: %s", trade_id)
                return None
            
            # Calculate P&L
            entry_price = float(getattr(trade, "entry_price", 0))
            quantity = int(getattr(trade, "quantity", 0))
            side = getattr(trade, "side", "BUY")
            
            # For BUY side: profit when exit > entry
            # For SELL side: profit when exit < entry
            if side == "BUY":
                pnl = (exit_price - entry_price) * quantity
            else:
                pnl = (entry_price - exit_price) * quantity
            
            # Calculate P&L percentage
            if entry_price > 0:
                pnl_percentage = ((exit_price - entry_price) / entry_price) * 100
            else:
                pnl_percentage = 0.0
            
            # Close trade in database
            closed_trade = self._trade_repo.close_trade(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_reason=exit_reason,
            )
            
            if closed_trade is None:
                logger.error("Failed to close trade in database: %s", trade_id)
                return None
            
            # Close position in database
            try:
                self._position_repo.close_position(trade_id)
            except Exception as e:
                logger.warning("Could not close position: %s", e)
            
            # Format P&L for logging
            instrument = getattr(trade, "instrument", "?")
            pnl_str = format_pnl(pnl)
            
            if pnl >= 0:
                emoji = "🟢"
            else:
                emoji = "🔴"
            
            logger.info(
                "%s Order CLOSED | %s | %s | Entry: ₹%.2f → Exit: ₹%.2f | "
                "P&L: %s (%.1f%%) | Reason: %s",
                emoji,
                trade_id[:8],
                instrument,
                entry_price,
                exit_price,
                pnl_str,
                pnl_percentage,
                exit_reason,
            )
            
            return closed_trade
        
        except Exception as e:
            logger.error(
                "❌ Failed to close order %s: %s",
                trade_id[:8] if trade_id else "?",
                str(e),
            )
            return None
    
    # ================================================================ #
    #  CANCEL ORDER                                                     #
    # ================================================================ #
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a pending order before execution.
        
        Parameters
        ----------
        order_id : str
            The order_id of the pending order to cancel.
        
        Returns
        -------
        bool
            True if cancelled successfully, False otherwise.
        """
        if order_id not in self._pending_orders:
            logger.warning(
                "Cannot cancel order %s: not found in pending orders",
                order_id[:8] if order_id else "?",
            )
            return False
        
        order = self._pending_orders[order_id]
        
        # Check if already executed
        if order.get("status") == constants.ORDER_STATUS_FILLED:
            logger.warning(
                "Cannot cancel order %s: already filled",
                order_id[:8],
            )
            return False
        
        # Update status
        order["status"] = constants.ORDER_STATUS_CANCELLED
        order["cancelled_at"] = get_ist_now().isoformat()
        
        # Remove from pending
        del self._pending_orders[order_id]
        
        logger.info(
            "🚫 Order CANCELLED | %s | %s",
            order_id[:8],
            order.get("instrument", ""),
        )
        
        return True
    
    # ================================================================ #
    #  QUERY METHODS                                                    #
    # ================================================================ #
    
    def get_open_orders(self) -> List[Any]:
        """
        Get all currently open trades.
        
        Returns
        -------
        list
            List of open Trade objects from database.
        """
        try:
            open_trades = self._trade_repo.get_open_trades()
            if open_trades is None:
                return []
            return list(open_trades)
        except Exception as e:
            logger.error("Error fetching open orders: %s", e)
            return []
    
    def get_order_status(self, order_id: str) -> dict:
        """
        Get status of a specific order.
        
        Parameters
        ----------
        order_id : str
            The order_id to look up.
        
        Returns
        -------
        dict
            Order status dict with current state.
        """
        # Check pending orders first
        if order_id in self._pending_orders:
            return self._pending_orders[order_id].copy()
        
        # Try to find in database by order_id
        # (would need to add this method to trade_repo)
        return {
            "order_id": order_id,
            "status": "NOT_FOUND",
            "message": "Order not found in pending orders or executed recently",
        }
    
    def get_pending_count(self) -> int:
        """Get count of pending (unexecuted) orders."""
        return len(self._pending_orders)
    
    def get_order_summary(self) -> dict:
        """
        Get summary of order manager state.
        
        Returns
        -------
        dict
            Summary including mode, pending count, open count.
        """
        open_orders = self.get_open_orders()
        
        return {
            "mode": self._mode,
            "is_paper": self._paper_mode,
            "pending_orders": len(self._pending_orders),
            "open_positions": len(open_orders),
            "pending_order_ids": list(self._pending_orders.keys()),
        }
    
    # ================================================================ #
    #  DUNDER METHODS                                                   #
    # ================================================================ #
    
    def __repr__(self) -> str:
        return (
            f"OrderManager(mode={self._mode}, "
            f"pending={len(self._pending_orders)}, "
            f"open={len(self.get_open_orders())})"
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
    print("  ORDER MANAGER - Standalone Test")
    print("=" * 65)
    
    # ── Mock classes ─────────────────────────────────────────────────
    class MockSettings:
        PAPER_TRADING = True
        INITIAL_CAPITAL = 10_000.0
    
    class MockMarketData:
        def get_option_quote(self, symbol, strike, option_type, expiry):
            return {
                "ltp": 125.50,
                "bid": 125.00,
                "ask": 126.00,
                "volume": 10000,
            }
    
    class MockTrade:
        def __init__(self, data):
            for key, value in data.items():
                setattr(self, key, value)
    
    class MockTradeRepo:
        def __init__(self):
            self._trades = {}
        
        def save_trade(self, data):
            trade = MockTrade(data)
            self._trades[data["trade_id"]] = trade
            return trade
        
        def get_trade(self, trade_id):
            return self._trades.get(trade_id)
        
        def get_open_trades(self):
            return [t for t in self._trades.values() 
                    if getattr(t, "status", "") == constants.ORDER_STATUS_OPEN]
        
        def close_trade(self, trade_id, exit_price, exit_reason):
            trade = self._trades.get(trade_id)
            if trade:
                trade.status = constants.ORDER_STATUS_CLOSED
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
            self._positions[data["trade_id"]] = data
        
        def close_position(self, trade_id):
            if trade_id in self._positions:
                del self._positions[trade_id]
        
        def get_open_positions(self):
            return list(self._positions.values())
    
    # ── Create OrderManager ──────────────────────────────────────────
    settings_mock = MockSettings()
    market_data = MockMarketData()
    trade_repo = MockTradeRepo()
    position_repo = MockPositionRepo()
    
    om = OrderManager(settings_mock, market_data, trade_repo, position_repo)
    
    print(f"\n  {om}")
    print(f"  Mode: {om.mode}")
    print(f"  Is Paper: {om.is_paper_mode}")
    
    # ── Test 1: Create Order ─────────────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 1: Create Order")
    print("-" * 65)
    
    trade_params = {
        "symbol": "NIFTY",
        "instrument": "NIFTY 24500 CE",
        "strike": 24500,
        "option_type": "CE",
        "expiry": "2025-01-30",
        "side": "BUY",
        "quantity": 25,
        "lots": 1,
        "lot_size": 25,
        "entry_price": 120.0,
        "stop_loss": 84.0,
        "take_profit": 180.0,
        "trailing_stop": 84.0,
        "confidence": 0.75,
        "reasoning": "RSI oversold, MACD bullish crossover",
        "brain_signals": {"technical": {"action": "BUY"}},
        "max_loss": 900.0,
        "max_profit": 1500.0,
        "capital_required": 3000.0,
    }
    
    order = om.create_order(trade_params)
    
    print(f"\n  Order ID: {order['order_id'][:8]}...")
    print(f"  Trade ID: {order['trade_id'][:8]}...")
    print(f"  Instrument: {order['instrument']}")
    print(f"  Price: ₹{order['price']}")
    print(f"  Status: {order['status']}")
    print(f"  Pending orders: {om.get_pending_count()}")
    
    # ── Test 2: Execute Order ────────────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 2: Execute Order (Paper Mode)")
    print("-" * 65)
    
    trade = om.execute_order(order)
    
    if trade:
        print(f"\n  Trade saved: {trade.trade_id[:8]}...")
        print(f"  Entry price: ₹{trade.entry_price}")
        print(f"  Status: {trade.status}")
        print(f"  Pending orders: {om.get_pending_count()}")
        print(f"  Open orders: {len(om.get_open_orders())}")
    else:
        print("  ❌ Trade execution failed")
    
    # ── Test 3: Get Open Orders ──────────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 3: Get Open Orders")
    print("-" * 65)
    
    open_orders = om.get_open_orders()
    print(f"\n  Open orders count: {len(open_orders)}")
    for o in open_orders:
        print(f"    - {o.instrument} @ ₹{o.entry_price}")
    
    # ── Test 4: Close Order (Take Profit) ────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 4: Close Order (Take Profit)")
    print("-" * 65)
    
    if trade:
        closed = om.close_order(
            trade_id=trade.trade_id,
            exit_price=175.0,
            exit_reason="TP",
        )
        
        if closed:
            print(f"\n  Closed trade: {closed.trade_id[:8]}...")
            print(f"  Exit price: ₹{closed.exit_price}")
            print(f"  P&L: {format_pnl(closed.pnl)}")
            print(f"  Status: {closed.status}")
            print(f"  Open orders: {len(om.get_open_orders())}")
    
    # ── Test 5: Cancel Pending Order ─────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 5: Cancel Pending Order")
    print("-" * 65)
    
    # Create another order
    order2 = om.create_order(trade_params)
    print(f"\n  Created order: {order2['order_id'][:8]}...")
    print(f"  Pending count: {om.get_pending_count()}")
    
    # Cancel it
    cancelled = om.cancel_order(order2["order_id"])
    print(f"  Cancelled: {cancelled}")
    print(f"  Pending count: {om.get_pending_count()}")
    
    # ── Test 6: Order Summary ────────────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 6: Order Summary")
    print("-" * 65)
    
    summary = om.get_order_summary()
    for key, value in summary.items():
        print(f"  {key}: {value}")
    
    # ── Test 7: Close with Stop Loss ─────────────────────────────────
    print("\n" + "-" * 65)
    print("  TEST 7: Close Order (Stop Loss)")
    print("-" * 65)
    
    # Create and execute another order
    order3 = om.create_order(trade_params)
    trade3 = om.execute_order(order3)
    
    if trade3:
        closed_sl = om.close_order(
            trade_id=trade3.trade_id,
            exit_price=80.0,  # Below stop loss
            exit_reason="SL",
        )
        
        if closed_sl:
            print(f"\n  Closed (SL): {closed_sl.trade_id[:8]}...")
            print(f"  Exit price: ₹{closed_sl.exit_price}")
            print(f"  P&L: {format_pnl(closed_sl.pnl)}")
    
    print("\n" + "=" * 65)
    print("  ✅ All OrderManager tests completed!")
    print("=" * 65 + "\n")