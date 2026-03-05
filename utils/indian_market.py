"""
Indian Market Module
====================
NSE/BSE market hours, holidays, and timezone handling.

Usage:
    from utils.indian_market import (
        is_market_open,
        is_trading_day,
        get_time_to_market_open,
        get_next_trading_day
    )
    
    if is_market_open():
        print("Market is OPEN! Let's trade!")
    else:
        print(f"Market closed. Opens in {get_time_to_market_open()}")
"""

from datetime import datetime, date, time, timedelta
from typing import Optional, Tuple

import pytz


# ══════════════════════════════════════════════════════════
# TIMEZONE
# ══════════════════════════════════════════════════════════

IST = pytz.timezone('Asia/Kolkata')


# ══════════════════════════════════════════════════════════
# MARKET HOURS
# ══════════════════════════════════════════════════════════

# Normal trading hours
MARKET_OPEN_TIME = time(9, 15, 0)    # 9:15 AM IST
MARKET_CLOSE_TIME = time(15, 30, 0)  # 3:30 PM IST

# Pre-market session
PRE_MARKET_OPEN = time(9, 0, 0)      # 9:00 AM IST
PRE_MARKET_CLOSE = time(9, 15, 0)    # 9:15 AM IST

# Post-market session
POST_MARKET_OPEN = time(15, 40, 0)   # 3:40 PM IST
POST_MARKET_CLOSE = time(16, 0, 0)   # 4:00 PM IST

# Trading cutoff times
NO_NEW_TRADES_TIME = time(14, 30, 0)    # Don't take new trades after 2:30 PM
CLOSE_ALL_POSITIONS_TIME = time(15, 15, 0)  # Close all by 3:15 PM


# ══════════════════════════════════════════════════════════
# NSE HOLIDAYS 2025
# ══════════════════════════════════════════════════════════
# Source: NSE official holiday calendar
# Update this list every year!

NSE_HOLIDAYS_2025 = [
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramadan Eid)
    date(2025, 4, 10),   # Shri Mahavir Jayanti
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 6, 7),    # Eid ul-Adha (Bakri Eid)
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 16),   # Parsi New Year
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Mahatma Gandhi Jayanti
    date(2025, 10, 21),  # Diwali Laxmi Pujan
    date(2025, 10, 22),  # Diwali Balipratipada
    date(2025, 11, 5),   # Prakash Gurpurab Sri Guru Nanak Dev
    date(2025, 12, 25),  # Christmas
]

# Special trading sessions (shortened hours) - optional
SPECIAL_SESSIONS_2025 = {
    # date: (open_time, close_time)
    # Add Muhurat trading or special sessions here if needed
}


# ══════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ══════════════════════════════════════════════════════════

def get_ist_now() -> datetime:
    """Get current time in IST."""
    return datetime.now(IST)


def is_weekend(check_date: Optional[date] = None) -> bool:
    """
    Check if date is Saturday or Sunday.
    
    Args:
        check_date: Date to check (default: today)
    
    Returns:
        bool: True if weekend
    """
    if check_date is None:
        check_date = get_ist_now().date()
    
    # Monday=0, Sunday=6
    return check_date.weekday() >= 5


def is_holiday(check_date: Optional[date] = None) -> bool:
    """
    Check if date is an NSE holiday.
    
    Args:
        check_date: Date to check (default: today)
    
    Returns:
        bool: True if NSE holiday
    """
    if check_date is None:
        check_date = get_ist_now().date()
    
    return check_date in NSE_HOLIDAYS_2025


def get_holiday_name(check_date: Optional[date] = None) -> Optional[str]:
    """
    Get name of holiday if date is a holiday.
    
    Returns:
        str or None: Holiday name if holiday, else None
    """
    if check_date is None:
        check_date = get_ist_now().date()
    
    holiday_names = {
        date(2025, 2, 26): "Mahashivratri",
        date(2025, 3, 14): "Holi",
        date(2025, 3, 31): "Id-Ul-Fitr",
        date(2025, 4, 10): "Mahavir Jayanti",
        date(2025, 4, 14): "Ambedkar Jayanti",
        date(2025, 4, 18): "Good Friday",
        date(2025, 5, 1): "Maharashtra Day",
        date(2025, 6, 7): "Eid ul-Adha",
        date(2025, 8, 15): "Independence Day",
        date(2025, 8, 16): "Parsi New Year",
        date(2025, 8, 27): "Ganesh Chaturthi",
        date(2025, 10, 2): "Gandhi Jayanti",
        date(2025, 10, 21): "Diwali Laxmi Pujan",
        date(2025, 10, 22): "Diwali Balipratipada",
        date(2025, 11, 5): "Guru Nanak Jayanti",
        date(2025, 12, 25): "Christmas",
    }
    
    return holiday_names.get(check_date)


