"""
Database Repository Module
==========================

CRUD operations for all database models.
This is the DATA ACCESS LAYER - all database reads/writes go through here.

Architecture:
    DatabaseManager   → Engine, Session, Table management
    TradeRepository   → Trade CRUD + PnL calculations + statistics
    PositionRepository → Position tracking + live PnL updates
    SignalRepository  → Signal storage + execution tracking
    SnapshotRepository → Daily equity curve data

Design Principles:
    1. Every write operation is wrapped in a transaction
    2. Every read returns clean objects (no lazy loading surprises)
    3. Errors are caught and logged, never silently swallowed
    4. PnL is calculated at close time, never estimated
    5. Statistics are computed from actual data, not cached

Usage:
    from database.repository import DatabaseManager, TradeRepository
    
    db = DatabaseManager("sqlite:///trading_bot.db")
    db.create_tables()
    
    trade_repo = TradeRepository(db)
    
    # Save a trade
    trade = trade_repo.save_trade({
        'symbol': 'NIFTY',
        'strike': 24500,
        'option_type': 'CE',
        'side': 'BUY',
        'entry_price': 125.50,
        'quantity': 25,
        'lots': 1,
        'stop_loss': 87.85,
        'take_profit': 188.25,
    })
    
    # Close with profit
    trade_repo.close_trade(trade.trade_id, exit_price=180.0, exit_reason='TP')
    
    # Get stats
    stats = trade_repo.get_stats()
    print(f"Win Rate: {stats['win_rate']}%")
"""

import os
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any

from sqlalchemy import create_engine, func, and_, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

# Import our models
from database.models import (
    Base,
    Trade,
    Position,
    Signal,
    DailySnapshot,
    TradeStatus,
    TradeSide,
    ExitReason,
    TradingMode,
)

# Setup logging
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════

def _get_ist_now():
    """Get current IST time."""
    try:
        from utils.helpers import get_ist_now
        return get_ist_now()
    except ImportError:
        return datetime.utcnow() + timedelta(hours=5, minutes=30)


def _get_ist_today():
    """Get today's date in IST."""
    return _get_ist_now().date()


def _generate_trade_id():
    """Generate unique trade ID."""
    try:
        from utils.helpers import generate_trade_id
        return generate_trade_id()
    except ImportError:
        import random
        now = _get_ist_now()
        rand = random.randint(100, 999)
        return f"TRD-{now.strftime('%Y%m%d')}-{rand}"


def _generate_signal_id():
    """Generate unique signal ID."""
    try:
        from utils.helpers import generate_order_id
        return generate_order_id().replace("ORD", "SIG")
    except ImportError:
        import random
        now = _get_ist_now()
        rand = random.randint(100, 999)
        return f"SIG-{now.strftime('%Y%m%d')}-{rand}"


# ══════════════════════════════════════════════════════════
# DATABASE MANAGER
# ══════════════════════════════════════════════════════════

class DatabaseManager:
    """
    Manages database engine and sessions.
    
    Responsibilities:
        - Create and manage the SQLAlchemy engine
        - Create and manage session factory
        - Create all tables on first run
        - Provide session context manager
    
    Usage:
        db = DatabaseManager("sqlite:///trading_bot.db")
        db.create_tables()
        
        with db.get_session() as session:
            trades = session.query(Trade).all()
    """
    
    def __init__(self, database_url: str = None):
        """
        Initialize database manager.
        
        Args:
            database_url: SQLAlchemy database URL
                          Default: sqlite:///trading_bot.db
        """
        if database_url is None:
            try:
                from config.settings import settings
                database_url = settings.DATABASE_URL
            except Exception:
                database_url = "sqlite:///trading_bot.db"
        
        self.database_url = database_url
        
        # Create engine
        # For SQLite: check_same_thread=False allows multi-thread access
        engine_kwargs = {
            'echo': False,  # Set True for SQL debugging
        }
        
        if 'sqlite' in database_url:
            engine_kwargs['connect_args'] = {'check_same_thread': False}
        
        self._engine = create_engine(database_url, **engine_kwargs)
        
        # Create session factory
        self._SessionFactory = sessionmaker(
            bind=self._engine,
            expire_on_commit=False,  # Don't expire objects after commit
        )
        
        logger.info(f"DatabaseManager initialized: {database_url}")
    
    def create_tables(self):
        """
        Create all tables if they don't exist.
        Safe to call multiple times (idempotent).
        """
        try:
            Base.metadata.create_all(self._engine)
            
            # Verify tables were created
            inspector = inspect(self._engine)
            tables = inspector.get_table_names()
            logger.info(f"Database tables ready: {', '.join(tables)}")
            
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            raise
    
    def get_session(self) -> Session:
        """
        Get a new database session.
        
        Returns:
            SQLAlchemy Session
            
        Usage:
            session = db.get_session()
            try:
                # do work
                session.commit()
            except:
                session.rollback()
                raise
            finally:
                session.close()
        """
        return self._SessionFactory()
    
    def get_table_count(self) -> int:
        """Get number of tables in database."""
        try:
            inspector = inspect(self._engine)
            return len(inspector.get_table_names())
        except Exception:
            return 0
    
    def get_table_names(self) -> List[str]:
        """Get list of table names."""
        try:
            inspector = inspect(self._engine)
            return inspector.get_table_names()
        except Exception:
            return []
    
    def close(self):
        """Close the database engine."""
        if self._engine:
            self._engine.dispose()
            logger.info("Database connection closed")
    
    def __repr__(self):
        return f"<DatabaseManager({self.database_url})>"


