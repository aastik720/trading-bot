"""
Utils Package
=============
Utility functions and helpers for the trading bot.
"""

from utils.helpers import (
    get_ist_now,
    format_currency,
    format_percentage,
    format_pnl,
    format_duration,
    safe_divide,
    generate_order_id,
    get_atm_strike,
)

from utils.indian_market import (
    is_market_open,
    is_trading_day,
    get_market_status,
    get_time_to_market_open,
    get_next_trading_day,
    get_weekly_expiry,
)

from utils.exceptions import (
    TradingBotError,
    ConfigError,
    APIError,
    RiskError,
    CircuitBreakerError,
    MarketClosedError,
)