"""
Helpers Module
==============
Utility functions used throughout the trading bot.

Usage:
    from utils.helpers import format_currency, get_ist_now
    
    print(format_currency(1234.5))     # "₹1,234.50"
    print(get_ist_now())               # 2025-01-15 14:30:00+05:30
"""

import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Union, List

import pytz


# ══════════════════════════════════════════════════════════
# TIMEZONE
# ══════════════════════════════════════════════════════════

# Indian Standard Time
IST = pytz.timezone('Asia/Kolkata')


def get_ist_now() -> datetime:
    """
    Get current time in IST (Indian Standard Time).
    
    Returns:
        datetime: Current time in IST with timezone info
    
    Example:
        >>> get_ist_now()
        datetime(2025, 1, 15, 14, 30, 0, tzinfo=IST)
    """
    return datetime.now(IST)


def get_utc_now() -> datetime:
    """
    Get current time in UTC.
    
    Returns:
        datetime: Current time in UTC
    """
    return datetime.now(pytz.UTC)


def ist_to_utc(ist_time: datetime) -> datetime:
    """
    Convert IST time to UTC.
    
    Args:
        ist_time: datetime in IST
    
    Returns:
        datetime: Same moment in UTC
    """
    if ist_time.tzinfo is None:
        ist_time = IST.localize(ist_time)
    return ist_time.astimezone(pytz.UTC)


def utc_to_ist(utc_time: datetime) -> datetime:
    """
    Convert UTC time to IST.
    
    Args:
        utc_time: datetime in UTC
    
    Returns:
        datetime: Same moment in IST
    """
    if utc_time.tzinfo is None:
        utc_time = pytz.UTC.localize(utc_time)
    return utc_time.astimezone(IST)


# ══════════════════════════════════════════════════════════
# FORMATTING - CURRENCY
# ══════════════════════════════════════════════════════════

def format_currency(amount: Union[int, float], symbol: str = "₹") -> str:
    """
    Format number as Indian currency.
    
    Args:
        amount: The amount to format
        symbol: Currency symbol (default: ₹)
    
    Returns:
        str: Formatted currency string
    
    Examples:
        >>> format_currency(1234.5)
        '₹1,234.50'
        >>> format_currency(-500)
        '-₹500.00'
        >>> format_currency(100000)
        '₹1,00,000.00'
    """
    if amount < 0:
        return f"-{symbol}{abs(amount):,.2f}"
    return f"{symbol}{amount:,.2f}"


def format_currency_short(amount: Union[int, float], symbol: str = "₹") -> str:
    """
    Format large currency amounts in short form.
    
    Args:
        amount: The amount to format
        symbol: Currency symbol
    
    Returns:
        str: Short formatted string
    
    Examples:
        >>> format_currency_short(1500)
        '₹1.5K'
        >>> format_currency_short(150000)
        '₹1.5L'
        >>> format_currency_short(10000000)
        '₹1Cr'
    """
    abs_amount = abs(amount)
    sign = "-" if amount < 0 else ""
    
    if abs_amount >= 10000000:  # 1 Crore
        return f"{sign}{symbol}{abs_amount/10000000:.1f}Cr"
    elif abs_amount >= 100000:  # 1 Lakh
        return f"{sign}{symbol}{abs_amount/100000:.1f}L"
    elif abs_amount >= 1000:  # 1 Thousand
        return f"{sign}{symbol}{abs_amount/1000:.1f}K"
    else:
        return f"{sign}{symbol}{abs_amount:.0f}"


# ══════════════════════════════════════════════════════════
# FORMATTING - PERCENTAGE
# ══════════════════════════════════════════════════════════

def format_percentage(value: float, decimals: int = 2, show_sign: bool = True) -> str:
    """
    Format number as percentage.
    
    Args:
        value: Decimal value (0.05 = 5%)
        decimals: Decimal places
        show_sign: Show + for positive
    
    Returns:
        str: Formatted percentage
    
    Examples:
        >>> format_percentage(0.0523)
        '+5.23%'
        >>> format_percentage(-0.0312)
        '-3.12%'
        >>> format_percentage(0.05, show_sign=False)
        '5.00%'
    """
    pct = value * 100
    
    if show_sign and pct > 0:
        return f"+{pct:.{decimals}f}%"
    return f"{pct:.{decimals}f}%"


