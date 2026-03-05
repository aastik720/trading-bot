"""
Constants Module
================
All magic numbers, fixed values, and enums in ONE place.

Usage:
    from config.constants import SIGNAL_BUY, RSI_OVERSOLD
    
    if signal == SIGNAL_BUY:
        print("Buying!")
    
    if rsi < RSI_OVERSOLD:
        print("Stock is oversold!")
"""


# ══════════════════════════════════════════════════════════
# SIGNAL TYPES
# ══════════════════════════════════════════════════════════

SIGNAL_BUY = "BUY"
SIGNAL_SELL = "SELL"
SIGNAL_HOLD = "HOLD"


# ══════════════════════════════════════════════════════════
# ORDER TYPES
# ══════════════════════════════════════════════════════════

ORDER_TYPE_MARKET = "MARKET"
ORDER_TYPE_LIMIT = "LIMIT"

ORDER_SIDE_BUY = "BUY"
ORDER_SIDE_SELL = "SELL"

ORDER_STATUS_PENDING = "PENDING"
ORDER_STATUS_OPEN = "OPEN"
ORDER_STATUS_FILLED = "FILLED"
ORDER_STATUS_CLOSED = "CLOSED"
ORDER_STATUS_CANCELLED = "CANCELLED"


# ══════════════════════════════════════════════════════════
# OPTION TYPES
# ══════════════════════════════════════════════════════════

OPTION_TYPE_CALL = "CE"
OPTION_TYPE_PUT = "PE"

OPTION_EXPIRY_WEEKLY = "WEEKLY"
OPTION_EXPIRY_MONTHLY = "MONTHLY"

# Strike selection
STRIKE_ATM = "ATM"       # At The Money
STRIKE_ITM = "ITM"       # In The Money
STRIKE_OTM = "OTM"       # Out of The Money
STRIKE_OTM1 = "OTM1"     # 1 strike out of money
STRIKE_OTM2 = "OTM2"     # 2 strikes out of money


# ══════════════════════════════════════════════════════════
# INSTRUMENTS
# ══════════════════════════════════════════════════════════

INSTRUMENT_NIFTY = "NIFTY"
INSTRUMENT_BANKNIFTY = "BANKNIFTY"

# Lot sizes (fixed by exchange)
LOT_SIZE_NIFTY = 25
LOT_SIZE_BANKNIFTY = 15

# Strike step (gap between strikes)
STRIKE_STEP_NIFTY = 50       # 24500, 24550, 24600...
STRIKE_STEP_BANKNIFTY = 100  # 52000, 52100, 52200...


# ══════════════════════════════════════════════════════════
# RSI INDICATOR
# ══════════════════════════════════════════════════════════

RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70


# ══════════════════════════════════════════════════════════
# MACD INDICATOR
# ══════════════════════════════════════════════════════════

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9


# ══════════════════════════════════════════════════════════
# MOVING AVERAGES
# ══════════════════════════════════════════════════════════

SMA_SHORT = 20
SMA_LONG = 50
EMA_SHORT = 9
EMA_LONG = 21


# ══════════════════════════════════════════════════════════
# BOLLINGER BANDS
# ══════════════════════════════════════════════════════════

BOLLINGER_PERIOD = 20
BOLLINGER_STD_DEV = 2


# ══════════════════════════════════════════════════════════
# RISK DEFAULTS
# ══════════════════════════════════════════════════════════

# For options (percentage of premium)
DEFAULT_STOP_LOSS_PCT = 30.0      # 30% of premium
DEFAULT_TAKE_PROFIT_PCT = 50.0    # 50% of premium
DEFAULT_TRAILING_STOP_PCT = 20.0  # 20% trailing

# Circuit breaker
DEFAULT_MAX_CONSECUTIVE_LOSSES = 5
DEFAULT_CIRCUIT_BREAKER_COOLDOWN = 3600  # 1 hour in seconds

# Daily limits
DEFAULT_MAX_DAILY_LOSS_PCT = 3.0  # 3% of capital


# ══════════════════════════════════════════════════════════
# MARKET TIMING (IST)
# ══════════════════════════════════════════════════════════

MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15

MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30

# Pre-market
PRE_MARKET_OPEN_HOUR = 9
PRE_MARKET_OPEN_MINUTE = 0

# Trading cutoffs
NO_NEW_TRADES_HOUR = 14
NO_NEW_TRADES_MINUTE = 30

CLOSE_ALL_HOUR = 15
CLOSE_ALL_MINUTE = 15


