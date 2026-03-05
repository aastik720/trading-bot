"""
Database Models
===============

SQLAlchemy ORM models for the trading bot.
These models are the PERMANENT RECORD of every trading decision.

A profitable trader tracks EVERYTHING:
    - Every trade entry and exit with exact timestamps
    - Every signal generated (even ones not acted on)
    - Daily equity snapshots for performance curves
    - Position state for real-time monitoring

Models:
    Trade         - Complete trade lifecycle (entry -> exit -> PnL)
    Position      - Currently open positions with unrealized PnL
    Signal        - All brain signals with confidence scores
    DailySnapshot - End-of-day equity curve data

PnL Calculation Logic:
    BUY trade:  PnL = (exit_price - entry_price) * quantity
    SELL trade: PnL = (entry_price - exit_price) * quantity
"""

import json
import logging
from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Date,
    Text,
    ForeignKey,
    Index,
)

# Handle SQLAlchemy version differences for Base class
# Try newest first, fall back to older versions
_relationship = None
_Base = None

try:
    from sqlalchemy.orm import DeclarativeBase, relationship
    _relationship = relationship

    class _Base(DeclarativeBase):
        pass

    Base = _Base

except ImportError:
    from sqlalchemy.orm import relationship as _relationship

    try:
        from sqlalchemy.orm import declarative_base
        Base = declarative_base()
    except ImportError:
        from sqlalchemy.ext.declarative import declarative_base
        Base = declarative_base()

# Make relationship available at module level
relationship = _relationship

# Setup logging
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# HELPER: Get IST timestamp
# ══════════════════════════════════════════════════════════

def _get_ist_now():
    """Get current IST timestamp as naive datetime (no timezone info)."""
    try:
        from utils.helpers import get_ist_now
        dt = get_ist_now()
        # Strip timezone info for SQLite compatibility
        if dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
    except ImportError:
        from datetime import datetime, timedelta
        return datetime.utcnow() + timedelta(hours=5, minutes=30)


# ══════════════════════════════════════════════════════════
# TRADE STATUS CONSTANTS
# ══════════════════════════════════════════════════════════

