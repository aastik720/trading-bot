"""
Performance Analyzer - Live Trading Analytics
==============================================

This module analyzes actual trading performance from the database
to provide insights and detailed reports.

Features:
    - Overall performance statistics
    - Daily/Weekly/Monthly breakdowns
    - Instrument-level analysis
    - Brain accuracy tracking
    - Time-based analysis (best hours, days)
    - Risk metrics (drawdown, Sharpe, VaR)
    - Formatted reports for Telegram

Usage:
    from backtesting.performance_analyzer import PerformanceAnalyzer
    
    analyzer = PerformanceAnalyzer(trade_repo, snapshot_repo)
    stats = analyzer.get_overall_stats()
    report = analyzer.format_report('daily')

Author: Trading Bot
Phase: 10 - Polish & Enhancement
"""

import logging
import math
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None

from config import constants
from utils.helpers import (
    format_currency,
    format_pnl,
    format_percentage,
    format_duration,
    get_ist_now,
    safe_divide,
)

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """
    Analyzes trading performance from historical data.
    
    This class queries the database for trades and snapshots,
    then calculates comprehensive performance metrics.
    
    Attributes:
        trade_repo: TradeRepository for accessing trades
        snapshot_repo: SnapshotRepository for daily snapshots
        
    Example:
        >>> analyzer = PerformanceAnalyzer(trade_repo, snapshot_repo)
        >>> stats = analyzer.get_overall_stats()
        >>> print(f"Win Rate: {stats['win_rate']:.1f}%")
        >>> print(f"Total P&L: {format_currency(stats['total_pnl'])}")
    """
    
    def __init__(
        self,
        trade_repository,
        snapshot_repository,
        signal_repository=None,
    ):
        """
        Initialize the performance analyzer.
        
        Args:
            trade_repository: TradeRepository instance
            snapshot_repository: SnapshotRepository instance
            signal_repository: SignalRepository instance (optional)
        """
        self._trade_repo = trade_repository
        self._snapshot_repo = snapshot_repository
        self._signal_repo = signal_repository
        
        logger.info("PerformanceAnalyzer initialized")
    
    # ══════════════════════════════════════════════════════════════════════════
    # OVERALL STATISTICS
    # ══════════════════════════════════════════════════════════════════════════
    
    def get_overall_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive overall trading statistics.
        
        Returns:
            Dict with all performance metrics:
            - total_trades, wins, losses, win_rate
            - total_pnl, avg_pnl_per_trade
            - avg_win, avg_loss, profit_factor
            - best_trade, worst_trade
            - best_day, worst_day
            - streak information
            - duration statistics
        """
        try:
            # Get all closed trades
            all_trades = self._trade_repo.get_trade_history(limit=10000)
            trades = [t for t in all_trades if getattr(t, 'status', '') == 'CLOSED']
            
            if not trades:
                return self._empty_overall_stats()
            
            # Basic counts
            total_trades = len(trades)
            winners = [t for t in trades if (getattr(t, 'pnl', 0) or 0) > 0]
            losers = [t for t in trades if (getattr(t, 'pnl', 0) or 0) <= 0]
            wins = len(winners)
            losses = len(losers)
            win_rate = (wins / total_trades * 100) if total_trades else 0
            
            # P&L calculations
            pnls = [float(getattr(t, 'pnl', 0) or 0) for t in trades]
            total_pnl = sum(pnls)
            avg_pnl = total_pnl / total_trades if total_trades else 0
            
            win_pnls = [float(getattr(t, 'pnl', 0) or 0) for t in winners]
            loss_pnls = [float(getattr(t, 'pnl', 0) or 0) for t in losers]
            
            avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
            avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0
            
            # Profit factor
            total_wins = sum(win_pnls) if win_pnls else 0
            total_losses = abs(sum(loss_pnls)) if loss_pnls else 0
            profit_factor = safe_divide(total_wins, total_losses)
            
            # Best and worst trades
            best_trade = max(pnls) if pnls else 0
            worst_trade = min(pnls) if pnls else 0
            
            # Best and worst trade objects
            best_trade_obj = max(trades, key=lambda t: getattr(t, 'pnl', 0) or 0) if trades else None
            worst_trade_obj = min(trades, key=lambda t: getattr(t, 'pnl', 0) or 0) if trades else None
            
            # Daily P&L for best/worst day
            daily_pnl = self._calculate_daily_pnl(trades)
            best_day_pnl = max(daily_pnl.values()) if daily_pnl else 0
            worst_day_pnl = min(daily_pnl.values()) if daily_pnl else 0
            best_day = max(daily_pnl, key=daily_pnl.get) if daily_pnl else None
            worst_day = min(daily_pnl, key=daily_pnl.get) if daily_pnl else None
            
            # Trading days
            unique_days = set(
                getattr(t, 'entry_time', datetime.now()).date()
                for t in trades
                if hasattr(t, 'entry_time') and t.entry_time
            )
            total_days_traded = len(unique_days)
            avg_trades_per_day = total_trades / total_days_traded if total_days_traded else 0
            
            # Profitable days
            profitable_days = sum(1 for pnl in daily_pnl.values() if pnl > 0)
            losing_days = sum(1 for pnl in daily_pnl.values() if pnl <= 0)
            profitable_days_pct = (profitable_days / len(daily_pnl) * 100) if daily_pnl else 0
            
            # Streaks
            current_streak, streak_type = self._calculate_current_streak(trades)
            longest_win_streak = self._calculate_longest_streak(trades, winning=True)
            longest_lose_streak = self._calculate_longest_streak(trades, winning=False)
            
            # Duration
            durations = []
            for t in trades:
                entry = getattr(t, 'entry_time', None)
                exit_time = getattr(t, 'exit_time', None)
                if entry and exit_time:
                    duration = (exit_time - entry).total_seconds()
                    if duration > 0:
                        durations.append(duration)
            
            avg_duration = sum(durations) / len(durations) if durations else 0
            
            return {
                # Counts
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                
                # P&L
                "total_pnl": total_pnl,
                "avg_pnl_per_trade": avg_pnl,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "profit_factor": profit_factor,
                
                # Extremes
                "best_trade": best_trade,
                "worst_trade": worst_trade,
                "best_trade_instrument": getattr(best_trade_obj, 'instrument', 'N/A') if best_trade_obj else 'N/A',
                "worst_trade_instrument": getattr(worst_trade_obj, 'instrument', 'N/A') if worst_trade_obj else 'N/A',
                
                # Daily
                "best_day": str(best_day) if best_day else None,
                "best_day_pnl": best_day_pnl,
                "worst_day": str(worst_day) if worst_day else None,
                "worst_day_pnl": worst_day_pnl,
                "total_days_traded": total_days_traded,
                "avg_trades_per_day": avg_trades_per_day,
                "profitable_days": profitable_days,
                "losing_days": losing_days,
                "profitable_days_pct": profitable_days_pct,
                
                # Streaks
                "current_streak": current_streak,
                "current_streak_type": streak_type,  # "wins" or "losses"
                "longest_win_streak": longest_win_streak,
                "longest_lose_streak": longest_lose_streak,
                
                # Duration
                "avg_trade_duration": avg_duration,
                "avg_trade_duration_str": format_duration(avg_duration),
            }
            
        except Exception as e:
            logger.error(f"Error calculating overall stats: {e}")
            return self._empty_overall_stats()
    
    def _empty_overall_stats(self) -> Dict[str, Any]:
        """Return empty stats dict."""
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl_per_trade": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "best_trade_instrument": "N/A",
            "worst_trade_instrument": "N/A",
            "best_day": None,
            "best_day_pnl": 0.0,
            "worst_day": None,
            "worst_day_pnl": 0.0,
            "total_days_traded": 0,
            "avg_trades_per_day": 0.0,
            "profitable_days": 0,
            "losing_days": 0,
            "profitable_days_pct": 0.0,
            "current_streak": 0,
            "current_streak_type": "none",
            "longest_win_streak": 0,
            "longest_lose_streak": 0,
            "avg_trade_duration": 0.0,
            "avg_trade_duration_str": "0s",
        }
    
    # ══════════════════════════════════════════════════════════════════════════
    # PERIOD STATISTICS
    # ══════════════════════════════════════════════════════════════════════════
    
    def get_daily_stats(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get daily P&L statistics for the last N days.
        
        Args:
            days: Number of days to look back
            
        Returns:
            List of daily stats dicts, most recent first
        """
        try:
            # Try to get from snapshots first
            snapshots = self._snapshot_repo.get_snapshots(days=days)
            
            if snapshots:
                return [
                    {
                        "date": str(getattr(s, 'date', '')),
                        "pnl": float(getattr(s, 'pnl', 0) or 0),
                        "pnl_pct": float(getattr(s, 'pnl_pct', 0) or 0),
                        "trades": int(getattr(s, 'trades_count', 0) or 0),
                        "wins": int(getattr(s, 'wins', 0) or 0),
                        "losses": int(getattr(s, 'losses', 0) or 0),
                        "win_rate": float(getattr(s, 'win_rate', 0) or 0),
                        "capital": float(getattr(s, 'ending_capital', 0) or 0),
                    }
                    for s in snapshots
                ]
            
            # Fallback: calculate from trades
            all_trades = self._trade_repo.get_trade_history(limit=1000)
            trades = [t for t in all_trades if getattr(t, 'status', '') == 'CLOSED']
            
            # Group by date
            daily_data = defaultdict(lambda: {"pnl": 0, "trades": 0, "wins": 0, "losses": 0})
            
            cutoff_date = date.today() - timedelta(days=days)
            
            for trade in trades:
                entry_time = getattr(trade, 'entry_time', None)
                if not entry_time:
                    continue
                
                trade_date = entry_time.date()
                if trade_date < cutoff_date:
                    continue
                
                pnl = float(getattr(trade, 'pnl', 0) or 0)
                daily_data[trade_date]["pnl"] += pnl
                daily_data[trade_date]["trades"] += 1
                
                if pnl > 0:
                    daily_data[trade_date]["wins"] += 1
                else:
                    daily_data[trade_date]["losses"] += 1
            
            # Convert to list
            result = []
            for d in sorted(daily_data.keys(), reverse=True):
                data = daily_data[d]
                total = data["trades"]
                win_rate = (data["wins"] / total * 100) if total else 0
                
                result.append({
                    "date": str(d),
                    "pnl": data["pnl"],
                    "pnl_pct": 0,  # Would need capital to calculate
                    "trades": total,
                    "wins": data["wins"],
                    "losses": data["losses"],
                    "win_rate": win_rate,
                    "capital": 0,
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting daily stats: {e}")
            return []
    
    def get_weekly_stats(self, weeks: int = 4) -> List[Dict[str, Any]]:
        """
        Get weekly aggregated statistics.
        
        Args:
            weeks: Number of weeks to look back
            
        Returns:
            List of weekly stats dicts
        """
        try:
            daily_stats = self.get_daily_stats(days=weeks * 7)
            
            if not daily_stats:
                return []
            
            # Group by week
            weekly_data = defaultdict(lambda: {
                "pnl": 0, "trades": 0, "wins": 0, "losses": 0, "days": []
            })
            
            for day in daily_stats:
                day_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
                # Get week start (Monday)
                week_start = day_date - timedelta(days=day_date.weekday())
                
                weekly_data[week_start]["pnl"] += day["pnl"]
                weekly_data[week_start]["trades"] += day["trades"]
                weekly_data[week_start]["wins"] += day["wins"]
                weekly_data[week_start]["losses"] += day["losses"]
                weekly_data[week_start]["days"].append(day_date)
            
            # Convert to list
            result = []
            for week_start in sorted(weekly_data.keys(), reverse=True):
                data = weekly_data[week_start]
                week_end = week_start + timedelta(days=6)
                total = data["trades"]
                win_rate = (data["wins"] / total * 100) if total else 0
                
                result.append({
                    "week_start": str(week_start),
                    "week_end": str(week_end),
                    "pnl": data["pnl"],
                    "trades": total,
                    "wins": data["wins"],
                    "losses": data["losses"],
                    "win_rate": win_rate,
                    "trading_days": len(data["days"]),
                })
            
            return result[:weeks]
            
        except Exception as e:
            logger.error(f"Error getting weekly stats: {e}")
            return []
    
    def get_monthly_stats(self, months: int = 3) -> List[Dict[str, Any]]:
        """
        Get monthly aggregated statistics.
        
        Args:
            months: Number of months to look back
            
        Returns:
            List of monthly stats dicts
        """
        try:
            daily_stats = self.get_daily_stats(days=months * 31)
            
            if not daily_stats:
                return []
            
            # Group by month
            monthly_data = defaultdict(lambda: {
                "pnl": 0, "trades": 0, "wins": 0, "losses": 0
            })
            
            for day in daily_stats:
                day_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
                month_key = day_date.strftime("%Y-%m")
                
                monthly_data[month_key]["pnl"] += day["pnl"]
                monthly_data[month_key]["trades"] += day["trades"]
                monthly_data[month_key]["wins"] += day["wins"]
                monthly_data[month_key]["losses"] += day["losses"]
            
            # Convert to list
            result = []
            for month in sorted(monthly_data.keys(), reverse=True):
                data = monthly_data[month]
                total = data["trades"]
                win_rate = (data["wins"] / total * 100) if total else 0
                
                result.append({
                    "month": month,
                    "pnl": data["pnl"],
                    "trades": total,
                    "wins": data["wins"],
                    "losses": data["losses"],
                    "win_rate": win_rate,
                })
            
            return result[:months]
            
        except Exception as e:
            logger.error(f"Error getting monthly stats: {e}")
            return []
    
    # ══════════════════════════════════════════════════════════════════════════
    # INSTRUMENT ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    
    def get_instrument_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Get performance breakdown by instrument/symbol.
        
        Returns:
            Dict mapping instrument to stats:
            {
                "NIFTY": {"trades": 50, "pnl": 5000, "win_rate": 62.0},
                "BANKNIFTY": {"trades": 30, "pnl": 3000, "win_rate": 58.0},
            }
        """
        try:
            all_trades = self._trade_repo.get_trade_history(limit=10000)
            trades = [t for t in all_trades if getattr(t, 'status', '') == 'CLOSED']
            
            if not trades:
                return {}
            
            # Group by symbol
            by_symbol = defaultdict(list)
            
            for trade in trades:
                symbol = getattr(trade, 'symbol', 'UNKNOWN')
                by_symbol[symbol].append(trade)
            
            # Calculate stats for each symbol
            result = {}
            
            for symbol, symbol_trades in by_symbol.items():
                total = len(symbol_trades)
                wins = sum(1 for t in symbol_trades if (getattr(t, 'pnl', 0) or 0) > 0)
                losses = total - wins
                total_pnl = sum(float(getattr(t, 'pnl', 0) or 0) for t in symbol_trades)
                win_rate = (wins / total * 100) if total else 0
                
                win_pnls = [float(getattr(t, 'pnl', 0) or 0) for t in symbol_trades if (getattr(t, 'pnl', 0) or 0) > 0]
                loss_pnls = [float(getattr(t, 'pnl', 0) or 0) for t in symbol_trades if (getattr(t, 'pnl', 0) or 0) <= 0]
                
                avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
                avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0
                
                result[symbol] = {
                    "trades": total,
                    "wins": wins,
                    "losses": losses,
                    "pnl": total_pnl,
                    "win_rate": win_rate,
                    "avg_win": avg_win,
                    "avg_loss": avg_loss,
                }
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting instrument stats: {e}")
            return {}
    
    # ══════════════════════════════════════════════════════════════════════════
    # BRAIN ACCURACY
    # ══════════════════════════════════════════════════════════════════════════
    
    def get_brain_accuracy(self, signal_repository=None) -> Dict[str, Dict[str, Any]]:
        """
        Analyze accuracy of each brain's signals.
        
        Compares signal predictions with actual trade outcomes.
        
        Args:
            signal_repository: SignalRepository (optional, uses init one if not provided)
            
        Returns:
            Dict mapping brain name to accuracy stats:
            {
                "technical": {"signals": 100, "correct": 65, "accuracy": 65.0},
                "sentiment": {"signals": 80, "correct": 45, "accuracy": 56.25},
                "pattern": {"signals": 60, "correct": 35, "accuracy": 58.33},
            }
        """
        try:
            signal_repo = signal_repository or self._signal_repo
            
            if not signal_repo:
                logger.warning("No signal repository available for brain accuracy")
                return self._default_brain_accuracy()
            
            # Get all closed trades with their signals
            all_trades = self._trade_repo.get_trade_history(limit=10000)
            trades = [t for t in all_trades if getattr(t, 'status', '') == 'CLOSED']
            
            if not trades:
                return self._default_brain_accuracy()
            
            # Track brain performance
            brain_stats = defaultdict(lambda: {"signals": 0, "correct": 0})
            
            for trade in trades:
                # Get brain signals from trade
                brain_signals = getattr(trade, 'brain_signals', [])
                trade_pnl = float(getattr(trade, 'pnl', 0) or 0)
                trade_won = trade_pnl > 0
                
                if not brain_signals:
                    continue
                
                for signal in brain_signals:
                    brain_name = signal.get('brain', 'unknown')
                    signal_action = signal.get('action', 'HOLD')
                    
                    # Skip HOLD signals
                    if signal_action == 'HOLD':
                        continue
                    
                    brain_stats[brain_name]["signals"] += 1
                    
                    # Signal was correct if:
                    # - BUY signal and trade was profitable
                    # - SELL signal and trade was profitable (for put options)
                    if signal_action in ['BUY', 'SELL'] and trade_won:
                        brain_stats[brain_name]["correct"] += 1
            
            # Calculate accuracy
            result = {}
            for brain_name in ['technical', 'sentiment', 'pattern']:
                stats = brain_stats.get(brain_name, {"signals": 0, "correct": 0})
                signals = stats["signals"]
                correct = stats["correct"]
                accuracy = (correct / signals * 100) if signals else 0
                
                result[brain_name] = {
                    "signals": signals,
                    "correct": correct,
                    "accuracy": accuracy,
                }
            
            return result
            
        except Exception as e:
            logger.error(f"Error calculating brain accuracy: {e}")
            return self._default_brain_accuracy()
    
    def _default_brain_accuracy(self) -> Dict[str, Dict[str, Any]]:
        """Return default brain accuracy structure."""
        return {
            "technical": {"signals": 0, "correct": 0, "accuracy": 0.0},
            "sentiment": {"signals": 0, "correct": 0, "accuracy": 0.0},
            "pattern": {"signals": 0, "correct": 0, "accuracy": 0.0},
        }
    
    # ══════════════════════════════════════════════════════════════════════════
    # TIME ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    
    def get_time_analysis(self) -> Dict[str, Any]:
        """
        Analyze performance by time of day and day of week.
        
        Returns:
            Dict with:
            - best_hour: Most profitable hour
            - worst_hour: Least profitable hour
            - hourly_pnl: Dict of hour -> pnl
            - best_day: Most profitable weekday
            - worst_day: Least profitable weekday
            - daily_pnl: Dict of weekday -> pnl
        """
        try:
            all_trades = self._trade_repo.get_trade_history(limit=10000)
            trades = [t for t in all_trades if getattr(t, 'status', '') == 'CLOSED']
            
            if not trades:
                return self._empty_time_analysis()
            
            # Hourly analysis
            hourly_pnl = defaultdict(float)
            hourly_count = defaultdict(int)
            
            # Daily analysis (weekday)
            daily_pnl = defaultdict(float)
            daily_count = defaultdict(int)
            
            weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            
            for trade in trades:
                entry_time = getattr(trade, 'entry_time', None)
                pnl = float(getattr(trade, 'pnl', 0) or 0)
                
                if not entry_time:
                    continue
                
                hour = entry_time.hour
                weekday = entry_time.weekday()
                
                hourly_pnl[hour] += pnl
                hourly_count[hour] += 1
                
                daily_pnl[weekday] += pnl
                daily_count[weekday] += 1
            
            # Find best/worst
            best_hour = max(hourly_pnl, key=hourly_pnl.get) if hourly_pnl else 10
            worst_hour = min(hourly_pnl, key=hourly_pnl.get) if hourly_pnl else 15
            
            best_weekday = max(daily_pnl, key=daily_pnl.get) if daily_pnl else 0
            worst_weekday = min(daily_pnl, key=daily_pnl.get) if daily_pnl else 4
            
            # Format hourly data
            hourly_data = {}
            for hour in range(9, 16):  # Market hours 9 AM to 3 PM
                hourly_data[f"{hour:02d}:00"] = {
                    "pnl": hourly_pnl.get(hour, 0),
                    "trades": hourly_count.get(hour, 0),
                }
            
            # Format daily data
            weekday_data = {}
            for i, name in enumerate(weekday_names[:5]):  # Mon-Fri
                weekday_data[name] = {
                    "pnl": daily_pnl.get(i, 0),
                    "trades": daily_count.get(i, 0),
                }
            
            return {
                "best_hour": f"{best_hour:02d}:00",
                "best_hour_pnl": hourly_pnl.get(best_hour, 0),
                "worst_hour": f"{worst_hour:02d}:00",
                "worst_hour_pnl": hourly_pnl.get(worst_hour, 0),
                "hourly_breakdown": hourly_data,
                "best_day": weekday_names[best_weekday],
                "best_day_pnl": daily_pnl.get(best_weekday, 0),
                "worst_day": weekday_names[worst_weekday],
                "worst_day_pnl": daily_pnl.get(worst_weekday, 0),
                "daily_breakdown": weekday_data,
            }
            
        except Exception as e:
            logger.error(f"Error in time analysis: {e}")
            return self._empty_time_analysis()
    
    def _empty_time_analysis(self) -> Dict[str, Any]:
        """Return empty time analysis."""
        return {
            "best_hour": "10:00",
            "best_hour_pnl": 0,
            "worst_hour": "15:00",
            "worst_hour_pnl": 0,
            "hourly_breakdown": {},
            "best_day": "Monday",
            "best_day_pnl": 0,
            "worst_day": "Friday",
            "worst_day_pnl": 0,
            "daily_breakdown": {},
        }
    
    # ══════════════════════════════════════════════════════════════════════════
    # RISK METRICS
    # ══════════════════════════════════════════════════════════════════════════
    
    def get_risk_metrics(self) -> Dict[str, Any]:
        """
        Calculate risk-adjusted performance metrics.
        
        Returns:
            Dict with:
            - max_drawdown, max_drawdown_pct
            - sharpe_ratio, sortino_ratio
            - calmar_ratio
            - var_95 (Value at Risk at 95%)
            - avg_risk_per_trade
        """
        try:
            all_trades = self._trade_repo.get_trade_history(limit=10000)
            trades = [t for t in all_trades if getattr(t, 'status', '') == 'CLOSED']
            
            if not trades:
                return self._empty_risk_metrics()
            
            # Get P&L series
            pnls = [float(getattr(t, 'pnl', 0) or 0) for t in trades]
            
            # Get daily returns
            daily_pnl = self._calculate_daily_pnl(trades)
            daily_returns = list(daily_pnl.values()) if daily_pnl else []
            
            # Initial capital (assume from settings or estimate)
            initial_capital = 100000  # Default
            try:
                from config.settings import settings
                initial_capital = float(getattr(settings, 'INITIAL_CAPITAL', 100000))
            except:
                pass
            
            # Convert to returns
            daily_return_pcts = [r / initial_capital for r in daily_returns] if daily_returns else []
            
            # Max drawdown
            max_dd, max_dd_pct = self._calculate_max_drawdown_from_pnls(pnls, initial_capital)
            
            # Sharpe ratio
            sharpe = self._calculate_sharpe(daily_return_pcts)
            
            # Sortino ratio (only considers downside volatility)
            sortino = self._calculate_sortino(daily_return_pcts)
            
            # Calmar ratio (return / max drawdown)
            total_return = sum(pnls) / initial_capital if initial_capital else 0
            calmar = safe_divide(total_return, max_dd_pct / 100) if max_dd_pct else 0
            
            # VaR 95%
            var_95 = self._calculate_var(pnls, 0.95)
            
            # Average risk per trade
            losses_only = [p for p in pnls if p < 0]
            avg_risk = abs(sum(losses_only) / len(losses_only)) if losses_only else 0
            
            return {
                "max_drawdown": max_dd,
                "max_drawdown_pct": max_dd_pct,
                "sharpe_ratio": sharpe,
                "sortino_ratio": sortino,
                "calmar_ratio": calmar,
                "var_95": var_95,
                "avg_risk_per_trade": avg_risk,
            }
            
        except Exception as e:
            logger.error(f"Error calculating risk metrics: {e}")
            return self._empty_risk_metrics()
    
    def _empty_risk_metrics(self) -> Dict[str, Any]:
        """Return empty risk metrics."""
        return {
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "calmar_ratio": 0.0,
            "var_95": 0.0,
            "avg_risk_per_trade": 0.0,
        }
    
    def _calculate_sharpe(self, returns: List[float]) -> float:
        """Calculate Sharpe ratio."""
        if not returns or len(returns) < 2:
            return 0.0
        
        if NUMPY_AVAILABLE:
            arr = np.array(returns)
            mean_ret = np.mean(arr)
            std_ret = np.std(arr, ddof=1)
            if std_ret == 0:
                return 0.0
            return float(mean_ret / std_ret * np.sqrt(252))
        else:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
            std_ret = math.sqrt(variance) if variance > 0 else 0
            if std_ret == 0:
                return 0.0
            return mean_ret / std_ret * math.sqrt(252)
    
    def _calculate_sortino(self, returns: List[float]) -> float:
        """Calculate Sortino ratio (only downside deviation)."""
        if not returns or len(returns) < 2:
            return 0.0
        
        mean_ret = sum(returns) / len(returns)
        
        # Downside returns only
        downside = [r for r in returns if r < 0]
        if not downside:
            return float('inf') if mean_ret > 0 else 0.0
        
        downside_variance = sum(r ** 2 for r in downside) / len(downside)
        downside_std = math.sqrt(downside_variance) if downside_variance > 0 else 0
        
        if downside_std == 0:
            return 0.0
        
        return mean_ret / downside_std * math.sqrt(252)
    
    def _calculate_var(self, pnls: List[float], confidence: float = 0.95) -> float:
        """Calculate Value at Risk."""
        if not pnls:
            return 0.0
        
        sorted_pnls = sorted(pnls)
        index = int((1 - confidence) * len(sorted_pnls))
        return abs(sorted_pnls[index]) if index < len(sorted_pnls) else 0.0
    
    def _calculate_max_drawdown_from_pnls(
        self,
        pnls: List[float],
        initial_capital: float
    ) -> Tuple[float, float]:
        """Calculate max drawdown from P&L series."""
        if not pnls:
            return 0.0, 0.0
        
        # Build equity curve
        equity = initial_capital
        peak = equity
        max_dd = 0
        max_dd_pct = 0
        
        for pnl in pnls:
            equity += pnl
            if equity > peak:
                peak = equity
            
            dd = peak - equity
            dd_pct = (dd / peak * 100) if peak > 0 else 0
            
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct
        
        return max_dd, max_dd_pct
    
    # ══════════════════════════════════════════════════════════════════════════
    # FORMATTED REPORTS
    # ══════════════════════════════════════════════════════════════════════════
    
    def format_report(self, period: str = 'daily') -> str:
        """
        Format statistics as a report string for Telegram.
        
        Args:
            period: 'daily', 'weekly', or 'monthly'
            
        Returns:
            Formatted report string with emojis
        """
        try:
            if period == 'daily':
                return self._format_daily_report()
            elif period == 'weekly':
                return self._format_weekly_report()
            elif period == 'monthly':
                return self._format_monthly_report()
            else:
                return self._format_daily_report()
        except Exception as e:
            logger.error(f"Error formatting report: {e}")
            return f"❌ Error generating report: {str(e)[:100]}"
    
    def _format_daily_report(self) -> str:
        """Format daily report."""
        today = date.today()
        daily_stats = self.get_daily_stats(days=1)
        
        if not daily_stats:
            return f"📊 DAILY REPORT - {today.strftime('%d %b %Y')}\n\nNo trades today."
        
        day_data = daily_stats[0]
        pnl = day_data['pnl']
        trades = day_data['trades']
        wins = day_data['wins']
        losses = day_data['losses']
        win_rate = day_data['win_rate']
        
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        
        # Get brain accuracy for today
        brain_acc = self.get_brain_accuracy()
        
        # Get best/worst trade today
        trades_today = self._trade_repo.get_trades_today() or []
        closed_today = [t for t in trades_today if getattr(t, 'status', '') == 'CLOSED']
        
        best_trade = max(closed_today, key=lambda t: getattr(t, 'pnl', 0) or 0) if closed_today else None
        worst_trade = min(closed_today, key=lambda t: getattr(t, 'pnl', 0) or 0) if closed_today else None
        
        report = f"📊 <b>DAILY REPORT</b> - {today.strftime('%d %b %Y')}\n\n"
        
        report += f"<b>P&L:</b> {pnl_emoji} {format_pnl(pnl)}\n"
        report += f"<b>Trades:</b> {trades} ({wins}W / {losses}L)\n"
        report += f"<b>Win Rate:</b> {win_rate:.1f}%\n\n"
        
        if best_trade:
            best_pnl = float(getattr(best_trade, 'pnl', 0) or 0)
            best_instr = getattr(best_trade, 'instrument', 'N/A')
            report += f"<b>Best:</b> {best_instr}\n"
            report += f"        {format_pnl(best_pnl)}\n"
        
        if worst_trade:
            worst_pnl = float(getattr(worst_trade, 'pnl', 0) or 0)
            worst_instr = getattr(worst_trade, 'instrument', 'N/A')
            report += f"<b>Worst:</b> {worst_instr}\n"
            report += f"         {format_pnl(worst_pnl)}\n"
        
        report += "\n<b>Brain Accuracy:</b>\n"
        for brain, stats in brain_acc.items():
            if stats['signals'] > 0:
                report += f"├─ {brain.title()}: {stats['correct']}/{stats['signals']} ({stats['accuracy']:.0f}%)\n"
        
        return report
    
    def _format_weekly_report(self) -> str:
        """Format weekly report."""
        weekly_stats = self.get_weekly_stats(weeks=2)
        
        if not weekly_stats:
            return "📊 WEEKLY REPORT\n\nNo data available."
        
        current_week = weekly_stats[0] if weekly_stats else None
        last_week = weekly_stats[1] if len(weekly_stats) > 1 else None
        
        report = f"📊 <b>WEEKLY REPORT</b>\n\n"
        
        if current_week:
            pnl = current_week['pnl']
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            
            report += f"<b>This Week</b> ({current_week['week_start']} to {current_week['week_end']})\n"
            report += f"├─ P&L: {pnl_emoji} {format_pnl(pnl)}\n"
            report += f"├─ Trades: {current_week['trades']} ({current_week['wins']}W / {current_week['losses']}L)\n"
            report += f"└─ Win Rate: {current_week['win_rate']:.1f}%\n\n"
        
        if last_week:
            pnl = last_week['pnl']
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            
            report += f"<b>Last Week</b> ({last_week['week_start']} to {last_week['week_end']})\n"
            report += f"├─ P&L: {pnl_emoji} {format_pnl(pnl)}\n"
            report += f"├─ Trades: {last_week['trades']} ({last_week['wins']}W / {last_week['losses']}L)\n"
            report += f"└─ Win Rate: {last_week['win_rate']:.1f}%\n\n"
        
        # Compare weeks
        if current_week and last_week:
            pnl_change = current_week['pnl'] - last_week['pnl']
            trend = "📈" if pnl_change >= 0 else "📉"
            report += f"<b>Trend:</b> {trend} {format_pnl(pnl_change)} vs last week"
        
        return report
    
    def _format_monthly_report(self) -> str:
        """Format monthly report."""
        monthly_stats = self.get_monthly_stats(months=2)
        overall = self.get_overall_stats()
        risk = self.get_risk_metrics()
        
        report = f"📊 <b>MONTHLY REPORT</b>\n\n"
        
        if monthly_stats:
            current_month = monthly_stats[0]
            pnl = current_month['pnl']
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            
            report += f"<b>{current_month['month']}</b>\n"
            report += f"├─ P&L: {pnl_emoji} {format_pnl(pnl)}\n"
            report += f"├─ Trades: {current_month['trades']}\n"
            report += f"└─ Win Rate: {current_month['win_rate']:.1f}%\n\n"
        
        report += f"<b>Overall Performance</b>\n"
        report += f"├─ Total Trades: {overall['total_trades']}\n"
        report += f"├─ Win Rate: {overall['win_rate']:.1f}%\n"
        report += f"├─ Profit Factor: {overall['profit_factor']:.2f}\n"
        report += f"└─ Total P&L: {format_pnl(overall['total_pnl'])}\n\n"
        
        report += f"<b>Risk Metrics</b>\n"
        report += f"├─ Max Drawdown: {format_currency(risk['max_drawdown'])} ({risk['max_drawdown_pct']:.1f}%)\n"
        report += f"├─ Sharpe Ratio: {risk['sharpe_ratio']:.2f}\n"
        report += f"└─ VaR (95%): {format_currency(risk['var_95'])}"
        
        return report
    
    # ══════════════════════════════════════════════════════════════════════════
    # HELPER METHODS
    # ══════════════════════════════════════════════════════════════════════════
    
    def _calculate_daily_pnl(self, trades: List) -> Dict[date, float]:
        """Calculate P&L grouped by day."""
        daily_pnl = defaultdict(float)
        
        for trade in trades:
            entry_time = getattr(trade, 'entry_time', None)
            pnl = float(getattr(trade, 'pnl', 0) or 0)
            
            if entry_time:
                trade_date = entry_time.date()
                daily_pnl[trade_date] += pnl
        
        return dict(daily_pnl)
    
    def _calculate_current_streak(self, trades: List) -> Tuple[int, str]:
        """
        Calculate current win/loss streak.
        
        Returns:
            Tuple of (streak_count, streak_type)
        """
        if not trades:
            return 0, "none"
        
        # Sort by exit time (most recent first)
        sorted_trades = sorted(
            trades,
            key=lambda t: getattr(t, 'exit_time', datetime.min) or datetime.min,
            reverse=True
        )
        
        streak = 0
        streak_type = None
        
        for trade in sorted_trades:
            pnl = float(getattr(trade, 'pnl', 0) or 0)
            is_win = pnl > 0
            
            if streak_type is None:
                streak_type = "wins" if is_win else "losses"
                streak = 1
            elif (streak_type == "wins" and is_win) or (streak_type == "losses" and not is_win):
                streak += 1
            else:
                break
        
        return streak, streak_type or "none"
    
    def _calculate_longest_streak(self, trades: List, winning: bool = True) -> int:
        """Calculate longest winning or losing streak."""
        if not trades:
            return 0
        
        # Sort by exit time
        sorted_trades = sorted(
            trades,
            key=lambda t: getattr(t, 'exit_time', datetime.min) or datetime.min
        )
        
        longest = 0
        current = 0
        
        for trade in sorted_trades:
            pnl = float(getattr(trade, 'pnl', 0) or 0)
            is_win = pnl > 0
            
            if (winning and is_win) or (not winning and not is_win):
                current += 1
                longest = max(longest, current)
            else:
                current = 0
        
        return longest


# ══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  PERFORMANCE ANALYZER - TEST")
    print("=" * 60)
    
    print("\n  This module requires database access to analyze trades.")
    print("  Run with actual trade data for meaningful results.")
    
    # Try to create analyzer with actual repos
    try:
        from database import get_trade_repo, get_snapshot_repo, get_signal_repo
        
        trade_repo = get_trade_repo()
        snapshot_repo = get_snapshot_repo()
        signal_repo = get_signal_repo()
        
        analyzer = PerformanceAnalyzer(
            trade_repo,
            snapshot_repo,
            signal_repo
        )
        
        print("\n  ✅ Analyzer initialized successfully")
        
        # Get overall stats
        print("\n  Fetching overall statistics...")
        stats = analyzer.get_overall_stats()
        
        print(f"\n  Total Trades: {stats['total_trades']}")
        print(f"  Win Rate: {stats['win_rate']:.1f}%")
        print(f"  Total P&L: {format_pnl(stats['total_pnl'])}")
        print(f"  Profit Factor: {stats['profit_factor']:.2f}")
        
        # Get daily report
        print("\n  Generating daily report...")
        report = analyzer.format_report('daily')
        print("\n" + report)
        
    except ImportError as e:
        print(f"\n  ⚠️ Could not import database modules: {e}")
        print("  Run this from the project root directory.")
    except Exception as e:
        print(f"\n  ❌ Error: {e}")
    
    print("\n" + "=" * 60)
    print("  Performance Analyzer test complete!")
    print("=" * 60 + "\n")