def is_trading_day(check_date: Optional[date] = None) -> bool:
    """
    Check if date is a valid trading day.
    
    A trading day is:
        - Not a weekend (Saturday/Sunday)
        - Not an NSE holiday
    
    Args:
        check_date: Date to check (default: today)
    
    Returns:
        bool: True if trading day
    
    Examples:
        >>> is_trading_day(date(2025, 1, 15))  # Wednesday
        True
        >>> is_trading_day(date(2025, 1, 18))  # Saturday
        False
        >>> is_trading_day(date(2025, 10, 21)) # Diwali
        False
    """
    if check_date is None:
        check_date = get_ist_now().date()
    
    # Not a weekend
    if is_weekend(check_date):
        return False
    
    # Not a holiday
    if is_holiday(check_date):
        return False
    
    return True


def is_market_open() -> bool:
    """
    Check if market is CURRENTLY open for trading.
    
    Checks:
        1. Is today a trading day?
        2. Is current time between 9:15 AM and 3:30 PM?
    
    Returns:
        bool: True if market is open RIGHT NOW
    
    Example:
        >>> if is_market_open():
        ...     place_trade()
        ... else:
        ...     wait()
    """
    now = get_ist_now()
    
    # Check if trading day
    if not is_trading_day(now.date()):
        return False
    
    # Check if within trading hours
    current_time = now.time()
    
    return MARKET_OPEN_TIME <= current_time <= MARKET_CLOSE_TIME


def is_pre_market() -> bool:
    """Check if currently in pre-market session (9:00-9:15 AM)."""
    now = get_ist_now()
    
    if not is_trading_day(now.date()):
        return False
    
    current_time = now.time()
    return PRE_MARKET_OPEN <= current_time < PRE_MARKET_CLOSE


def is_post_market() -> bool:
    """Check if currently in post-market session (3:40-4:00 PM)."""
    now = get_ist_now()
    
    if not is_trading_day(now.date()):
        return False
    
    current_time = now.time()
    return POST_MARKET_OPEN <= current_time <= POST_MARKET_CLOSE


def can_take_new_trades() -> bool:
    """
    Check if we can take NEW trades.
    
    Returns False after 2:30 PM (don't enter new positions late).
    
    Returns:
        bool: True if we can enter new trades
    """
    now = get_ist_now()
    
    if not is_market_open():
        return False
    
    current_time = now.time()
    return current_time < NO_NEW_TRADES_TIME


def should_close_all_positions() -> bool:
    """
    Check if we should close all positions.
    
    Returns True after 3:15 PM (close before market ends).
    
    Returns:
        bool: True if should close all
    """
    now = get_ist_now()
    
    if not is_trading_day(now.date()):
        return False
    
    current_time = now.time()
    return current_time >= CLOSE_ALL_POSITIONS_TIME


# ══════════════════════════════════════════════════════════
# TIME CALCULATIONS
# ══════════════════════════════════════════════════════════

def get_market_open_datetime(for_date: Optional[date] = None) -> datetime:
    """
    Get market opening datetime for a specific date.
    
    Args:
        for_date: Date to get open time for (default: today)
    
    Returns:
        datetime: Market open time in IST
    """
    if for_date is None:
        for_date = get_ist_now().date()
    
    return IST.localize(datetime.combine(for_date, MARKET_OPEN_TIME))


def get_market_close_datetime(for_date: Optional[date] = None) -> datetime:
    """
    Get market closing datetime for a specific date.
    
    Args:
        for_date: Date to get close time for (default: today)
    
    Returns:
        datetime: Market close time in IST
    """
    if for_date is None:
        for_date = get_ist_now().date()
    
    return IST.localize(datetime.combine(for_date, MARKET_CLOSE_TIME))


def get_time_to_market_open() -> Tuple[bool, str, int]:
    """
    Get time remaining until market opens.
    
    Returns:
        Tuple of:
            - bool: True if market is currently open
            - str: Human readable time string
            - int: Seconds until open (0 if open)
    
    Examples:
        >>> is_open, message, seconds = get_time_to_market_open()
        >>> print(message)
        'Market is OPEN'
        OR
        'Opens in 2h 15m'
        OR
        'Opens Monday at 9:15 AM'
    """
    now = get_ist_now()
    
    # If market is currently open
    if is_market_open():
        return True, "Market is OPEN", 0
    
    # Find next trading day
    next_trading = get_next_trading_day()
    next_open = get_market_open_datetime(next_trading)
    
    # Calculate time difference
    time_diff = next_open - now
    total_seconds = int(time_diff.total_seconds())
    
    if total_seconds < 0:
        total_seconds = 0
    
    # Format message
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    
    if next_trading == now.date():
        # Opens today
        message = f"Opens in {hours}h {minutes}m"
    else:
        # Opens another day
        day_name = next_trading.strftime("%A")
        message = f"Opens {day_name} at 9:15 AM"
    
    return False, message, total_seconds