class TradeStatus:
    """Trade lifecycle states."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TradeSide:
    """Trade direction."""
    BUY = "BUY"
    SELL = "SELL"


class ExitReason:
    """Why the trade was closed."""
    STOP_LOSS = "SL"
    TAKE_PROFIT = "TP"
    TRAILING_SL = "TSL"
    MANUAL = "MANUAL"
    EXPIRY = "EXPIRY"
    EOD = "EOD"
    RISK = "RISK"
    SIGNAL = "SIGNAL"


class TradingMode:
    """Trading mode."""
    PAPER = "PAPER"
    LIVE = "LIVE"


# ══════════════════════════════════════════════════════════
# MODEL: TRADE
# ══════════════════════════════════════════════════════════

class Trade(Base):
    """
    Complete trade lifecycle record.

    This is the most important table. Every single trade
    (paper or live) is recorded here permanently.

    Lifecycle:
        1. Signal generated -> Trade created (status=OPEN)
        2. Market moves -> SL/TP monitored
        3. Exit triggered -> Trade closed (status=CLOSED, PnL calculated)

    PnL Calculation:
        BUY:  pnl = (exit_price - entry_price) * quantity
        SELL: pnl = (entry_price - exit_price) * quantity
    """

    __tablename__ = "trades"

    # Primary Key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Trade Identification
    trade_id = Column(String(50), unique=True, nullable=False, index=True)

    # Instrument Details
    symbol = Column(String(20), nullable=False, index=True)
    instrument = Column(String(50), nullable=False)
    strike = Column(Float, nullable=False)
    option_type = Column(String(2), nullable=False)
    expiry = Column(String(20), nullable=False)

    # Trade Details
    side = Column(String(4), nullable=False)
    quantity = Column(Integer, nullable=False)
    lots = Column(Integer, nullable=False, default=1)

    # Prices
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)

    # Status
    status = Column(String(10), nullable=False, default="OPEN", index=True)

    # PnL (calculated on close)
    pnl = Column(Float, default=0.0)
    pnl_percentage = Column(Float, default=0.0)

    # Timestamps
    entry_time = Column(DateTime, nullable=False, default=_get_ist_now)
    exit_time = Column(DateTime, nullable=True)
    exit_reason = Column(String(20), nullable=True)

    # Mode
    mode = Column(String(5), nullable=False, default="PAPER", index=True)

    # Brain/Signal Data (JSON string)
    brain_signals = Column(Text, nullable=True)

    # Notes
    notes = Column(Text, nullable=True)

    # Audit Timestamps
    created_at = Column(DateTime, default=_get_ist_now)
    updated_at = Column(DateTime, default=_get_ist_now, onupdate=_get_ist_now)

    # Relationships
    signals = relationship("Signal", back_populates="trade", lazy="select")

    # Indexes for fast queries
    __table_args__ = (
        Index('idx_trade_status_symbol', 'status', 'symbol'),
        Index('idx_trade_entry_time', 'entry_time'),
        Index('idx_trade_mode_status', 'mode', 'status'),
    )

    # ── Calculated Properties ──

    @property
    def duration(self) -> Optional[timedelta]:
        """How long the trade was held."""
        try:
            if self.exit_time and self.entry_time:
                # Make both naive for comparison
                exit_t = self.exit_time.replace(tzinfo=None) if self.exit_time.tzinfo else self.exit_time
                entry_t = self.entry_time.replace(tzinfo=None) if self.entry_time.tzinfo else self.entry_time
                return exit_t - entry_t
            elif self.entry_time:
                now = _get_ist_now()
                entry_t = self.entry_time.replace(tzinfo=None) if self.entry_time.tzinfo else self.entry_time
                return now - entry_t
        except Exception:
            pass
        return None

    @property
    def is_closed(self) -> bool:
        """Check if trade is closed."""
        return self.status == TradeStatus.CLOSED

    @property
    def is_profitable(self) -> bool:
        """Check if trade was profitable."""
        return (self.pnl or 0) > 0

    @property
    def entry_value(self) -> float:
        """Total value at entry (premium * quantity)."""
        return self.entry_price * self.quantity

    @property
    def exit_value(self) -> float:
        """Total value at exit (premium * quantity)."""
        if self.exit_price is None:
            return 0.0
        return self.exit_price * self.quantity

    @property
    def duration(self) -> Optional[timedelta]:
        """How long the trade was held."""
        if self.exit_time and self.entry_time:
            return self.exit_time - self.entry_time
        elif self.entry_time:
            return _get_ist_now() - self.entry_time
        return None

    @property
    def duration_str(self) -> str:
        """Human-readable duration."""
        dur = self.duration
        if dur is None:
            return "N/A"

        total_seconds = int(dur.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    @property
    def risk_reward_ratio(self) -> float:
        """Calculate risk-reward ratio."""
        if self.side == TradeSide.BUY:
            risk = self.entry_price - self.stop_loss
            reward = self.take_profit - self.entry_price
        else:
            risk = self.stop_loss - self.entry_price
            reward = self.entry_price - self.take_profit

        if risk <= 0:
            return 0.0
        return round(reward / risk, 2)

    @property
    def brain_signals_dict(self) -> Dict:
        """Parse brain_signals JSON string to dict."""
        if not self.brain_signals:
            return {}
        try:
            return json.loads(self.brain_signals)
        except (json.JSONDecodeError, TypeError):
            return {}

    @brain_signals_dict.setter
    def brain_signals_dict(self, value: Dict):
        """Set brain_signals from dict."""
        if value:
            self.brain_signals = json.dumps(value)
        else:
            self.brain_signals = None

    # ── Methods ──

    def calculate_pnl(self, exit_price: float) -> tuple:
        """
        Calculate PnL for a given exit price.

        Returns:
            tuple: (pnl_amount, pnl_percentage)
        """
        if self.side == TradeSide.BUY:
            pnl = (exit_price - self.entry_price) * self.quantity
        else:
            pnl = (self.entry_price - exit_price) * self.quantity

        entry_value = self.entry_price * self.quantity
        if entry_value > 0:
            pnl_pct = (pnl / entry_value) * 100
        else:
            pnl_pct = 0.0

        return round(pnl, 2), round(pnl_pct, 2)

    def close(self, exit_price: float, exit_reason: str, exit_time: datetime = None):
        """Close this trade and calculate PnL."""
        self.exit_price = exit_price
        self.exit_reason = exit_reason
        self.exit_time = exit_time or _get_ist_now()
        self.status = TradeStatus.CLOSED

        self.pnl, self.pnl_percentage = self.calculate_pnl(exit_price)
        self.updated_at = _get_ist_now()

        logger.info(
            f"Trade {self.trade_id} closed: "
            f"{self.instrument} {self.side} @ {exit_price:.2f} | "
            f"PnL: {self.pnl:+.2f} ({self.pnl_percentage:+.2f}%) | "
            f"Reason: {exit_reason}"
        )

    def cancel(self, reason: str = "Manual cancellation"):
        """Cancel this trade."""
        self.status = TradeStatus.CANCELLED
        self.notes = reason
        self.updated_at = _get_ist_now()
        logger.info(f"Trade {self.trade_id} cancelled: {reason}")

    def should_stop_loss(self, current_price: float) -> bool:
        """Check if current price has hit stop loss."""
        if self.side == TradeSide.BUY:
            return current_price <= self.stop_loss
        else:
            return current_price >= self.stop_loss

    def should_take_profit(self, current_price: float) -> bool:
        """Check if current price has hit take profit."""
        if self.side == TradeSide.BUY:
            return current_price >= self.take_profit
        else:
            return current_price <= self.take_profit

    def to_dict(self) -> Dict[str, Any]:
        """Convert trade to dictionary."""
        return {
            'id': self.id,
            'trade_id': self.trade_id,
            'symbol': self.symbol,
            'instrument': self.instrument,
            'strike': self.strike,
            'option_type': self.option_type,
            'expiry': self.expiry,
            'side': self.side,
            'quantity': self.quantity,
            'lots': self.lots,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'status': self.status,
            'pnl': self.pnl,
            'pnl_percentage': self.pnl_percentage,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'exit_reason': self.exit_reason,
            'mode': self.mode,
            'duration': self.duration_str,
            'is_profitable': self.is_profitable,
            'risk_reward': self.risk_reward_ratio,
        }

    def __repr__(self) -> str:
        pnl_str = f" PnL:{self.pnl:+.2f}" if self.is_closed else ""
        return (
            f"<Trade({self.trade_id}) {self.side} {self.instrument} "
            f"@ {self.entry_price:.2f} [{self.status}]{pnl_str}>"
        )


# ══════════════════════════════════════════════════════════
# MODEL: POSITION
# ══════════════════════════════════════════════════════════

class Position(Base):
    """
    Currently open position tracking.

    This table tracks the REAL-TIME state of open positions.
    Updated frequently during market hours with current prices.
    """

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(50), nullable=True, index=True)

    # Instrument
    symbol = Column(String(20), nullable=False, index=True)
    instrument = Column(String(50), nullable=False)
    strike = Column(Float, nullable=False)
    option_type = Column(String(2), nullable=False)
    expiry = Column(String(20), nullable=False)

    # Position Details
    side = Column(String(4), nullable=False)
    quantity = Column(Integer, nullable=False)
    lots = Column(Integer, nullable=False, default=1)

    # Prices
    avg_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=True)

    # PnL
    unrealized_pnl = Column(Float, default=0.0)
    unrealized_pnl_pct = Column(Float, default=0.0)

    # Status
    status = Column(String(10), nullable=False, default="OPEN", index=True)

    # Timestamps
    opened_at = Column(DateTime, default=_get_ist_now)
    updated_at = Column(DateTime, default=_get_ist_now, onupdate=_get_ist_now)

    # Indexes
    __table_args__ = (
        Index('idx_position_status', 'status'),
        Index('idx_position_symbol_status', 'symbol', 'status'),
    )

    def update_price(self, current_price: float):
        """Update current price and recalculate unrealized PnL."""
        self.current_price = current_price

        if self.side == TradeSide.BUY:
            self.unrealized_pnl = (current_price - self.avg_price) * self.quantity
        else:
            self.unrealized_pnl = (self.avg_price - current_price) * self.quantity

        entry_value = self.avg_price * self.quantity
        if entry_value > 0:
            self.unrealized_pnl_pct = (self.unrealized_pnl / entry_value) * 100
        else:
            self.unrealized_pnl_pct = 0.0

        self.unrealized_pnl = round(self.unrealized_pnl, 2)
        self.unrealized_pnl_pct = round(self.unrealized_pnl_pct, 2)
        self.updated_at = _get_ist_now()

    def close_position(self):
        """Mark position as closed."""
        self.status = TradeStatus.CLOSED
        self.updated_at = _get_ist_now()

    @property
    def is_open(self) -> bool:
        return self.status == TradeStatus.OPEN

    @property
    def is_profitable(self) -> bool:
        return (self.unrealized_pnl or 0) > 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert position to dictionary."""
        return {
            'id': self.id,
            'trade_id': self.trade_id,
            'symbol': self.symbol,
            'instrument': self.instrument,
            'strike': self.strike,
            'option_type': self.option_type,
            'side': self.side,
            'quantity': self.quantity,
            'lots': self.lots,
            'avg_price': self.avg_price,
            'current_price': self.current_price,
            'unrealized_pnl': self.unrealized_pnl,
            'unrealized_pnl_pct': self.unrealized_pnl_pct,
            'status': self.status,
        }

    def __repr__(self) -> str:
        pnl = self.unrealized_pnl or 0
        return (
            f"<Position {self.side} {self.instrument} "
            f"qty={self.quantity} PnL:{pnl:+.2f}>"
        )


