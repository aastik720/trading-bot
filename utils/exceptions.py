"""
Exceptions Module
=================
Custom exception classes for the trading bot.

Usage:
    from utils.exceptions import InsufficientFundsError, APIError
    
    try:
        place_order(...)
    except InsufficientFundsError as e:
        print(f"Not enough money: {e}")
    except APIError as e:
        print(f"API failed: {e}")

Hierarchy:
    TradingBotError (base)
    ├── ConfigError
    ├── APIError
    │   ├── DhanAPIError
    │   └── FinnhubAPIError
    ├── DataError
    ├── BrainError
    ├── RiskError
    │   ├── InsufficientFundsError
    │   ├── MaxPositionsError
    │   └── DailyLossLimitError
    ├── OrderError
    ├── CircuitBreakerError
    └── MarketClosedError
"""


# ══════════════════════════════════════════════════════════
# BASE EXCEPTION
# ══════════════════════════════════════════════════════════

class TradingBotError(Exception):
    """
    Base exception for all trading bot errors.
    
    All custom exceptions inherit from this.
    Catch this to catch ANY bot error.
    """
    
    def __init__(self, message: str = "Trading bot error occurred"):
        self.message = message
        super().__init__(self.message)
    
    def __str__(self):
        return self.message


# ══════════════════════════════════════════════════════════
# CONFIG ERRORS
# ══════════════════════════════════════════════════════════

class ConfigError(TradingBotError):
    """
    Configuration is missing or invalid.
    
    Raised when:
        - .env file not found
        - Required API key missing
        - Invalid setting value
    """
    
    def __init__(self, message: str = "Configuration error"):
        super().__init__(f"CONFIG ERROR: {message}")


# ══════════════════════════════════════════════════════════
# API ERRORS
# ══════════════════════════════════════════════════════════

class APIError(TradingBotError):
    """
    External API call failed.
    
    Base class for all API-related errors.
    """
    
    def __init__(self, message: str = "API error", status_code: int = None):
        self.status_code = status_code
        error_msg = f"API ERROR: {message}"
        if status_code:
            error_msg += f" (Status: {status_code})"
        super().__init__(error_msg)


class DhanAPIError(APIError):
    """
    Dhan broker API error.
    
    Raised when:
        - Connection to Dhan fails
        - Invalid credentials
        - Order placement fails
        - Rate limit exceeded
    """
    
    def __init__(self, message: str = "Dhan API error", status_code: int = None):
        super().__init__(f"DHAN: {message}", status_code)


class FinnhubAPIError(APIError):
    """
    Finnhub API error.
    
    Raised when:
        - Connection to Finnhub fails
        - Invalid API key
        - Rate limit exceeded
    """
    
    def __init__(self, message: str = "Finnhub API error", status_code: int = None):
        super().__init__(f"FINNHUB: {message}", status_code)


class TelegramAPIError(APIError):
    """
    Telegram Bot API error.
    
    Raised when:
        - Bot token invalid
        - Message send fails
        - Chat not found
    """
    
    def __init__(self, message: str = "Telegram API error", status_code: int = None):
        super().__init__(f"TELEGRAM: {message}", status_code)


# ══════════════════════════════════════════════════════════
# DATA ERRORS
# ══════════════════════════════════════════════════════════

class DataError(TradingBotError):
    """
    Market data error.
    
    Raised when:
        - Price data unavailable
        - Invalid OHLCV data
        - Data format unexpected
    """
    
    def __init__(self, message: str = "Data error"):
        super().__init__(f"DATA ERROR: {message}")


class NoDataError(DataError):
    """
    No data available for symbol.
    """
    
    def __init__(self, symbol: str = "Unknown"):
        super().__init__(f"No data available for {symbol}")


class StaleDataError(DataError):
    """
    Data is too old / stale.
    """
    
    def __init__(self, symbol: str = "Unknown", age_seconds: int = 0):
        super().__init__(f"Data for {symbol} is {age_seconds}s old (stale)")


# ══════════════════════════════════════════════════════════
# BRAIN ERRORS
# ══════════════════════════════════════════════════════════

class BrainError(TradingBotError):
    """
    Brain analysis error.
    
    Raised when:
        - Brain fails to analyze
        - Invalid signal generated
        - Missing indicator data
    """
    
    def __init__(self, brain_name: str = "Unknown", message: str = "Analysis failed"):
        super().__init__(f"BRAIN ERROR [{brain_name}]: {message}")
        self.brain_name = brain_name


# ══════════════════════════════════════════════════════════
# RISK ERRORS
# ══════════════════════════════════════════════════════════

class RiskError(TradingBotError):
    """
    Risk check failed.
    
    Base class for all risk-related rejections.
    """
    
    def __init__(self, message: str = "Risk check failed"):
        super().__init__(f"RISK ERROR: {message}")


class InsufficientFundsError(RiskError):
    """
    Not enough capital for trade.
    """
    
    def __init__(self, required: float = 0, available: float = 0):
        self.required = required
        self.available = available
        super().__init__(
            f"Insufficient funds. Need Rs.{required:,.0f}, have Rs.{available:,.0f}"
        )


class MaxPositionsError(RiskError):
    """
    Maximum open positions reached.
    """
    
    def __init__(self, current: int = 0, maximum: int = 0):
        self.current = current
        self.maximum = maximum
        super().__init__(
            f"Max positions reached. Current: {current}/{maximum}"
        )