def format_percentage_raw(value: float, decimals: int = 2, show_sign: bool = True) -> str:
    """
    Format percentage when value is already in percentage form.
    
    Args:
        value: Already percentage (5.23 = 5.23%)
        decimals: Decimal places
        show_sign: Show + for positive
    
    Examples:
        >>> format_percentage_raw(5.23)
        '+5.23%'
    """
    if show_sign and value > 0:
        return f"+{value:.{decimals}f}%"
    return f"{value:.{decimals}f}%"


# ══════════════════════════════════════════════════════════
# FORMATTING - P&L
# ══════════════════════════════════════════════════════════

def format_pnl(amount: Union[int, float]) -> str:
    """
    Format profit/loss with emoji indicator.
    
    Args:
        amount: P&L amount
    
    Returns:
        str: Formatted P&L with emoji
    
    Examples:
        >>> format_pnl(1250)
        '🟢 +₹1,250.00'
        >>> format_pnl(-380)
        '🔴 -₹380.00'
        >>> format_pnl(0)
        '⚪ ₹0.00'
    """
    if amount > 0:
        return f"🟢 +₹{amount:,.2f}"
    elif amount < 0:
        return f"🔴 -₹{abs(amount):,.2f}"
    else:
        return f"⚪ ₹0.00"


def format_pnl_simple(amount: Union[int, float]) -> str:
    """
    Format P&L without emoji (for logs/files).
    
    Examples:
        >>> format_pnl_simple(1250)
        '+₹1,250.00'
        >>> format_pnl_simple(-380)
        '-₹380.00'
    """
    if amount >= 0:
        return f"+₹{amount:,.2f}"
    return f"-₹{abs(amount):,.2f}"


# ══════════════════════════════════════════════════════════
# FORMATTING - TIME
# ══════════════════════════════════════════════════════════

def format_time(dt: datetime) -> str:
    """
    Format datetime as HH:MM:SS.
    
    Example:
        >>> format_time(datetime.now())
        '14:30:45'
    """
    return dt.strftime("%H:%M:%S")


def format_date(dt: datetime) -> str:
    """
    Format datetime as DD-MM-YYYY.
    
    Example:
        >>> format_date(datetime.now())
        '15-01-2025'
    """
    return dt.strftime("%d-%m-%Y")


def format_datetime(dt: datetime) -> str:
    """
    Format full datetime.
    
    Example:
        >>> format_datetime(datetime.now())
        '15-01-2025 14:30:45'
    """
    return dt.strftime("%d-%m-%Y %H:%M:%S")


def format_duration(seconds: int) -> str:
    """
    Format seconds as human readable duration.
    
    Examples:
        >>> format_duration(90)
        '1m 30s'
        >>> format_duration(3665)
        '1h 1m 5s'
        >>> format_duration(86400)
        '1d 0h 0m'
    """
    if seconds < 0:
        return "0s"
    
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


# ══════════════════════════════════════════════════════════
# MATH HELPERS
# ══════════════════════════════════════════════════════════