# ══════════════════════════════════════════════════════════
# MODEL: SIGNAL
# ══════════════════════════════════════════════════════════

class Signal(Base):
    """
    Brain signal record.

    Every signal generated by every brain is stored here.
    Even signals NOT executed are stored for review.
    """

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(String(50), unique=True, nullable=False, index=True)

    # Timing
    timestamp = Column(DateTime, nullable=False, default=_get_ist_now, index=True)

    # Instrument
    symbol = Column(String(20), nullable=False, index=True)
    instrument = Column(String(50), nullable=True)

    # Signal Details
    action = Column(String(4), nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    brain_name = Column(String(50), nullable=False)
    reasoning = Column(Text, nullable=True)

    # Indicator Data (JSON string)
    indicators = Column(Text, nullable=True)

    # Execution Status
    executed = Column(Boolean, default=False, index=True)

    # Link to Trade
    trade_id_ref = Column(
        String(50),
        ForeignKey('trades.trade_id'),
        nullable=True,
    )

    # Audit
    created_at = Column(DateTime, default=_get_ist_now)

    # Relationships
    trade = relationship("Trade", back_populates="signals")

    # Indexes
    __table_args__ = (
        Index('idx_signal_symbol_timestamp', 'symbol', 'timestamp'),
        Index('idx_signal_brain_action', 'brain_name', 'action'),
        Index('idx_signal_executed', 'executed'),
    )

    @property
    def is_buy(self) -> bool:
        return self.action == "BUY"

    @property
    def is_sell(self) -> bool:
        return self.action == "SELL"

    @property
    def is_hold(self) -> bool:
        return self.action == "HOLD"

    @property
    def is_strong_signal(self) -> bool:
        """Confidence > 0.7 is considered strong."""
        return (self.confidence or 0) > 0.7

    @property
    def indicators_dict(self) -> Dict:
        """Parse indicators JSON to dict."""
        if not self.indicators:
            return {}
        try:
            return json.loads(self.indicators)
        except (json.JSONDecodeError, TypeError):
            return {}

    @indicators_dict.setter
    def indicators_dict(self, value: Dict):
        """Set indicators from dict."""
        if value:
            self.indicators = json.dumps(value)
        else:
            self.indicators = None

    def mark_executed(self, trade_id: str):
        """Mark this signal as executed and link to trade."""
        self.executed = True
        self.trade_id_ref = trade_id

    def to_dict(self) -> Dict[str, Any]:
        """Convert signal to dictionary."""
        return {
            'signal_id': self.signal_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'symbol': self.symbol,
            'instrument': self.instrument,
            'action': self.action,
            'confidence': self.confidence,
            'brain_name': self.brain_name,
            'reasoning': self.reasoning,
            'indicators': self.indicators_dict,
            'executed': self.executed,
            'trade_id': self.trade_id_ref,
        }

    def __repr__(self) -> str:
        executed_str = "✅" if self.executed else "⏳"
        return (
            f"<Signal({self.signal_id}) {self.action} {self.symbol} "
            f"conf={self.confidence:.0%} brain={self.brain_name} {executed_str}>"
        )


# ══════════════════════════════════════════════════════════
# MODEL: DAILY SNAPSHOT
# ══════════════════════════════════════════════════════════

class DailySnapshot(Base):
    """
    End-of-day performance snapshot.

    One record per trading day. This builds the EQUITY CURVE.
    """

    __tablename__ = "daily_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, unique=True, nullable=False, index=True)

    # Capital
    starting_capital = Column(Float, nullable=False)
    ending_capital = Column(Float, nullable=False)

    # PnL
    total_pnl = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)

    # Trade Stats
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)

    # Risk Metrics
    max_drawdown = Column(Float, default=0.0)
    max_profit = Column(Float, default=0.0)
    max_loss = Column(Float, default=0.0)

    # Notes
    notes = Column(Text, nullable=True)

    # Audit
    created_at = Column(DateTime, default=_get_ist_now)
    updated_at = Column(DateTime, default=_get_ist_now, onupdate=_get_ist_now)

    @property
    def is_profitable_day(self) -> bool:
        """Was this a profitable trading day?"""
        return (self.total_pnl or 0) > 0

    @property
    def capital_change_pct(self) -> float:
        """Percentage change in capital."""
        if self.starting_capital and self.starting_capital > 0:
            return ((self.ending_capital - self.starting_capital) / self.starting_capital) * 100
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary."""
        return {
            'date': self.date.isoformat() if self.date else None,
            'starting_capital': self.starting_capital,
            'ending_capital': self.ending_capital,
            'total_pnl': self.total_pnl,
            'realized_pnl': self.realized_pnl,
            'unrealized_pnl': self.unrealized_pnl,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'max_drawdown': self.max_drawdown,
            'capital_change_pct': round(self.capital_change_pct, 2),
            'is_profitable': self.is_profitable_day,
        }

    def __repr__(self) -> str:
        pnl = self.total_pnl or 0
        emoji = "📈" if pnl > 0 else "📉" if pnl < 0 else "➡️"
        return (
            f"<DailySnapshot({self.date}) {emoji} "
            f"PnL:{pnl:+.2f} Trades:{self.total_trades} "
            f"WR:{self.win_rate:.0f}%>"
        )


# ══════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  DATABASE MODELS - TEST")
    print("=" * 60)

    # Test Trade Model
    print("\n  1. Testing Trade model...")
    trade = Trade(
        trade_id="TRD-20250305-001",
        symbol="NIFTY",
        instrument="NIFTY 24500 CE",
        strike=24500,
        option_type="CE",
        expiry="05MAR",
        side="BUY",
        quantity=25,
        lots=1,
        entry_price=125.50,
        stop_loss=87.85,
        take_profit=188.25,
        status="OPEN",
        mode="PAPER",
    )

    print(f"     Created: {trade}")
    print(f"     Entry Value: {trade.entry_value:,.2f}")
    print(f"     Risk/Reward: {trade.risk_reward_ratio}")

    pnl, pnl_pct = trade.calculate_pnl(180.00)
    print(f"     If exit @ 180: PnL = {pnl:+,.2f} ({pnl_pct:+.2f}%)")

    trade.close(exit_price=180.00, exit_reason=ExitReason.TAKE_PROFIT)
    print(f"     After close: {trade}")
    print(f"     Profitable: {trade.is_profitable}")

    # Test Position Model
    print("\n  2. Testing Position model...")
    position = Position(
        symbol="BANKNIFTY",
        instrument="BANKNIFTY 48700 PE",
        strike=48700,
        option_type="PE",
        expiry="05MAR",
        side="BUY",
        quantity=15,
        lots=1,
        avg_price=200.00,
    )

    position.update_price(250.00)
    print(f"     PnL @ 250: {position.unrealized_pnl:+,.2f} ({position.unrealized_pnl_pct:+.2f}%)")

    position.update_price(150.00)
    print(f"     PnL @ 150: {position.unrealized_pnl:+,.2f} ({position.unrealized_pnl_pct:+.2f}%)")

    # Test Signal Model
    print("\n  3. Testing Signal model...")
    signal = Signal(
        signal_id="SIG-20250305-001",
        symbol="NIFTY",
        action="BUY",
        confidence=0.85,
        brain_name="technical",
        reasoning="RSI oversold + MACD bullish crossover",
    )
    signal.indicators_dict = {'rsi': 28.5, 'macd': 'bullish'}
    print(f"     Created: {signal}")
    print(f"     Strong: {signal.is_strong_signal}")

    # Test DailySnapshot
    print("\n  4. Testing DailySnapshot model...")
    snapshot = DailySnapshot(
        date=date.today(),
        starting_capital=10000.00,
        ending_capital=11250.00,
        total_pnl=1250.00,
        realized_pnl=1250.00,
        total_trades=5,
        winning_trades=3,
        losing_trades=2,
        win_rate=60.0,
    )
    print(f"     Created: {snapshot}")
    print(f"     Capital Change: {snapshot.capital_change_pct:+.2f}%")

    # Test database creation
    print("\n  5. Testing database creation...")
    try:
        from sqlalchemy import create_engine, inspect

        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(engine)

        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"     ✅ Created {len(tables)} tables: {', '.join(tables)}")

        columns = [col['name'] for col in inspector.get_columns('trades')]
        print(f"     ✅ Trade columns: {len(columns)}")

        engine.dispose()

    except Exception as e:
        print(f"     ❌ Error: {e}")

    print("\n" + "=" * 60)
    print("  All Model Tests Complete! ✅")
    print("=" * 60 + "\n")