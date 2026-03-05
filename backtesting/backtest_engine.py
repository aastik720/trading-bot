"""
Backtest Engine - Strategy Testing on Historical Data
======================================================

This engine simulates trading on historical data to evaluate
strategy performance BEFORE risking real money.

Features:
    - Candle-by-candle simulation
    - Stop Loss and Take Profit simulation
    - Comprehensive performance metrics
    - Equity curve tracking
    - Sharpe ratio, drawdown, profit factor
    - CSV report generation

Usage:
    from backtesting.backtest_engine import BacktestEngine
    from brains.technical import TechnicalBrain
    
    engine = BacktestEngine(settings, initial_capital=100000)
    results = engine.run("NIFTY", historical_data, TechnicalBrain())
    engine.print_report(results)

Author: Trading Bot
Phase: 10 - Polish & Enhancement
"""

import logging
import math
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
import csv
import os

try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    pd = None
    np = None

from config.settings import settings
from config import constants
from utils.helpers import (
    format_currency,
    format_pnl,
    format_duration,
    get_atm_strike,
    safe_divide,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BacktestTrade:
    """Represents a single trade in backtest."""
    trade_no: int
    entry_date: datetime
    entry_price: float
    quantity: int
    stop_loss: float
    take_profit: float
    direction: str = "LONG"  # LONG or SHORT
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    capital_after: float = 0.0
    duration_seconds: float = 0.0
    
    @property
    def is_open(self) -> bool:
        return self.exit_date is None
    
    @property
    def is_winner(self) -> bool:
        return self.pnl > 0
    
    def to_dict(self) -> Dict:
        return {
            "trade_no": self.trade_no,
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "exit_reason": self.exit_reason,
            "capital_after": self.capital_after,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class EquityPoint:
    """Represents a point in the equity curve."""
    date: datetime
    equity: float
    drawdown: float = 0.0
    drawdown_pct: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# MOCK MARKET DATA FOR BACKTESTING
# ══════════════════════════════════════════════════════════════════════════════

class MockMarketData:
    """
    Mock market data that provides historical data up to current candle.
    
    This allows brains to analyze data as if they're seeing it live,
    without peeking into the future.
    """
    
    def __init__(self, df: 'pd.DataFrame', current_index: int, symbol: str):
        """
        Initialize mock market data.
        
        Args:
            df: Full historical DataFrame
            current_index: Current candle index (only data up to this is visible)
            symbol: Symbol being analyzed
        """
        self._df = df
        self._current_index = current_index
        self._symbol = symbol
    
    def get_historical(self, symbol: str, days: int = 50) -> 'pd.DataFrame':
        """Return historical data up to current candle."""
        if not PANDAS_AVAILABLE:
            return None
        
        # Only return data up to (and including) current index
        start_idx = max(0, self._current_index - days + 1)
        return self._df.iloc[start_idx:self._current_index + 1].copy()
    
    def get_spot_price(self, symbol: str) -> float:
        """Return current close price."""
        if self._current_index < len(self._df):
            return float(self._df.iloc[self._current_index]['close'])
        return 0.0
    
    def get_quote(self, symbol: str) -> Dict:
        """Return current quote."""
        if self._current_index < len(self._df):
            row = self._df.iloc[self._current_index]
            return {
                "ltp": float(row['close']),
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close']),
                "volume": int(row.get('volume', 0)),
            }
        return {}
    
    def get_news(self, symbol: str, limit: int = 20) -> List[Dict]:
        """Return empty news (not available in backtest)."""
        return []
    
    def get_option_chain(self, symbol: str) -> List[Dict]:
        """Return empty option chain."""
        return []
    
    def get_option_quote(self, symbol: str, strike: float, option_type: str, expiry: str) -> Dict:
        """Return simulated option quote based on spot price."""
        spot = self.get_spot_price(symbol)
        
        # Simple option price simulation (for backtesting purposes)
        # In reality, option prices depend on many factors
        strike_diff = abs(spot - strike)
        base_price = max(50, spot * 0.01)  # ~1% of spot as base
        
        # ATM options are more expensive
        if strike_diff < 100:
            price = base_price * 1.5
        else:
            price = base_price * (1 - strike_diff / spot * 2)
            price = max(10, price)  # Minimum ₹10
        
        return {"ltp": price}
    
    def get_current_expiry(self, symbol: str) -> str:
        """Return a dummy expiry."""
        return "WEEKLY"


# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class BacktestEngine:
    """
    Backtest Engine - Simulates trading on historical data.
    
    This engine:
    1. Iterates through historical candles one by one
    2. Feeds each candle to the brain for analysis
    3. Executes trades based on brain signals
    4. Tracks equity curve and calculates metrics
    
    Attributes:
        capital: Current capital
        initial_capital: Starting capital
        trades: List of all trades
        equity_curve: List of equity points
        
    Example:
        >>> engine = BacktestEngine(settings, initial_capital=100000)
        >>> brain = TechnicalBrain()
        >>> results = engine.run("NIFTY", historical_df, brain)
        >>> engine.print_report(results)
    """
    
    # Default settings
    DEFAULT_CAPITAL = 100000
    DEFAULT_LOT_SIZE = 25  # NIFTY lot size
    DEFAULT_SL_PCT = 0.30  # 30% stop loss
    DEFAULT_TP_PCT = 0.50  # 50% take profit
    DEFAULT_CAPITAL_PER_TRADE_PCT = 0.10  # 10% of capital per trade
    
    def __init__(
        self,
        settings=None,
        initial_capital: float = None,
    ):
        """
        Initialize the backtest engine.
        
        Args:
            settings: Application settings (optional)
            initial_capital: Starting capital (default: 100000)
        """
        if not PANDAS_AVAILABLE:
            raise ImportError("pandas and numpy are required for backtesting")
        
        self._settings = settings
        self._initial_capital = initial_capital or self.DEFAULT_CAPITAL
        
        # Load settings
        if settings:
            self._sl_pct = float(getattr(settings, "STOP_LOSS_PERCENTAGE", 30)) / 100
            self._tp_pct = float(getattr(settings, "TAKE_PROFIT_PERCENTAGE", 50)) / 100
            self._capital_per_trade_pct = float(getattr(settings, "MAX_CAPITAL_PER_TRADE", 2500)) / self._initial_capital
        else:
            self._sl_pct = self.DEFAULT_SL_PCT
            self._tp_pct = self.DEFAULT_TP_PCT
            self._capital_per_trade_pct = self.DEFAULT_CAPITAL_PER_TRADE_PCT
        
        # State
        self._capital = self._initial_capital
        self._trades: List[BacktestTrade] = []
        self._equity_curve: List[EquityPoint] = []
        self._current_trade: Optional[BacktestTrade] = None
        self._trade_count = 0
        
        # Tracking
        self._start_date: Optional[datetime] = None
        self._end_date: Optional[datetime] = None
        self._peak_equity = self._initial_capital
        
        logger.info(f"BacktestEngine initialized with capital: {format_currency(self._initial_capital)}")
    
    # ══════════════════════════════════════════════════════════════════════════
    # MAIN RUN METHOD
    # ══════════════════════════════════════════════════════════════════════════
    
    def run(
        self,
        symbol: str,
        historical_data: 'pd.DataFrame',
        brain,
        lot_size: int = None,
        min_candles: int = 50,
    ) -> Dict[str, Any]:
        """
        Run backtest on historical data.
        
        Args:
            symbol: Symbol to backtest (e.g., "NIFTY")
            historical_data: DataFrame with OHLCV columns
            brain: Brain instance (TechnicalBrain, PatternBrain, etc.)
            lot_size: Lot size for the symbol (default: 25 for NIFTY)
            min_candles: Minimum candles needed before trading (default: 50)
            
        Returns:
            Dict with comprehensive backtest results
            
        Example:
            >>> results = engine.run("NIFTY", df, TechnicalBrain())
            >>> print(f"Win Rate: {results['win_rate']:.1f}%")
        """
        logger.info(f"Starting backtest for {symbol}...")
        logger.info(f"Data range: {len(historical_data)} candles")
        
        # Reset state
        self._reset()
        
        # Validate data
        if historical_data is None or len(historical_data) < min_candles:
            logger.error(f"Insufficient data: {len(historical_data) if historical_data is not None else 0} candles")
            return self._empty_results()
        
        # Standardize column names
        df = self._standardize_dataframe(historical_data)
        
        # Set lot size
        if lot_size is None:
            lot_size = constants.LOT_SIZE_NIFTY if symbol == "NIFTY" else constants.LOT_SIZE_BANKNIFTY
        
        # Record date range
        self._start_date = self._get_candle_date(df, 0)
        self._end_date = self._get_candle_date(df, len(df) - 1)
        
        logger.info(f"Backtest period: {self._start_date} to {self._end_date}")
        
        # ═══════════════════════════════════════════════════════════════════
        # MAIN SIMULATION LOOP
        # ═══════════════════════════════════════════════════════════════════
        
        for i in range(min_candles, len(df)):
            candle_date = self._get_candle_date(df, i)
            current_candle = df.iloc[i]
            
            # Update equity curve
            self._update_equity_curve(candle_date)
            
            # Check if we have an open position
            if self._current_trade is not None:
                # Check for exit conditions using current candle's high/low
                exit_triggered = self._check_exit_conditions(
                    current_candle, candle_date
                )
                
                if exit_triggered:
                    continue  # Position was closed, don't take new trade this candle
            
            # No open position - analyze for entry
            if self._current_trade is None:
                # Create mock market data up to current candle
                mock_data = MockMarketData(df, i, symbol)
                
                try:
                    # Get brain signal
                    signal = brain.analyze(symbol, mock_data)
                    
                    action = signal.get("action", constants.SIGNAL_HOLD)
                    confidence = signal.get("confidence", 0.0)
                    
                    # Check for entry signal
                    min_confidence = 0.6  # Minimum confidence to trade
                    
                    if action == constants.SIGNAL_BUY and confidence >= min_confidence:
                        # Enter trade at next candle's open price
                        if i + 1 < len(df):
                            next_candle = df.iloc[i + 1]
                            entry_price = float(next_candle['open'])
                            entry_date = self._get_candle_date(df, i + 1)
                            
                            self._open_trade(
                                entry_date=entry_date,
                                entry_price=entry_price,
                                lot_size=lot_size,
                            )
                    
                except Exception as e:
                    logger.debug(f"Brain analysis error at candle {i}: {e}")
                    continue
        
        # Close any remaining open position at last price
        if self._current_trade is not None:
            last_candle = df.iloc[-1]
            last_date = self._get_candle_date(df, len(df) - 1)
            self._close_trade(
                exit_date=last_date,
                exit_price=float(last_candle['close']),
                exit_reason="END_OF_DATA",
            )
        
        # Calculate final results
        results = self._calculate_results()
        
        logger.info(f"Backtest complete: {results['total_trades']} trades, "
                   f"{results['win_rate']:.1f}% win rate, "
                   f"{format_pnl(results['total_pnl'])}")
        
        return results
    
    # ══════════════════════════════════════════════════════════════════════════
    # TRADE MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════
    
    def _open_trade(
        self,
        entry_date: datetime,
        entry_price: float,
        lot_size: int,
    ) -> None:
        """
        Open a new trade.
        
        Args:
            entry_date: Entry datetime
            entry_price: Entry price
            lot_size: Lot size for position sizing
        """
        # Calculate position size
        capital_per_trade = self._capital * self._capital_per_trade_pct
        lots = max(1, int(capital_per_trade / (entry_price * lot_size)))
        quantity = lots * lot_size
        
        # Calculate SL and TP
        stop_loss = entry_price * (1 - self._sl_pct)
        take_profit = entry_price * (1 + self._tp_pct)
        
        self._trade_count += 1
        
        self._current_trade = BacktestTrade(
            trade_no=self._trade_count,
            entry_date=entry_date,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        
        logger.debug(f"Trade #{self._trade_count} opened at {format_currency(entry_price)}")
    
    def _close_trade(
        self,
        exit_date: datetime,
        exit_price: float,
        exit_reason: str,
    ) -> None:
        """
        Close the current trade.
        
        Args:
            exit_date: Exit datetime
            exit_price: Exit price
            exit_reason: Reason for exit (SL, TP, SIGNAL, END_OF_DATA)
        """
        if self._current_trade is None:
            return
        
        trade = self._current_trade
        
        # Calculate P&L
        pnl = (exit_price - trade.entry_price) * trade.quantity
        pnl_pct = ((exit_price - trade.entry_price) / trade.entry_price) * 100
        
        # Update trade
        trade.exit_date = exit_date
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.pnl = pnl
        trade.pnl_pct = pnl_pct
        
        # Calculate duration
        if trade.entry_date and trade.exit_date:
            duration = trade.exit_date - trade.entry_date
            trade.duration_seconds = duration.total_seconds()
        
        # Update capital
        self._capital += pnl
        trade.capital_after = self._capital
        
        # Track peak for drawdown
        if self._capital > self._peak_equity:
            self._peak_equity = self._capital
        
        # Save trade
        self._trades.append(trade)
        self._current_trade = None
        
        logger.debug(f"Trade #{trade.trade_no} closed: {format_pnl(pnl)} ({pnl_pct:+.1f}%)")
    
    def _check_exit_conditions(
        self,
        candle: 'pd.Series',
        candle_date: datetime,
    ) -> bool:
        """
        Check if current candle triggers exit conditions.
        
        Uses candle's high/low to check if SL or TP was hit.
        
        Args:
            candle: Current candle data
            candle_date: Candle datetime
            
        Returns:
            True if position was closed
        """
        if self._current_trade is None:
            return False
        
        trade = self._current_trade
        high = float(candle['high'])
        low = float(candle['low'])
        close = float(candle['close'])
        
        # Check Stop Loss (hit if low <= stop_loss)
        if low <= trade.stop_loss:
            self._close_trade(
                exit_date=candle_date,
                exit_price=trade.stop_loss,  # Assume filled at SL price
                exit_reason="STOP_LOSS",
            )
            return True
        
        # Check Take Profit (hit if high >= take_profit)
        if high >= trade.take_profit:
            self._close_trade(
                exit_date=candle_date,
                exit_price=trade.take_profit,  # Assume filled at TP price
                exit_reason="TAKE_PROFIT",
            )
            return True
        
        return False
    
    # ══════════════════════════════════════════════════════════════════════════
    # METRICS CALCULATION
    # ══════════════════════════════════════════════════════════════════════════
    
    def _calculate_results(self) -> Dict[str, Any]:
        """
        Calculate comprehensive backtest results.
        
        Returns:
            Dict with all performance metrics
        """
        if not self._trades:
            return self._empty_results()
        
        # Basic counts
        total_trades = len(self._trades)
        winners = [t for t in self._trades if t.is_winner]
        losers = [t for t in self._trades if not t.is_winner]
        winning_trades = len(winners)
        losing_trades = len(losers)
        
        # P&L metrics
        total_pnl = sum(t.pnl for t in self._trades)
        total_pnl_pct = (total_pnl / self._initial_capital) * 100
        
        wins_pnl = [t.pnl for t in winners]
        losses_pnl = [t.pnl for t in losers]
        
        avg_win = sum(wins_pnl) / len(wins_pnl) if wins_pnl else 0
        avg_loss = sum(losses_pnl) / len(losses_pnl) if losses_pnl else 0
        
        avg_win_pct = sum(t.pnl_pct for t in winners) / len(winners) if winners else 0
        avg_loss_pct = sum(t.pnl_pct for t in losers) / len(losers) if losers else 0
        
        largest_win = max(wins_pnl) if wins_pnl else 0
        largest_loss = min(losses_pnl) if losses_pnl else 0
        
        # Win rate
        win_rate = (winning_trades / total_trades * 100) if total_trades else 0
        
        # Profit factor
        profit_factor = self._calculate_profit_factor(wins_pnl, losses_pnl)
        
        # Risk metrics
        daily_returns = self._calculate_daily_returns()
        sharpe_ratio = self._calculate_sharpe_ratio(daily_returns)
        max_dd, max_dd_pct = self._calculate_max_drawdown()
        
        # Duration
        durations = [t.duration_seconds for t in self._trades if t.duration_seconds > 0]
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        # Equity curve for output
        equity_curve = [
            {"date": ep.date.isoformat(), "equity": ep.equity}
            for ep in self._equity_curve
        ]
        
        # Trades for output
        trades_list = [t.to_dict() for t in self._trades]
        
        return {
            # Counts
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            
            # P&L
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "initial_capital": self._initial_capital,
            "final_capital": self._capital,
            
            # Averages
            "avg_pnl": total_pnl / total_trades if total_trades else 0,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
            
            # Extremes
            "largest_win": largest_win,
            "largest_loss": largest_loss,
            
            # Risk metrics
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_dd,
            "max_drawdown_pct": max_dd_pct,
            
            # Duration
            "avg_trade_duration": avg_duration,
            "avg_trade_duration_str": format_duration(avg_duration),
            
            # Date range
            "start_date": self._start_date.isoformat() if self._start_date else None,
            "end_date": self._end_date.isoformat() if self._end_date else None,
            
            # Data
            "equity_curve": equity_curve,
            "trades": trades_list,
        }
    
    def _calculate_sharpe_ratio(self, returns: List[float]) -> float:
        """
        Calculate Sharpe ratio.
        
        Sharpe = mean(returns) / std(returns) * sqrt(252)
        
        Args:
            returns: List of daily returns
            
        Returns:
            Sharpe ratio (0 if insufficient data)
        """
        if not returns or len(returns) < 2:
            return 0.0
        
        if not PANDAS_AVAILABLE:
            return 0.0
        
        returns_array = np.array(returns)
        mean_return = np.mean(returns_array)
        std_return = np.std(returns_array, ddof=1)
        
        if std_return == 0:
            return 0.0
        
        # Annualized Sharpe (252 trading days)
        sharpe = (mean_return / std_return) * np.sqrt(252)
        
        return float(sharpe)
    
    def _calculate_max_drawdown(self) -> Tuple[float, float]:
        """
        Calculate maximum drawdown.
        
        Returns:
            Tuple of (max_drawdown_amount, max_drawdown_percentage)
        """
        if not self._equity_curve:
            return 0.0, 0.0
        
        peak = self._initial_capital
        max_dd = 0.0
        max_dd_pct = 0.0
        
        for point in self._equity_curve:
            if point.equity > peak:
                peak = point.equity
            
            dd = peak - point.equity
            dd_pct = (dd / peak * 100) if peak > 0 else 0
            
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct
        
        return max_dd, max_dd_pct
    
    def _calculate_profit_factor(
        self,
        wins: List[float],
        losses: List[float]
    ) -> float:
        """
        Calculate profit factor.
        
        Profit Factor = sum(wins) / abs(sum(losses))
        
        Args:
            wins: List of winning trade P&Ls
            losses: List of losing trade P&Ls
            
        Returns:
            Profit factor (0 if no losses)
        """
        total_wins = sum(wins) if wins else 0
        total_losses = abs(sum(losses)) if losses else 0
        
        if total_losses == 0:
            return float('inf') if total_wins > 0 else 0.0
        
        return total_wins / total_losses
    
    def _calculate_daily_returns(self) -> List[float]:
        """
        Calculate daily returns from equity curve.
        
        Returns:
            List of daily percentage returns
        """
        if len(self._equity_curve) < 2:
            return []
        
        returns = []
        for i in range(1, len(self._equity_curve)):
            prev_equity = self._equity_curve[i - 1].equity
            curr_equity = self._equity_curve[i].equity
            
            if prev_equity > 0:
                daily_return = (curr_equity - prev_equity) / prev_equity
                returns.append(daily_return)
        
        return returns
    
    # ══════════════════════════════════════════════════════════════════════════
    # REPORTING
    # ══════════════════════════════════════════════════════════════════════════
    
    def print_report(self, results: Dict[str, Any]) -> None:
        """
        Print formatted backtest report to console.
        
        Args:
            results: Results dict from run()
        """
        print("\n")
        print("═" * 50)
        print("           BACKTEST REPORT")
        print("═" * 50)
        
        # Period
        start = results.get("start_date", "N/A")
        end = results.get("end_date", "N/A")
        if start != "N/A":
            start = start[:10] if isinstance(start, str) else start
        if end != "N/A":
            end = end[:10] if isinstance(end, str) else end
        
        print(f"\n  Period:          {start} to {end}")
        print(f"  Initial Capital: {format_currency(results.get('initial_capital', 0))}")
        print(f"  Final Capital:   {format_currency(results.get('final_capital', 0))}")
        
        # P&L
        total_pnl = results.get('total_pnl', 0)
        total_pnl_pct = results.get('total_pnl_pct', 0)
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        
        print(f"\n  {pnl_emoji} Total P&L:    {format_pnl(total_pnl)} ({total_pnl_pct:+.1f}%)")
        
        # Trades
        total = results.get('total_trades', 0)
        wins = results.get('winning_trades', 0)
        losses = results.get('losing_trades', 0)
        win_rate = results.get('win_rate', 0)
        
        print(f"\n  Total Trades:    {total}")
        print(f"  Win Rate:        {win_rate:.1f}% ({wins}W / {losses}L)")
        
        # Averages
        avg_win = results.get('avg_win', 0)
        avg_loss = results.get('avg_loss', 0)
        avg_win_pct = results.get('avg_win_pct', 0)
        avg_loss_pct = results.get('avg_loss_pct', 0)
        
        print(f"\n  Avg Win:         {format_currency(avg_win)} ({avg_win_pct:+.1f}%)")
        print(f"  Avg Loss:        {format_currency(avg_loss)} ({avg_loss_pct:+.1f}%)")
        
        # Extremes
        largest_win = results.get('largest_win', 0)
        largest_loss = results.get('largest_loss', 0)
        
        print(f"  Largest Win:     {format_currency(largest_win)}")
        print(f"  Largest Loss:    {format_currency(largest_loss)}")
        
        # Risk metrics
        profit_factor = results.get('profit_factor', 0)
        sharpe = results.get('sharpe_ratio', 0)
        max_dd = results.get('max_drawdown', 0)
        max_dd_pct = results.get('max_drawdown_pct', 0)
        
        print(f"\n  Profit Factor:   {profit_factor:.2f}")
        print(f"  Sharpe Ratio:    {sharpe:.2f}")
        print(f"  Max Drawdown:    {format_currency(max_dd)} ({max_dd_pct:.1f}%)")
        
        # Duration
        avg_duration = results.get('avg_trade_duration_str', 'N/A')
        print(f"\n  Avg Duration:    {avg_duration}")
        
        print("\n" + "═" * 50)
        print("")
    
    def generate_csv_report(
        self,
        results: Dict[str, Any],
        filename: str = "backtest_results.csv"
    ) -> str:
        """
        Generate CSV file with all trades.
        
        Args:
            results: Results dict from run()
            filename: Output filename
            
        Returns:
            Path to generated file
        """
        trades = results.get("trades", [])
        
        if not trades:
            logger.warning("No trades to export")
            return ""
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else ".", exist_ok=True)
        
        # Write CSV
        fieldnames = [
            "trade_no", "entry_date", "exit_date", "entry_price", "exit_price",
            "quantity", "stop_loss", "take_profit", "pnl", "pnl_pct",
            "exit_reason", "capital_after"
        ]
        
        with open(filename, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for trade in trades:
                row = {k: trade.get(k, "") for k in fieldnames}
                # Format numbers
                for key in ["entry_price", "exit_price", "stop_loss", "take_profit", "pnl", "pnl_pct", "capital_after"]:
                    if key in row and row[key]:
                        row[key] = f"{row[key]:.2f}"
                writer.writerow(row)
        
        logger.info(f"CSV report saved: {filename}")
        return filename
    
    # ══════════════════════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════════════════════
    
    def _reset(self) -> None:
        """Reset engine state for new backtest."""
        self._capital = self._initial_capital
        self._trades = []
        self._equity_curve = []
        self._current_trade = None
        self._trade_count = 0
        self._peak_equity = self._initial_capital
        self._start_date = None
        self._end_date = None
    
    def _standardize_dataframe(self, df: 'pd.DataFrame') -> 'pd.DataFrame':
        """
        Standardize DataFrame column names.
        
        Args:
            df: Input DataFrame
            
        Returns:
            DataFrame with lowercase column names
        """
        df = df.copy()
        df.columns = [col.lower() for col in df.columns]
        
        # Ensure required columns exist
        required = ['open', 'high', 'low', 'close']
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")
        
        # Fill NaN values
        df = df.ffill().bfill()
        
        return df
    
    def _get_candle_date(self, df: 'pd.DataFrame', index: int) -> datetime:
        """
        Get datetime for a candle.
        
        Args:
            df: DataFrame
            index: Candle index
            
        Returns:
            datetime object
        """
        if df.index.dtype == 'datetime64[ns]' or hasattr(df.index, 'to_pydatetime'):
            return df.index[index].to_pydatetime()
        elif 'date' in df.columns:
            return pd.to_datetime(df.iloc[index]['date']).to_pydatetime()
        elif 'datetime' in df.columns:
            return pd.to_datetime(df.iloc[index]['datetime']).to_pydatetime()
        else:
            # Use index as days from start
            return datetime.now() - timedelta(days=len(df) - index)
    
    def _update_equity_curve(self, current_date: datetime) -> None:
        """
        Update equity curve with current capital.
        
        Args:
            current_date: Current datetime
        """
        # Calculate current equity including open position
        equity = self._capital
        
        if self._current_trade is not None:
            # Add unrealized P&L (not implemented for simplicity)
            pass
        
        # Calculate drawdown
        drawdown = self._peak_equity - equity
        drawdown_pct = (drawdown / self._peak_equity * 100) if self._peak_equity > 0 else 0
        
        self._equity_curve.append(EquityPoint(
            date=current_date,
            equity=equity,
            drawdown=drawdown,
            drawdown_pct=drawdown_pct,
        ))
    
    def _empty_results(self) -> Dict[str, Any]:
        """Return empty results dict."""
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "initial_capital": self._initial_capital,
            "final_capital": self._initial_capital,
            "avg_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
            "profit_factor": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "avg_trade_duration": 0.0,
            "avg_trade_duration_str": "0s",
            "start_date": None,
            "end_date": None,
            "equity_curve": [],
            "trades": [],
        }


# ══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """
    Run backtest with TechnicalBrain on sample data.
    
    Usage: python -m backtesting.backtest_engine
    """
    import sys
    
    print("\n" + "=" * 60)
    print("  BACKTEST ENGINE - DEMO")
    print("=" * 60)
    
    if not PANDAS_AVAILABLE:
        print("\n  ❌ pandas and numpy are required for backtesting")
        print("  Install: pip install pandas numpy")
        sys.exit(1)
    
    # Generate sample data
    print("\n  Generating sample historical data...")
    
    np.random.seed(42)
    days = 90  # 3 months
    
    # Create dates
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    
    # Generate price data with trend and noise
    base_price = 24000
    prices = [base_price]
    
    for i in range(1, days):
        # Random walk with slight upward trend
        change = np.random.normal(10, 100)  # Mean +10, std 100
        prices.append(prices[-1] + change)
    
    # Generate OHLCV
    data = []
    for i, (date, close) in enumerate(zip(dates, prices)):
        volatility = 80
        open_price = close + np.random.normal(0, volatility * 0.3)
        high = max(open_price, close) + abs(np.random.normal(0, volatility))
        low = min(open_price, close) - abs(np.random.normal(0, volatility))
        volume = int(1000000 + np.random.normal(0, 200000))
        
        data.append({
            'date': date,
            'open': round(open_price, 2),
            'high': round(high, 2),
            'low': round(low, 2),
            'close': round(close, 2),
            'volume': abs(volume),
        })
    
    df = pd.DataFrame(data)
    df.set_index('date', inplace=True)
    
    print(f"  Generated {len(df)} candles")
    print(f"  Date range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Price range: {format_currency(df['low'].min())} to {format_currency(df['high'].max())}")
    
    # Create brain
    print("\n  Loading TechnicalBrain...")
    
    try:
        from brains.technical import TechnicalBrain
        brain = TechnicalBrain()
        print(f"  Brain loaded: {brain.name} (weight: {brain.weight})")
    except ImportError as e:
        print(f"  ❌ Could not import TechnicalBrain: {e}")
        print("  Using a simple mock brain instead...")
        
        # Simple mock brain
        class MockBrain:
            name = "mock"
            weight = 1.0
            
            def analyze(self, symbol, market_data):
                import random
                actions = ["BUY", "HOLD", "HOLD", "HOLD", "HOLD"]  # 20% buy signals
                action = random.choice(actions)
                return {
                    "action": action,
                    "confidence": 0.7 if action == "BUY" else 0.3,
                    "reasoning": "Mock signal",
                }
        
        brain = MockBrain()
    
    # Run backtest
    print("\n  Running backtest...")
    print("-" * 50)
    
    engine = BacktestEngine(initial_capital=100000)
    results = engine.run("NIFTY", df, brain)
    
    # Print report
    engine.print_report(results)
    
    # Generate CSV
    csv_file = "backtest_results.csv"
    if results.get("total_trades", 0) > 0:
        engine.generate_csv_report(results, csv_file)
        print(f"  📄 CSV report saved: {csv_file}")
    
    print("\n" + "=" * 60)
    print("  Backtest complete!")
    print("=" * 60 + "\n")