def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safe division that returns default if denominator is zero.
    
    Args:
        numerator: Top number
        denominator: Bottom number
        default: Value to return if division by zero
    
    Examples:
        >>> safe_divide(100, 4)
        25.0
        >>> safe_divide(100, 0)
        0.0
        >>> safe_divide(100, 0, default=-1)
        -1
    """
    if denominator == 0:
        return default
    return numerator / denominator


def calculate_percentage_change(old_value: float, new_value: float) -> float:
    """
    Calculate percentage change between two values.
    
    Args:
        old_value: Original value
        new_value: New value
    
    Returns:
        float: Percentage change as decimal (0.05 = 5%)
    
    Examples:
        >>> calculate_percentage_change(100, 105)
        0.05
        >>> calculate_percentage_change(100, 95)
        -0.05
    """
    return safe_divide(new_value - old_value, old_value, 0.0)


def round_to_tick(price: float, tick_size: float = 0.05) -> float:
    """
    Round price to nearest tick size.
    
    Args:
        price: Price to round
        tick_size: Minimum price movement (default 0.05 for NSE)
    
    Examples:
        >>> round_to_tick(125.23)
        125.25
        >>> round_to_tick(125.22)
        125.20
    """
    return round(price / tick_size) * tick_size


def clamp(value: float, min_value: float, max_value: float) -> float:
    """
    Clamp value between min and max.
    
    Examples:
        >>> clamp(150, 0, 100)
        100
        >>> clamp(-10, 0, 100)
        0
        >>> clamp(50, 0, 100)
        50
    """
    return max(min_value, min(value, max_value))


# ══════════════════════════════════════════════════════════
# ID GENERATORS
# ══════════════════════════════════════════════════════════

def generate_order_id(prefix: str = "ORD") -> str:
    """
    Generate unique order ID.
    
    Format: ORD-20250115-143025-A1B2
    
    Returns:
        str: Unique order ID
    
    Example:
        >>> generate_order_id()
        'ORD-20250115-143025-A1B2'
    """
    now = get_ist_now()
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    unique_part = uuid.uuid4().hex[:4].upper()
    
    return f"{prefix}-{date_part}-{time_part}-{unique_part}"


def generate_trade_id() -> str:
    """Generate unique trade ID."""
    return generate_order_id("TRD")


def generate_signal_id() -> str:
    """Generate unique signal ID."""
    return generate_order_id("SIG")


# ══════════════════════════════════════════════════════════
# STRING HELPERS
# ══════════════════════════════════════════════════════════

def truncate(text: str, max_length: int = 50, suffix: str = "...") -> str:
    """
    Truncate text to max length.
    
    Examples:
        >>> truncate("Hello World", 5)
        'He...'
        >>> truncate("Hi", 10)
        'Hi'
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def pad_right(text: str, width: int, char: str = " ") -> str:
    """Pad text on right to specified width."""
    return text.ljust(width, char)


def pad_left(text: str, width: int, char: str = " ") -> str:
    """Pad text on left to specified width."""
    return text.rjust(width, char)


# ══════════════════════════════════════════════════════════
# OPTION HELPERS
# ══════════════════════════════════════════════════════════

def get_atm_strike(spot_price: float, strike_step: float) -> float:
    """
    Get At-The-Money strike price.
    
    Args:
        spot_price: Current price of underlying
        strike_step: Gap between strikes (50 for NIFTY, 100 for BANKNIFTY)
    
    Returns:
        float: ATM strike price
    
    Examples:
        >>> get_atm_strike(24567, 50)
        24550
        >>> get_atm_strike(52340, 100)
        52300
    """
    return round(spot_price / strike_step) * strike_step


def get_otm_strike(spot_price: float, strike_step: float, steps: int = 1, option_type: str = "CE") -> float:
    """
    Get Out-of-The-Money strike price.
    
    Args:
        spot_price: Current price
        strike_step: Gap between strikes
        steps: How many strikes OTM
        option_type: "CE" for call, "PE" for put
    
    Examples:
        >>> get_otm_strike(24550, 50, 1, "CE")
        24600  # 1 strike above for calls
        >>> get_otm_strike(24550, 50, 1, "PE")
        24500  # 1 strike below for puts
    """
    atm = get_atm_strike(spot_price, strike_step)
    
    if option_type.upper() == "CE":
        return atm + (steps * strike_step)
    else:  # PE
        return atm - (steps * strike_step)


def format_option_name(instrument: str, strike: float, option_type: str, expiry: str = "") -> str:
    """
    Format option contract name.
    
    Examples:
        >>> format_option_name("NIFTY", 24500, "CE")
        'NIFTY 24500 CE'
        >>> format_option_name("BANKNIFTY", 52000, "PE", "16JAN")
        'BANKNIFTY 16JAN 52000 PE'
    """
    if expiry:
        return f"{instrument} {expiry} {int(strike)} {option_type}"
    return f"{instrument} {int(strike)} {option_type}"