class DailyLossLimitError(RiskError):
    """
    Daily loss limit exceeded.
    """
    
    def __init__(self, current_loss: float = 0, max_loss: float = 0):
        self.current_loss = current_loss
        self.max_loss = max_loss
        super().__init__(
            f"Daily loss limit hit. Loss: Rs.{current_loss:,.0f}, Max: Rs.{max_loss:,.0f}"
        )


class MaxTradesError(RiskError):
    """
    Maximum trades per day reached.
    """
    
    def __init__(self, current: int = 0, maximum: int = 0):
        self.current = current
        self.maximum = maximum
        super().__init__(
            f"Max daily trades reached. Trades: {current}/{maximum}"
        )


class PositionSizeError(RiskError):
    """
    Position size exceeds limit.
    """
    
    def __init__(self, size: float = 0, max_size: float = 0):
        super().__init__(
            f"Position too large. Size: Rs.{size:,.0f}, Max: Rs.{max_size:,.0f}"
        )


# ══════════════════════════════════════════════════════════
# ORDER ERRORS
# ══════════════════════════════════════════════════════════

class OrderError(TradingBotError):
    """
    Order creation or execution error.
    """
    
    def __init__(self, message: str = "Order error", order_id: str = None):
        self.order_id = order_id
        error_msg = f"ORDER ERROR: {message}"
        if order_id:
            error_msg += f" (Order: {order_id})"
        super().__init__(error_msg)


class OrderRejectedError(OrderError):
    """
    Order was rejected by broker.
    """
    
    def __init__(self, reason: str = "Unknown", order_id: str = None):
        super().__init__(f"Order rejected: {reason}", order_id)


class OrderNotFoundError(OrderError):
    """
    Order not found.
    """
    
    def __init__(self, order_id: str = "Unknown"):
        super().__init__(f"Order not found: {order_id}", order_id)


# ══════════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════

class CircuitBreakerError(TradingBotError):
    """
    Circuit breaker triggered - emergency stop.
    
    Raised when:
        - Max consecutive losses hit
        - Daily loss limit exceeded
        - Manual emergency stop
    """
    
    def __init__(self, reason: str = "Circuit breaker triggered", cooldown: int = 0):
        self.reason = reason
        self.cooldown = cooldown
        msg = f"CIRCUIT BREAKER: {reason}"
        if cooldown > 0:
            msg += f" (Cooldown: {cooldown}s)"
        super().__init__(msg)


# ══════════════════════════════════════════════════════════
# MARKET ERRORS
# ══════════════════════════════════════════════════════════

class MarketClosedError(TradingBotError):
    """
    Market is not open for trading.
    """
    
    def __init__(self, message: str = "Market is closed"):
        super().__init__(f"MARKET CLOSED: {message}")


class MarketHolidayError(MarketClosedError):
    """
    Today is a market holiday.
    """
    
    def __init__(self, holiday_name: str = "Holiday"):
        super().__init__(f"Today is {holiday_name}")


# ══════════════════════════════════════════════════════════
# OPTIONS SPECIFIC ERRORS
# ══════════════════════════════════════════════════════════

class OptionsError(TradingBotError):
    """
    Options trading specific error.
    """
    
    def __init__(self, message: str = "Options error"):
        super().__init__(f"OPTIONS ERROR: {message}")


class InvalidStrikeError(OptionsError):
    """
    Invalid strike price.
    """
    
    def __init__(self, strike: float = 0, instrument: str = ""):
        super().__init__(f"Invalid strike {strike} for {instrument}")


class PremiumTooHighError(OptionsError):
    """
    Option premium exceeds budget.
    """
    
    def __init__(self, premium: float = 0, max_premium: float = 0):
        super().__init__(
            f"Premium too high. Premium: Rs.{premium}, Max: Rs.{max_premium}"
        )


class ExpiryTooCloseError(OptionsError):
    """
    Expiry too close - high theta risk.
    """
    
    def __init__(self, hours_to_expiry: int = 0):
        super().__init__(f"Expiry too close: {hours_to_expiry} hours remaining")


# ══════════════════════════════════════════════════════════
# TEST - Run this file directly to test exceptions
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("  TESTING CUSTOM EXCEPTIONS")
    print("=" * 55)
    
    # Test each exception
    exceptions_to_test = [
        ConfigError("Missing DHAN_API_KEY"),
        DhanAPIError("Connection timeout", 408),
        InsufficientFundsError(5000, 2500),
        MaxPositionsError(4, 4),
        DailyLossLimitError(350, 300),
        CircuitBreakerError("5 consecutive losses", 3600),
        MarketClosedError("Opens at 9:15 AM"),
        PremiumTooHighError(300, 250),
    ]
    
    for exc in exceptions_to_test:
        print(f"\n  {type(exc).__name__}:")
        print(f"    {exc}")
    
    print("\n" + "=" * 55)
    
    # Test catching hierarchy
    print("\n  Testing exception hierarchy:")
    
    try:
        raise InsufficientFundsError(5000, 2500)
    except RiskError as e:
        print(f"    Caught as RiskError: {e}")
    
    try:
        raise DhanAPIError("Timeout")
    except APIError as e:
        print(f"    Caught as APIError: {e}")
    
    try:
        raise ConfigError("Missing key")
    except TradingBotError as e:
        print(f"    Caught as TradingBotError: {e}")
    
    print("\n" + "=" * 55)
    print("  All exceptions working!")
    print("=" * 55 + "\n")