# ══════════════════════════════════════════════════════════
# TIMEFRAMES
# ══════════════════════════════════════════════════════════

TIMEFRAME_1MIN = "1m"
TIMEFRAME_5MIN = "5m"
TIMEFRAME_15MIN = "15m"
TIMEFRAME_1HOUR = "1h"
TIMEFRAME_1DAY = "1d"


# ══════════════════════════════════════════════════════════
# CONFIDENCE THRESHOLDS
# ══════════════════════════════════════════════════════════

# Minimum confidence to take a trade
MIN_CONFIDENCE_THRESHOLD = 0.60  # 60%

# Strong signal threshold
STRONG_SIGNAL_THRESHOLD = 0.75   # 75%

# Weak signal (maybe skip)
WEAK_SIGNAL_THRESHOLD = 0.50     # 50%


# ══════════════════════════════════════════════════════════
# API SETTINGS
# ══════════════════════════════════════════════════════════

API_TIMEOUT = 10           # seconds
API_MAX_RETRIES = 3
API_RETRY_DELAY = 2        # seconds between retries

# Rate limits
DHAN_RATE_LIMIT = 10       # requests per second
FINNHUB_RATE_LIMIT = 60    # requests per minute


# ══════════════════════════════════════════════════════════
# TRADING BOT STATES
# ══════════════════════════════════════════════════════════

BOT_STATE_STOPPED = "STOPPED"
BOT_STATE_RUNNING = "RUNNING"
BOT_STATE_PAUSED = "PAUSED"
BOT_STATE_ERROR = "ERROR"


# ══════════════════════════════════════════════════════════
# BRAIN NAMES
# ══════════════════════════════════════════════════════════

BRAIN_TECHNICAL = "technical"
BRAIN_SENTIMENT = "sentiment"
BRAIN_PATTERN = "pattern"
BRAIN_AI = "ai"
BRAIN_NEWS = "news"


# ══════════════════════════════════════════════════════════
# ERROR CODES
# ══════════════════════════════════════════════════════════

ERROR_API_TIMEOUT = "API_TIMEOUT"
ERROR_API_ERROR = "API_ERROR"
ERROR_INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
ERROR_MAX_POSITIONS = "MAX_POSITIONS"
ERROR_CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
ERROR_MARKET_CLOSED = "MARKET_CLOSED"
ERROR_INVALID_ORDER = "INVALID_ORDER"


# ══════════════════════════════════════════════════════════
# MISC
# ══════════════════════════════════════════════════════════

# App info
APP_NAME = "Trading Bot"
APP_VERSION = "1.0.0"

# Timezone
TIMEZONE_IST = "Asia/Kolkata"

# Database
DEFAULT_DB_URL = "sqlite:///trading_bot.db"

# Logs
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


# ══════════════════════════════════════════════════════════
# TEST - Run this file directly to see all constants
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  TRADING BOT CONSTANTS")
    print("=" * 50)
    
    print("\n  SIGNALS:")
    print(f"    BUY:  {SIGNAL_BUY}")
    print(f"    SELL: {SIGNAL_SELL}")
    print(f"    HOLD: {SIGNAL_HOLD}")
    
    print("\n  OPTIONS:")
    print(f"    CALL: {OPTION_TYPE_CALL}")
    print(f"    PUT:  {OPTION_TYPE_PUT}")
    
    print("\n  LOT SIZES:")
    print(f"    NIFTY:     {LOT_SIZE_NIFTY}")
    print(f"    BANKNIFTY: {LOT_SIZE_BANKNIFTY}")
    
    print("\n  RSI:")
    print(f"    Period:     {RSI_PERIOD}")
    print(f"    Oversold:   {RSI_OVERSOLD}")
    print(f"    Overbought: {RSI_OVERBOUGHT}")
    
    print("\n  RISK:")
    print(f"    Stop Loss:   {DEFAULT_STOP_LOSS_PCT}%")
    print(f"    Take Profit: {DEFAULT_TAKE_PROFIT_PCT}%")
    print(f"    Max Losses:  {DEFAULT_MAX_CONSECUTIVE_LOSSES}")
    
    print("\n  MARKET HOURS:")
    print(f"    Open:  {MARKET_OPEN_HOUR}:{MARKET_OPEN_MINUTE:02d}")
    print(f"    Close: {MARKET_CLOSE_HOUR}:{MARKET_CLOSE_MINUTE:02d}")
    
    print("\n" + "=" * 50)
    print("  All constants loaded!")
    print("=" * 50 + "\n")