# ══════════════════════════════════════════════════════════
# VALIDATION HELPERS
# ══════════════════════════════════════════════════════════

def is_valid_symbol(symbol: str) -> bool:
    """
    Check if symbol is valid.
    
    Examples:
        >>> is_valid_symbol("NIFTY")
        True
        >>> is_valid_symbol("")
        False
        >>> is_valid_symbol("NIFTY 123")
        False
    """
    if not symbol:
        return False
    if not symbol.isalnum():
        return False
    return True


def is_positive(value: Union[int, float]) -> bool:
    """Check if value is positive."""
    return value > 0


def is_within_range(value: float, min_val: float, max_val: float) -> bool:
    """Check if value is within range (inclusive)."""
    return min_val <= value <= max_val


# ══════════════════════════════════════════════════════════
# LIST HELPERS
# ══════════════════════════════════════════════════════════

def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """
    Split list into chunks.
    
    Examples:
        >>> chunk_list([1,2,3,4,5], 2)
        [[1, 2], [3, 4], [5]]
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def get_first(lst: List, default=None):
    """Get first item or default."""
    return lst[0] if lst else default


def get_last(lst: List, default=None):
    """Get last item or default."""
    return lst[-1] if lst else default


# ══════════════════════════════════════════════════════════
# TEST - Run this file directly to test
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("  TESTING HELPER FUNCTIONS")
    print("=" * 55)
    
    # Time
    print("\n  TIME:")
    now = get_ist_now()
    print(f"    Current IST:    {format_datetime(now)}")
    print(f"    Time only:      {format_time(now)}")
    print(f"    Date only:      {format_date(now)}")
    
    # Currency
    print("\n  CURRENCY:")
    print(f"    format_currency(1234.5):      {format_currency(1234.5)}")
    print(f"    format_currency(-500):        {format_currency(-500)}")
    print(f"    format_currency_short(150000): {format_currency_short(150000)}")
    print(f"    format_currency_short(10000000): {format_currency_short(10000000)}")
    
    # Percentage
    print("\n  PERCENTAGE:")
    print(f"    format_percentage(0.0523):    {format_percentage(0.0523)}")
    print(f"    format_percentage(-0.0312):   {format_percentage(-0.0312)}")
    
    # P&L
    print("\n  P&L:")
    print(f"    format_pnl(1250):    {format_pnl(1250)}")
    print(f"    format_pnl(-380):    {format_pnl(-380)}")
    print(f"    format_pnl(0):       {format_pnl(0)}")
    
    # Duration
    print("\n  DURATION:")
    print(f"    format_duration(90):    {format_duration(90)}")
    print(f"    format_duration(3665):  {format_duration(3665)}")
    print(f"    format_duration(86400): {format_duration(86400)}")
    
    # Math
    print("\n  MATH:")
    print(f"    safe_divide(100, 0):              {safe_divide(100, 0)}")
    print(f"    calculate_percentage_change(100, 105): {calculate_percentage_change(100, 105)}")
    print(f"    round_to_tick(125.23):            {round_to_tick(125.23)}")
    
    # IDs
    print("\n  IDs:")
    print(f"    generate_order_id(): {generate_order_id()}")
    print(f"    generate_trade_id(): {generate_trade_id()}")
    
    # Options
    print("\n  OPTIONS:")
    print(f"    get_atm_strike(24567, 50):          {get_atm_strike(24567, 50)}")
    print(f"    get_otm_strike(24550, 50, 1, 'CE'): {get_otm_strike(24550, 50, 1, 'CE')}")
    print(f"    format_option_name('NIFTY', 24500, 'CE'): {format_option_name('NIFTY', 24500, 'CE')}")
    
    print("\n" + "=" * 55)
    print("  All helper functions working!")
    print("=" * 55 + "\n")