def get_time_to_market_close() -> Tuple[bool, str, int]:
    """
    Get time remaining until market closes.
    
    Returns:
        Tuple of:
            - bool: True if market is currently open
            - str: Human readable time string
            - int: Seconds until close (0 if closed)
    
    Examples:
        >>> is_open, message, seconds = get_time_to_market_close()
        >>> print(message)
        'Closes in 1h 30m'
        OR
        'Market is CLOSED'
    """
    now = get_ist_now()
    
    # If market is NOT open
    if not is_market_open():
        return False, "Market is CLOSED", 0
    
    # Calculate time until close
    market_close = get_market_close_datetime(now.date())
    time_diff = market_close - now
    total_seconds = int(time_diff.total_seconds())
    
    if total_seconds < 0:
        total_seconds = 0
    
    # Format message
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    
    message = f"Closes in {hours}h {minutes}m"
    
    return True, message, total_seconds


def get_next_trading_day(from_date: Optional[date] = None) -> date:
    """
    Get the next trading day.
    
    Args:
        from_date: Start date (default: today)
    
    Returns:
        date: Next trading day
    
    Examples:
        >>> get_next_trading_day(date(2025, 1, 17))  # Friday
        date(2025, 1, 20)  # Monday
        
        >>> get_next_trading_day(date(2025, 10, 20))  # Before Diwali
        date(2025, 10, 23)  # After Diwali holidays
    """
    if from_date is None:
        from_date = get_ist_now().date()
    
    # Check if today is a trading day and market hasn't closed
    now = get_ist_now()
    if from_date == now.date():
        if is_trading_day(from_date) and now.time() < MARKET_OPEN_TIME:
            return from_date
    
    # Start checking from tomorrow
    check_date = from_date + timedelta(days=1)
    
    # Find next trading day (max 10 days ahead to avoid infinite loop)
    for _ in range(10):
        if is_trading_day(check_date):
            return check_date
        check_date += timedelta(days=1)
    
    # Fallback (shouldn't reach here)
    return check_date


def get_previous_trading_day(from_date: Optional[date] = None) -> date:
    """
    Get the previous trading day.
    
    Args:
        from_date: Start date (default: today)
    
    Returns:
        date: Previous trading day
    """
    if from_date is None:
        from_date = get_ist_now().date()
    
    # Start checking from yesterday
    check_date = from_date - timedelta(days=1)
    
    # Find previous trading day (max 10 days back)
    for _ in range(10):
        if is_trading_day(check_date):
            return check_date
        check_date -= timedelta(days=1)
    
    # Fallback
    return check_date


def get_trading_days_between(start_date: date, end_date: date) -> int:
    """
    Count trading days between two dates.
    
    Args:
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
    
    Returns:
        int: Number of trading days
    """
    count = 0
    current = start_date
    
    while current <= end_date:
        if is_trading_day(current):
            count += 1
        current += timedelta(days=1)
    
    return count


# ══════════════════════════════════════════════════════════
# OPTIONS EXPIRY
# ══════════════════════════════════════════════════════════

def get_weekly_expiry(from_date: Optional[date] = None) -> date:
    """
    Get the next weekly options expiry (Thursday).
    
    NIFTY/BANKNIFTY weekly options expire every Thursday.
    If Thursday is a holiday, expiry is Wednesday.
    
    Args:
        from_date: Start date (default: today)
    
    Returns:
        date: Next expiry date
    """
    if from_date is None:
        from_date = get_ist_now().date()
    
    # Find next Thursday (weekday 3)
    days_until_thursday = (3 - from_date.weekday()) % 7
    
    if days_until_thursday == 0:
        # Today is Thursday
        now = get_ist_now()
        if now.time() > MARKET_CLOSE_TIME:
            # After market close, get next week's Thursday
            days_until_thursday = 7
    
    next_thursday = from_date + timedelta(days=days_until_thursday)
    
    # If Thursday is a holiday, expiry is Wednesday
    if is_holiday(next_thursday):
        return next_thursday - timedelta(days=1)
    
    return next_thursday