# ══════════════════════════════════════════════════════════
# TRADE REPOSITORY
# ══════════════════════════════════════════════════════════

class TradeRepository:
    """
    CRUD operations for Trade records.
    
    This is where the REAL trading history lives.
    Every method here is designed for what a trader actually needs:
        - "Show me today's trades"
        - "What's my win rate?"
        - "Close this trade at profit"
        - "What's my total PnL this week?"
    """
    
    def __init__(self, db_manager: DatabaseManager):
        """Initialize with database manager."""
        self._db = db_manager
    
    def save_trade(self, trade_data: Dict) -> Trade:
        """
        Save a new trade to database.
        
        Args:
            trade_data: {
                'symbol': 'NIFTY',
                'strike': 24500,
                'option_type': 'CE',
                'expiry': '05MAR',
                'side': 'BUY',
                'entry_price': 125.50,
                'quantity': 25,
                'lots': 1,
                'stop_loss': 87.85,
                'take_profit': 188.25,
                'mode': 'PAPER',  (optional, default PAPER)
                'brain_signals': {},  (optional)
                'notes': '',  (optional)
            }
        
        Returns:
            Trade: The created trade object
        """
        session = self._db.get_session()
        
        try:
            # Generate trade ID if not provided
            trade_id = trade_data.get('trade_id', _generate_trade_id())
            
            # Build instrument name
            symbol = trade_data.get('symbol', 'NIFTY')
            strike = trade_data.get('strike', 0)
            opt_type = trade_data.get('option_type', 'CE')
            instrument = trade_data.get(
                'instrument', 
                f"{symbol} {int(strike)} {opt_type}"
            )
            
            # Determine mode
            mode = trade_data.get('mode', TradingMode.PAPER)
            if mode is None:
                try:
                    from config.settings import settings
                    mode = TradingMode.PAPER if settings.PAPER_TRADING else TradingMode.LIVE
                except Exception:
                    mode = TradingMode.PAPER
            
            # Create trade object
            trade = Trade(
                trade_id=trade_id,
                symbol=symbol,
                instrument=instrument,
                strike=float(strike),
                option_type=opt_type,
                expiry=trade_data.get('expiry', ''),
                side=trade_data.get('side', TradeSide.BUY),
                quantity=int(trade_data.get('quantity', 0)),
                lots=int(trade_data.get('lots', 1)),
                entry_price=float(trade_data.get('entry_price', 0)),
                stop_loss=float(trade_data.get('stop_loss', 0)),
                take_profit=float(trade_data.get('take_profit', 0)),
                status=TradeStatus.OPEN,
                mode=mode,
                notes=trade_data.get('notes', None),
                entry_time=trade_data.get('entry_time', _get_ist_now()),
            )
            
            # Set brain signals if provided
            brain_signals = trade_data.get('brain_signals')
            if brain_signals:
                trade.brain_signals_dict = brain_signals
            
            session.add(trade)
            session.commit()
            
            logger.info(
                f"Trade saved: {trade.trade_id} | "
                f"{trade.side} {trade.instrument} @ ₹{trade.entry_price:.2f} | "
                f"SL: ₹{trade.stop_loss:.2f} TP: ₹{trade.take_profit:.2f}"
            )
            
            return trade
            
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Database error saving trade: {e}")
            raise
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving trade: {e}")
            raise
        finally:
            session.close()
    
    def get_trade(self, trade_id: str) -> Optional[Trade]:
        """Get a trade by its trade_id."""
        session = self._db.get_session()
        try:
            trade = session.query(Trade).filter(
                Trade.trade_id == trade_id
            ).first()
            return trade
        except Exception as e:
            logger.error(f"Error getting trade {trade_id}: {e}")
            return None
        finally:
            session.close()
    
    def get_trade_by_id(self, id: int) -> Optional[Trade]:
        """Get a trade by its database ID."""
        session = self._db.get_session()
        try:
            return session.query(Trade).filter(Trade.id == id).first()
        except Exception as e:
            logger.error(f"Error getting trade by id {id}: {e}")
            return None
        finally:
            session.close()
    
    def get_open_trades(self) -> List[Trade]:
        """Get all currently open trades."""
        session = self._db.get_session()
        try:
            trades = session.query(Trade).filter(
                Trade.status == TradeStatus.OPEN
            ).order_by(Trade.entry_time.desc()).all()
            return trades
        except Exception as e:
            logger.error(f"Error getting open trades: {e}")
            return []
        finally:
            session.close()
    
    def get_trades_today(self) -> List[Trade]:
        """Get all trades entered today."""
        session = self._db.get_session()
        try:
            today = _get_ist_today()
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.combine(today, datetime.max.time())
            
            trades = session.query(Trade).filter(
                and_(
                    Trade.entry_time >= today_start,
                    Trade.entry_time <= today_end,
                )
            ).order_by(Trade.entry_time.desc()).all()
            
            return trades
        except Exception as e:
            logger.error(f"Error getting today's trades: {e}")
            return []
        finally:
            session.close()
    
    def get_trades_by_date(self, target_date: date) -> List[Trade]:
        """Get all trades for a specific date."""
        session = self._db.get_session()
        try:
            day_start = datetime.combine(target_date, datetime.min.time())
            day_end = datetime.combine(target_date, datetime.max.time())
            
            trades = session.query(Trade).filter(
                and_(
                    Trade.entry_time >= day_start,
                    Trade.entry_time <= day_end,
                )
            ).order_by(Trade.entry_time.desc()).all()
            
            return trades
        except Exception as e:
            logger.error(f"Error getting trades for {target_date}: {e}")
            return []
        finally:
            session.close()
    
    def close_trade(
        self, 
        trade_id: str, 
        exit_price: float, 
        exit_reason: str,
        exit_time: datetime = None,
    ) -> Optional[Trade]:
        """
        Close a trade and calculate PnL.
        
        This is the MOST IMPORTANT method. It:
            1. Finds the open trade
            2. Calculates exact PnL
            3. Records exit price, time, reason
            4. Updates status to CLOSED
        
        Args:
            trade_id: The trade to close
            exit_price: Exit premium per unit
            exit_reason: Why (SL, TP, MANUAL, etc.)
            exit_time: When (default: now)
            
        Returns:
            Trade: Updated trade with PnL calculated
        """
        session = self._db.get_session()
        
        try:
            trade = session.query(Trade).filter(
                Trade.trade_id == trade_id
            ).first()
            
            if not trade:
                logger.error(f"Trade not found: {trade_id}")
                return None
            
            if trade.status != TradeStatus.OPEN:
                logger.warning(f"Trade {trade_id} is already {trade.status}")
                return trade
            
            # Close the trade (this calculates PnL)
            trade.close(
                exit_price=exit_price,
                exit_reason=exit_reason,
                exit_time=exit_time,
            )
            
            session.commit()
            
            logger.info(
                f"Trade closed: {trade.trade_id} | "
                f"Exit @ ₹{exit_price:.2f} | "
                f"PnL: ₹{trade.pnl:+,.2f} ({trade.pnl_percentage:+.2f}%) | "
                f"Reason: {exit_reason} | "
                f"Duration: {trade.duration_str}"
            )
            
            return trade
            
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Database error closing trade {trade_id}: {e}")
            raise
        except Exception as e:
            session.rollback()
            logger.error(f"Error closing trade {trade_id}: {e}")
            raise
        finally:
            session.close()
    
    def cancel_trade(self, trade_id: str, reason: str = "Cancelled") -> Optional[Trade]:
        """Cancel an open trade."""
        session = self._db.get_session()
        
        try:
            trade = session.query(Trade).filter(
                Trade.trade_id == trade_id
            ).first()
            
            if not trade:
                logger.error(f"Trade not found: {trade_id}")
                return None
            
            trade.cancel(reason)
            session.commit()
            
            logger.info(f"Trade cancelled: {trade_id} - {reason}")
            return trade
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error cancelling trade {trade_id}: {e}")
            raise
        finally:
            session.close()
    
    def get_trade_history(self, days: int = 30) -> List[Trade]:
        """Get closed trades from last N days."""
        session = self._db.get_session()
        try:
            cutoff = _get_ist_now() - timedelta(days=days)
            
            trades = session.query(Trade).filter(
                and_(
                    Trade.status == TradeStatus.CLOSED,
                    Trade.entry_time >= cutoff,
                )
            ).order_by(Trade.exit_time.desc()).all()
            
            return trades
        except Exception as e:
            logger.error(f"Error getting trade history: {e}")
            return []
        finally:
            session.close()
    
    def get_total_pnl(self, days: Optional[int] = None) -> float:
        """
        Get total realized PnL.
        
        Args:
            days: Number of days to look back (None = all time)
        """
        session = self._db.get_session()
        try:
            query = session.query(func.sum(Trade.pnl)).filter(
                Trade.status == TradeStatus.CLOSED
            )
            
            if days is not None:
                cutoff = _get_ist_now() - timedelta(days=days)
                query = query.filter(Trade.exit_time >= cutoff)
            
            result = query.scalar()
            return round(result or 0.0, 2)
            
        except Exception as e:
            logger.error(f"Error getting total PnL: {e}")
            return 0.0
        finally:
            session.close()
    
    def get_total_trade_count(self) -> int:
        """Get total number of trades."""
        session = self._db.get_session()
        try:
            return session.query(func.count(Trade.id)).scalar() or 0
        except Exception as e:
            logger.error(f"Error getting trade count: {e}")
            return 0
        finally:
            session.close()
    
    def get_win_rate(self, days: Optional[int] = None) -> float:
        """
        Calculate win rate percentage.
        
        Args:
            days: Look back period (None = all time)
            
        Returns:
            float: Win rate as percentage (0-100)
        """
        session = self._db.get_session()
        try:
            query = session.query(Trade).filter(
                Trade.status == TradeStatus.CLOSED
            )
            
            if days is not None:
                cutoff = _get_ist_now() - timedelta(days=days)
                query = query.filter(Trade.exit_time >= cutoff)
            
            trades = query.all()
            
            if not trades:
                return 0.0
            
            winners = sum(1 for t in trades if (t.pnl or 0) > 0)
            return round((winners / len(trades)) * 100, 1)
            
        except Exception as e:
            logger.error(f"Error calculating win rate: {e}")
            return 0.0
        finally:
            session.close()
    
    def get_stats(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Get comprehensive trading statistics.
        
        This is what a profitable trader reviews daily.
        
        Args:
            days: Look back period (None = all time)
            
        Returns:
            dict: {
                'total_trades': 150,
                'open_trades': 2,
                'closed_trades': 148,
                'winning_trades': 92,
                'losing_trades': 56,
                'win_rate': 62.2,
                'total_pnl': 15250.00,
                'avg_pnl': 103.04,
                'avg_win': 285.50,
                'avg_loss': -195.25,
                'max_win': 1250.00,
                'max_loss': -875.00,
                'profit_factor': 2.35,
                'avg_duration': '2h 15m',
                'best_symbol': 'NIFTY',
                'most_traded': 'CE',
            }
        """
        session = self._db.get_session()
        
        try:
            # Base query for closed trades
            query = session.query(Trade).filter(
                Trade.status == TradeStatus.CLOSED
            )
            
            if days is not None:
                cutoff = _get_ist_now() - timedelta(days=days)
                query = query.filter(Trade.exit_time >= cutoff)
            
            closed_trades = query.all()
            open_trades = session.query(Trade).filter(
                Trade.status == TradeStatus.OPEN
            ).count()
            
            # Calculate stats
            total = len(closed_trades)
            
            if total == 0:
                return {
                    'total_trades': 0,
                    'open_trades': open_trades,
                    'closed_trades': 0,
                    'winning_trades': 0,
                    'losing_trades': 0,
                    'win_rate': 0.0,
                    'total_pnl': 0.0,
                    'avg_pnl': 0.0,
                    'avg_win': 0.0,
                    'avg_loss': 0.0,
                    'max_win': 0.0,
                    'max_loss': 0.0,
                    'profit_factor': 0.0,
                    'avg_duration': 'N/A',
                    'best_symbol': 'N/A',
                    'most_traded': 'N/A',
                }
            
            # Separate winners and losers
            winners = [t for t in closed_trades if (t.pnl or 0) > 0]
            losers = [t for t in closed_trades if (t.pnl or 0) < 0]
            
            total_pnl = sum(t.pnl or 0 for t in closed_trades)
            
            # Average PnL
            avg_pnl = total_pnl / total
            
            # Average win/loss
            avg_win = sum(t.pnl for t in winners) / len(winners) if winners else 0
            avg_loss = sum(t.pnl for t in losers) / len(losers) if losers else 0
            
            # Max win/loss
            pnls = [t.pnl or 0 for t in closed_trades]
            max_win = max(pnls) if pnls else 0
            max_loss = min(pnls) if pnls else 0
            
            # Profit factor (gross profit / gross loss)
            gross_profit = sum(t.pnl for t in winners) if winners else 0
            gross_loss = abs(sum(t.pnl for t in losers)) if losers else 0
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
            
            # Average duration
            durations = []
            for t in closed_trades:
                if t.entry_time and t.exit_time:
                    dur = (t.exit_time - t.entry_time).total_seconds()
                    durations.append(dur)
            
            if durations:
                avg_dur_seconds = sum(durations) / len(durations)
                hours = int(avg_dur_seconds // 3600)
                minutes = int((avg_dur_seconds % 3600) // 60)
                avg_duration = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
            else:
                avg_duration = "N/A"
            
            # Best symbol
            symbol_pnl = {}
            for t in closed_trades:
                symbol_pnl[t.symbol] = symbol_pnl.get(t.symbol, 0) + (t.pnl or 0)
            best_symbol = max(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else "N/A"
            
            # Most traded option type
            type_counts = {}
            for t in closed_trades:
                type_counts[t.option_type] = type_counts.get(t.option_type, 0) + 1
            most_traded = max(type_counts, key=type_counts.get) if type_counts else "N/A"
            
            return {
                'total_trades': total + open_trades,
                'open_trades': open_trades,
                'closed_trades': total,
                'winning_trades': len(winners),
                'losing_trades': len(losers),
                'win_rate': round((len(winners) / total) * 100, 1),
                'total_pnl': round(total_pnl, 2),
                'avg_pnl': round(avg_pnl, 2),
                'avg_win': round(avg_win, 2),
                'avg_loss': round(avg_loss, 2),
                'max_win': round(max_win, 2),
                'max_loss': round(max_loss, 2),
                'profit_factor': round(profit_factor, 2),
                'avg_duration': avg_duration,
                'best_symbol': best_symbol,
                'most_traded': most_traded,
            }
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {'total_trades': 0, 'win_rate': 0, 'total_pnl': 0}
        finally:
            session.close()


# ══════════════════════════════════════════════════════════
# POSITION REPOSITORY
# ══════════════════════════════════════════════════════════

class PositionRepository:
    """CRUD operations for Position records."""
    
    def __init__(self, db_manager: DatabaseManager):
        self._db = db_manager
    
    def save_position(self, position_data: Dict) -> Position:
        """Save a new position."""
        session = self._db.get_session()
        
        try:
            symbol = position_data.get('symbol', 'NIFTY')
            strike = position_data.get('strike', 0)
            opt_type = position_data.get('option_type', 'CE')
            
            position = Position(
                trade_id=position_data.get('trade_id'),
                symbol=symbol,
                instrument=position_data.get(
                    'instrument', 
                    f"{symbol} {int(strike)} {opt_type}"
                ),
                strike=float(strike),
                option_type=opt_type,
                expiry=position_data.get('expiry', ''),
                side=position_data.get('side', TradeSide.BUY),
                quantity=int(position_data.get('quantity', 0)),
                lots=int(position_data.get('lots', 1)),
                avg_price=float(position_data.get('avg_price', 0)),
                current_price=float(position_data.get('current_price', 0)),
                status=TradeStatus.OPEN,
            )
            
            session.add(position)
            session.commit()
            
            logger.info(f"Position saved: {position}")
            return position
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving position: {e}")
            raise
        finally:
            session.close()
    
    def get_position(self, position_id: int) -> Optional[Position]:
        """Get position by ID."""
        session = self._db.get_session()
        try:
            return session.query(Position).filter(Position.id == position_id).first()
        except Exception as e:
            logger.error(f"Error getting position: {e}")
            return None
        finally:
            session.close()
    
    def get_all_positions(self) -> List[Position]:
        """Get all positions."""
        session = self._db.get_session()
        try:
            return session.query(Position).order_by(Position.opened_at.desc()).all()
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []
        finally:
            session.close()
    
    def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        session = self._db.get_session()
        try:
            return session.query(Position).filter(
                Position.status == TradeStatus.OPEN
            ).order_by(Position.opened_at.desc()).all()
        except Exception as e:
            logger.error(f"Error getting open positions: {e}")
            return []
        finally:
            session.close()
    
    def update_position_price(
        self, 
        position_id: int, 
        current_price: float
    ) -> Optional[Position]:
        """Update position with current market price."""
        session = self._db.get_session()
        try:
            position = session.query(Position).filter(
                Position.id == position_id
            ).first()
            
            if position:
                position.update_price(current_price)
                session.commit()
            
            return position
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating position price: {e}")
            return None
        finally:
            session.close()
    
    def close_position(self, position_id: int) -> Optional[Position]:
        """Close a position."""
        session = self._db.get_session()
        try:
            position = session.query(Position).filter(
                Position.id == position_id
            ).first()
            
            if position:
                position.close_position()
                session.commit()
                logger.info(f"Position closed: {position}")
            
            return position
        except Exception as e:
            session.rollback()
            logger.error(f"Error closing position: {e}")
            return None
        finally:
            session.close()
    
    def get_total_unrealized_pnl(self) -> float:
        """Get total unrealized PnL from all open positions."""
        session = self._db.get_session()
        try:
            result = session.query(func.sum(Position.unrealized_pnl)).filter(
                Position.status == TradeStatus.OPEN
            ).scalar()
            return round(result or 0.0, 2)
        except Exception as e:
            logger.error(f"Error getting unrealized PnL: {e}")
            return 0.0
        finally:
            session.close()


# ══════════════════════════════════════════════════════════
# SIGNAL REPOSITORY
# ══════════════════════════════════════════════════════════

class SignalRepository:
    """CRUD operations for Signal records."""
    
    def __init__(self, db_manager: DatabaseManager):
        self._db = db_manager
    
    def save_signal(self, signal_data: Dict) -> Signal:
        """Save a new signal."""
        session = self._db.get_session()
        
        try:
            signal_id = signal_data.get('signal_id', _generate_signal_id())
            
            signal = Signal(
                signal_id=signal_id,
                symbol=signal_data.get('symbol', ''),
                instrument=signal_data.get('instrument'),
                action=signal_data.get('action', 'HOLD'),
                confidence=float(signal_data.get('confidence', 0)),
                brain_name=signal_data.get('brain_name', 'unknown'),
                reasoning=signal_data.get('reasoning', ''),
                executed=signal_data.get('executed', False),
                timestamp=signal_data.get('timestamp', _get_ist_now()),
            )
            
            # Set indicators
            indicators = signal_data.get('indicators')
            if indicators:
                signal.indicators_dict = indicators
            
            session.add(signal)
            session.commit()
            
            logger.info(f"Signal saved: {signal}")
            return signal
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving signal: {e}")
            raise
        finally:
            session.close()
    
    def get_signals_today(self) -> List[Signal]:
        """Get all signals generated today."""
        session = self._db.get_session()
        try:
            today = _get_ist_today()
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.combine(today, datetime.max.time())
            
            return session.query(Signal).filter(
                and_(
                    Signal.timestamp >= today_start,
                    Signal.timestamp <= today_end,
                )
            ).order_by(Signal.timestamp.desc()).all()
        except Exception as e:
            logger.error(f"Error getting today's signals: {e}")
            return []
        finally:
            session.close()
    
    def get_signals_by_symbol(self, symbol: str) -> List[Signal]:
        """Get all signals for a symbol."""
        session = self._db.get_session()
        try:
            return session.query(Signal).filter(
                Signal.symbol == symbol.upper()
            ).order_by(Signal.timestamp.desc()).all()
        except Exception as e:
            logger.error(f"Error getting signals for {symbol}: {e}")
            return []
        finally:
            session.close()
    
    def mark_executed(self, signal_id: str, trade_id: str) -> Optional[Signal]:
        """Mark a signal as executed and link to trade."""
        session = self._db.get_session()
        try:
            signal = session.query(Signal).filter(
                Signal.signal_id == signal_id
            ).first()
            
            if signal:
                signal.mark_executed(trade_id)
                session.commit()
                logger.info(f"Signal {signal_id} marked executed → {trade_id}")
            
            return signal
        except Exception as e:
            session.rollback()
            logger.error(f"Error marking signal executed: {e}")
            return None
        finally:
            session.close()
    
    def get_unexecuted_signals(self) -> List[Signal]:
        """Get signals that haven't been acted on."""
        session = self._db.get_session()
        try:
            return session.query(Signal).filter(
                Signal.executed == False
            ).order_by(Signal.timestamp.desc()).all()
        except Exception as e:
            logger.error(f"Error getting unexecuted signals: {e}")
            return []
        finally:
            session.close()
    
    def get_total_signal_count(self) -> int:
        """Get total number of signals."""
        session = self._db.get_session()
        try:
            return session.query(func.count(Signal.id)).scalar() or 0
        except Exception as e:
            return 0
        finally:
            session.close()


# ══════════════════════════════════════════════════════════
# SNAPSHOT REPOSITORY
# ══════════════════════════════════════════════════════════

class SnapshotRepository:
    """CRUD operations for DailySnapshot records."""
    
    def __init__(self, db_manager: DatabaseManager):
        self._db = db_manager
    
    def save_daily_snapshot(self, snapshot_data: Dict) -> DailySnapshot:
        """
        Save or update daily snapshot.
        If a snapshot for the date already exists, it updates it.
        """
        session = self._db.get_session()
        
        try:
            snapshot_date = snapshot_data.get('date', _get_ist_today())
            
            # Check if snapshot exists for this date
            existing = session.query(DailySnapshot).filter(
                DailySnapshot.date == snapshot_date
            ).first()
            
            if existing:
                # Update existing snapshot
                existing.ending_capital = snapshot_data.get('ending_capital', existing.ending_capital)
                existing.total_pnl = snapshot_data.get('total_pnl', existing.total_pnl)
                existing.realized_pnl = snapshot_data.get('realized_pnl', existing.realized_pnl)
                existing.unrealized_pnl = snapshot_data.get('unrealized_pnl', existing.unrealized_pnl)
                existing.total_trades = snapshot_data.get('total_trades', existing.total_trades)
                existing.winning_trades = snapshot_data.get('winning_trades', existing.winning_trades)
                existing.losing_trades = snapshot_data.get('losing_trades', existing.losing_trades)
                existing.win_rate = snapshot_data.get('win_rate', existing.win_rate)
                existing.max_drawdown = snapshot_data.get('max_drawdown', existing.max_drawdown)
                existing.max_profit = snapshot_data.get('max_profit', existing.max_profit)
                existing.max_loss = snapshot_data.get('max_loss', existing.max_loss)
                existing.notes = snapshot_data.get('notes', existing.notes)
                existing.updated_at = _get_ist_now()
                
                session.commit()
                logger.info(f"Snapshot updated: {existing}")
                return existing
            else:
                # Create new snapshot
                snapshot = DailySnapshot(
                    date=snapshot_date,
                    starting_capital=snapshot_data.get('starting_capital', 0),
                    ending_capital=snapshot_data.get('ending_capital', 0),
                    total_pnl=snapshot_data.get('total_pnl', 0),
                    realized_pnl=snapshot_data.get('realized_pnl', 0),
                    unrealized_pnl=snapshot_data.get('unrealized_pnl', 0),
                    total_trades=snapshot_data.get('total_trades', 0),
                    winning_trades=snapshot_data.get('winning_trades', 0),
                    losing_trades=snapshot_data.get('losing_trades', 0),
                    win_rate=snapshot_data.get('win_rate', 0),
                    max_drawdown=snapshot_data.get('max_drawdown', 0),
                    max_profit=snapshot_data.get('max_profit', 0),
                    max_loss=snapshot_data.get('max_loss', 0),
                    notes=snapshot_data.get('notes'),
                )
                
                session.add(snapshot)
                session.commit()
                
                logger.info(f"Snapshot saved: {snapshot}")
                return snapshot
                
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving snapshot: {e}")
            raise
        finally:
            session.close()
    
    def get_snapshot(self, target_date: date) -> Optional[DailySnapshot]:
        """Get snapshot for a specific date."""
        session = self._db.get_session()
        try:
            return session.query(DailySnapshot).filter(
                DailySnapshot.date == target_date
            ).first()
        except Exception as e:
            logger.error(f"Error getting snapshot for {target_date}: {e}")
            return None
        finally:
            session.close()
    
    def get_snapshots(self, days: int = 30) -> List[DailySnapshot]:
        """Get snapshots for last N days."""
        session = self._db.get_session()
        try:
            cutoff = _get_ist_today() - timedelta(days=days)
            return session.query(DailySnapshot).filter(
                DailySnapshot.date >= cutoff
            ).order_by(DailySnapshot.date.desc()).all()
        except Exception as e:
            logger.error(f"Error getting snapshots: {e}")
            return []
        finally:
            session.close()
    
    def get_latest_snapshot(self) -> Optional[DailySnapshot]:
        """Get the most recent snapshot."""
        session = self._db.get_session()
        try:
            return session.query(DailySnapshot).order_by(
                DailySnapshot.date.desc()
            ).first()
        except Exception as e:
            logger.error(f"Error getting latest snapshot: {e}")
            return None
        finally:
            session.close()
    
    def get_total_snapshot_count(self) -> int:
        """Get total number of snapshots."""
        session = self._db.get_session()
        try:
            return session.query(func.count(DailySnapshot.id)).scalar() or 0
        except Exception as e:
            return 0
        finally:
            session.close()
    
    def get_equity_curve(self, days: int = 30) -> List[Dict]:
        """
        Get equity curve data for charting.
        
        Returns list of {date, capital, pnl} sorted by date.
        """
        snapshots = self.get_snapshots(days)
        
        curve = []
        for s in sorted(snapshots, key=lambda x: x.date):
            curve.append({
                'date': s.date.isoformat(),
                'capital': s.ending_capital,
                'pnl': s.total_pnl,
                'trades': s.total_trades,
                'win_rate': s.win_rate,
            })
        
        return curve


# ══════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  DATABASE REPOSITORY - TEST")
    print("=" * 60)
    
    # Use in-memory database for testing
    print("\n  Creating in-memory test database...")
    db = DatabaseManager("sqlite:///:memory:")
    db.create_tables()
    print(f"  ✅ Tables created: {', '.join(db.get_table_names())}")
    
    # ── Test TradeRepository ──
    print("\n" + "-" * 60)
    print("  Testing TradeRepository...")
    
    trade_repo = TradeRepository(db)
    
    # Save trades
    print("\n  Saving sample trades...")
    
    trade1 = trade_repo.save_trade({
        'symbol': 'NIFTY',
        'strike': 24500,
        'option_type': 'CE',
        'expiry': '05MAR',
        'side': 'BUY',
        'entry_price': 125.50,
        'quantity': 25,
        'lots': 1,
        'stop_loss': 87.85,
        'take_profit': 188.25,
        'mode': 'PAPER',
    })
    print(f"  ✅ Trade 1: {trade1}")
    
    trade2 = trade_repo.save_trade({
        'symbol': 'BANKNIFTY',
        'strike': 48700,
        'option_type': 'PE',
        'expiry': '05MAR',
        'side': 'BUY',
        'entry_price': 200.00,
        'quantity': 15,
        'lots': 1,
        'stop_loss': 140.00,
        'take_profit': 300.00,
        'mode': 'PAPER',
    })
    print(f"  ✅ Trade 2: {trade2}")
    
    trade3 = trade_repo.save_trade({
        'symbol': 'NIFTY',
        'strike': 24400,
        'option_type': 'PE',
        'expiry': '05MAR',
        'side': 'BUY',
        'entry_price': 95.00,
        'quantity': 25,
        'lots': 1,
        'stop_loss': 66.50,
        'take_profit': 142.50,
        'mode': 'PAPER',
    })
    print(f"  ✅ Trade 3: {trade3}")
    
    # Get open trades
    open_trades = trade_repo.get_open_trades()
    print(f"\n  Open trades: {len(open_trades)}")
    
    # Close trades with different outcomes
    print("\n  Closing trades...")
    
    # Trade 1: Take profit hit (winner)
    closed1 = trade_repo.close_trade(
        trade1.trade_id, 
        exit_price=185.00, 
        exit_reason=ExitReason.TAKE_PROFIT
    )
    print(f"  ✅ Trade 1 closed: PnL = ₹{closed1.pnl:+,.2f} ({closed1.pnl_percentage:+.2f}%)")
    
    # Trade 2: Stop loss hit (loser)
    closed2 = trade_repo.close_trade(
        trade2.trade_id, 
        exit_price=145.00, 
        exit_reason=ExitReason.STOP_LOSS
    )
    print(f"  ✅ Trade 2 closed: PnL = ₹{closed2.pnl:+,.2f} ({closed2.pnl_percentage:+.2f}%)")
    
    # Trade 3: Manual close (winner)
    closed3 = trade_repo.close_trade(
        trade3.trade_id, 
        exit_price=130.00, 
        exit_reason=ExitReason.MANUAL
    )
    print(f"  ✅ Trade 3 closed: PnL = ₹{closed3.pnl:+,.2f} ({closed3.pnl_percentage:+.2f}%)")
    
    # Get stats
    print("\n  Trading Statistics:")
    stats = trade_repo.get_stats()
    print(f"    Total Trades:     {stats['total_trades']}")
    print(f"    Winners:          {stats['winning_trades']}")
    print(f"    Losers:           {stats['losing_trades']}")
    print(f"    Win Rate:         {stats['win_rate']}%")
    print(f"    Total PnL:        ₹{stats['total_pnl']:+,.2f}")
    print(f"    Avg Win:          ₹{stats['avg_win']:+,.2f}")
    print(f"    Avg Loss:         ₹{stats['avg_loss']:+,.2f}")
    print(f"    Max Win:          ₹{stats['max_win']:+,.2f}")
    print(f"    Max Loss:         ₹{stats['max_loss']:+,.2f}")
    print(f"    Profit Factor:    {stats['profit_factor']}")
    print(f"    Best Symbol:      {stats['best_symbol']}")
    
    # ── Test PositionRepository ──
    print("\n" + "-" * 60)
    print("  Testing PositionRepository...")
    
    pos_repo = PositionRepository(db)
    
    pos = pos_repo.save_position({
        'trade_id': 'TRD-TEST-001',
        'symbol': 'NIFTY',
        'strike': 24500,
        'option_type': 'CE',
        'expiry': '05MAR',
        'side': 'BUY',
        'quantity': 25,
        'lots': 1,
        'avg_price': 125.50,
        'current_price': 125.50,
    })
    print(f"  ✅ Position saved: {pos}")
    
    # Update price
    updated = pos_repo.update_position_price(pos.id, 150.00)
    print(f"  ✅ Price updated: PnL = ₹{updated.unrealized_pnl:+,.2f}")
    
    # Get open positions
    open_pos = pos_repo.get_open_positions()
    print(f"  ✅ Open positions: {len(open_pos)}")
    
    # ── Test SignalRepository ──
    print("\n" + "-" * 60)
    print("  Testing SignalRepository...")
    
    sig_repo = SignalRepository(db)
    
    sig = sig_repo.save_signal({
        'symbol': 'NIFTY',
        'action': 'BUY',
        'confidence': 0.85,
        'brain_name': 'technical',
        'reasoning': 'RSI oversold + MACD bullish crossover',
        'indicators': {'rsi': 28.5, 'macd': 'bullish'},
    })
    print(f"  ✅ Signal saved: {sig}")
    
    # Save another signal
    sig2 = sig_repo.save_signal({
        'symbol': 'NIFTY',
        'action': 'HOLD',
        'confidence': 0.45,
        'brain_name': 'sentiment',
        'reasoning': 'Neutral market sentiment',
    })
    print(f"  ✅ Signal saved: {sig2}")
    
    # Get today's signals
    today_sigs = sig_repo.get_signals_today()
    print(f"  ✅ Today's signals: {len(today_sigs)}")
    
    # Get unexecuted
    unexecuted = sig_repo.get_unexecuted_signals()
    print(f"  ✅ Unexecuted: {len(unexecuted)}")
    
    # ── Test SnapshotRepository ──
    print("\n" + "-" * 60)
    print("  Testing SnapshotRepository...")
    
    snap_repo = SnapshotRepository(db)
    
    snap = snap_repo.save_daily_snapshot({
        'date': _get_ist_today(),
        'starting_capital': 10000.00,
        'ending_capital': 10725.00,
        'total_pnl': 725.00,
        'realized_pnl': 725.00,
        'total_trades': 3,
        'winning_trades': 2,
        'losing_trades': 1,
        'win_rate': 66.7,
        'max_drawdown': 5.5,
        'max_profit': 1487.50,
        'max_loss': -825.00,
    })
    print(f"  ✅ Snapshot saved: {snap}")
    
    # Get latest
    latest = snap_repo.get_latest_snapshot()
    print(f"  ✅ Latest snapshot: {latest}")
    
    # Get equity curve
    curve = snap_repo.get_equity_curve(30)
    print(f"  ✅ Equity curve points: {len(curve)}")
    
    # ── Final Summary ──
    print("\n" + "=" * 60)
    print("  REPOSITORY TEST SUMMARY")
    print("-" * 60)
    print(f"  Tables:     {len(db.get_table_names())}")
    print(f"  Trades:     {trade_repo.get_total_trade_count()} ({stats['winning_trades']}W/{stats['losing_trades']}L)")
    print(f"  Positions:  {len(pos_repo.get_all_positions())}")
    print(f"  Signals:    {sig_repo.get_total_signal_count()}")
    print(f"  Snapshots:  {snap_repo.get_total_snapshot_count()}")
    print(f"  Total PnL:  ₹{trade_repo.get_total_pnl():+,.2f}")
    print(f"  Win Rate:   {trade_repo.get_win_rate()}%")
    print("=" * 60)
    print("  All Repository Tests Complete! ✅")
    print("=" * 60 + "\n")
    
    # Cleanup
    db.close()