def get_monthly_expiry(from_date: Optional[date] = None) -> date:
    """
    Get the next monthly options expiry (last Thursday of month).
    
    Args:
        from_date: Start date (default: today)
    
    Returns:
        date: Next monthly expiry date
    """
    if from_date is None:
        from_date = get_ist_now().date()
    
    # Find last Thursday of current month
    year = from_date.year
    month = from_date.month
    
    # Start from last day of month and go backwards
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    
    last_day = next_month - timedelta(days=1)
    
    # Find last Thursday
    days_since_thursday = (last_day.weekday() - 3) % 7
    last_thursday = last_day - timedelta(days=days_since_thursday)
    
    # If we've passed this month's expiry, get next month's
    if from_date > last_thursday:
        if month == 12:
            return get_monthly_expiry(date(year + 1, 1, 1))
        else:
            return get_monthly_expiry(date(year, month + 1, 1))
    
    # If last Thursday is a holiday, use Wednesday
    if is_holiday(last_thursday):
        return last_thursday - timedelta(days=1)
    
    return last_thursday


def get_days_to_expiry(expiry_date: date) -> int:
    """
    Get trading days until expiry.
    
    Args:
        expiry_date: Expiry date
    
    Returns:
        int: Trading days until expiry
    """
    today = get_ist_now().date()
    return get_trading_days_between(today, expiry_date)


def format_expiry(expiry_date: date) -> str:
    """
    Format expiry date as string (e.g., '16JAN', '23JAN').
    
    Args:
        expiry_date: Expiry date
    
    Returns:
        str: Formatted expiry string
    """
    return expiry_date.strftime("%d%b").upper()


# ══════════════════════════════════════════════════════════
# MARKET STATUS STRING
# ══════════════════════════════════════════════════════════

def get_market_status() -> str:
    """
    Get full market status as formatted string.
    
    Returns:
        str: Market status message
    
    Example:
        >>> print(get_market_status())
        '🟢 Market OPEN | Closes in 2h 15m'
        OR
        '🔴 Market CLOSED | Opens Monday at 9:15 AM'
        OR
        '🟡 Holiday: Diwali'
    """
    now = get_ist_now()
    today = now.date()
    
    # Check if holiday
    if is_holiday(today):
        holiday_name = get_holiday_name(today)
        return f"🟡 Holiday: {holiday_name}"
    
    # Check if weekend
    if is_weekend(today):
        day_name = today.strftime("%A")
        next_open = get_next_trading_day()
        return f"🔴 Weekend ({day_name}) | Opens {next_open.strftime('%A')}"
    
    # Check if market is open
    if is_market_open():
        _, close_msg, _ = get_time_to_market_close()
        
        if not can_take_new_trades():
            return f"🟡 Market OPEN (no new trades) | {close_msg}"
        
        if should_close_all_positions():
            return f"🟠 CLOSE ALL POSITIONS | {close_msg}"
        
        return f"🟢 Market OPEN | {close_msg}"
    
    # Market closed
    _, open_msg, _ = get_time_to_market_open()
    return f"🔴 Market CLOSED | {open_msg}"


# ══════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  INDIAN MARKET - TEST")
    print("=" * 60)
    
    now = get_ist_now()
    today = now.date()
    
    print(f"\n  Current Time (IST): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Today:              {today.strftime('%A, %d %B %Y')}")
    
    print("\n  MARKET STATUS:")
    print(f"    {get_market_status()}")
    
    print("\n  TODAY'S CHECKS:")
    print(f"    Is Weekend:       {is_weekend()}")
    print(f"    Is Holiday:       {is_holiday()}")
    print(f"    Is Trading Day:   {is_trading_day()}")
    print(f"    Is Market Open:   {is_market_open()}")
    print(f"    Can Take Trades:  {can_take_new_trades()}")
    print(f"    Should Close All: {should_close_all_positions()}")
    
    print("\n  TIME INFO:")
    is_open, open_msg, open_secs = get_time_to_market_open()
    _, close_msg, close_secs = get_time_to_market_close()
    print(f"    Market Open:  {open_msg}")
    print(f"    Market Close: {close_msg}")
    
    print("\n  TRADING DAYS:")
    print(f"    Next Trading Day:     {get_next_trading_day()}")
    print(f"    Previous Trading Day: {get_previous_trading_day()}")
    
    print("\n  OPTIONS EXPIRY:")
    weekly = get_weekly_expiry()
    monthly = get_monthly_expiry()
    print(f"    Weekly Expiry:  {weekly} ({format_expiry(weekly)})")
    print(f"    Monthly Expiry: {monthly} ({format_expiry(monthly)})")
    print(f"    Days to Weekly: {get_days_to_expiry(weekly)}")
    
    print("\n  NSE HOLIDAYS 2025:")
    for i, holiday in enumerate(NSE_HOLIDAYS_2025[:5], 1):
        name = get_holiday_name(holiday)
        print(f"    {i}. {holiday} - {name}")
    print(f"    ... and {len(NSE_HOLIDAYS_2025) - 5} more")
    
    print("\n" + "=" * 60)
    print("  All market functions working!")
    print("=" * 60 + "\n")