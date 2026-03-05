"""
Settings Module
===============
Loads configuration from .env file and validates all required settings.

Usage:
    from config.settings import settings
    
    print(settings.INITIAL_CAPITAL)     # 10000
    print(settings.is_paper_mode())     # True
    print(settings.WATCHLIST)           # ['NIFTY', 'BANKNIFTY']
"""

import os
import sys
from pathlib import Path
from typing import List, Optional

# Load .env file
try:
    from dotenv import load_dotenv, set_key  # ← ADDED set_key import
except ImportError:
    print("ERROR: python-dotenv not installed!")
    print("Run: pip install python-dotenv")
    sys.exit(1)


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""
    pass


class Settings:
    """
    Central configuration manager.
    
    Loads all settings from .env file and provides
    easy access throughout the application.
    """
    
    def __init__(self):
        """Initialize settings by loading .env file."""
        self._load_env()
        self._load_settings()
        self._validate()
    
    def _load_env(self):
        """Find and load the .env file."""
        # Find project root (where .env should be)
        current_dir = Path(__file__).resolve().parent.parent
        self._env_path = current_dir / '.env'  # ← CHANGED: store path for later use
        
        if self._env_path.exists():
            load_dotenv(self._env_path)
            self._env_loaded = True
        else:
            # Try current working directory
            if Path('.env').exists():
                self._env_path = Path('.env').resolve()  # ← ADDED
                load_dotenv('.env')
                self._env_loaded = True
            else:
                print("WARNING: .env file not found!")
                print(f"Expected at: {self._env_path}")
                print("Copy .env.example to .env and fill in your keys.")
                self._env_loaded = False
    
    def _load_settings(self):
        """Load all settings from environment variables."""
        
        # ══════════════════════════════════════════
        # ENVIRONMENT
        # ══════════════════════════════════════════
        self.ENVIRONMENT = self._get('ENVIRONMENT', 'development')
        self.DEBUG = self._get_bool('DEBUG', True)
        
        # ══════════════════════════════════════════
        # TRADING MODE
        # ══════════════════════════════════════════
        self.PAPER_TRADING = self._get_bool('PAPER_TRADING', True)
        self.TRADING_TYPE = self._get('TRADING_TYPE', 'OPTIONS')
        
        # ══════════════════════════════════════════
        # DHAN API
        # ══════════════════════════════════════════
        self.DHAN_CLIENT_ID = self._get('DHAN_CLIENT_ID', '')
        self.DHAN_ACCESS_TOKEN = self._get('DHAN_ACCESS_TOKEN', '')
        
        # ══════════════════════════════════════════
        # FINNHUB API
        # ══════════════════════════════════════════
        self.FINNHUB_API_KEY = self._get('FINNHUB_API_KEY', '')
        
        # ══════════════════════════════════════════
        # TELEGRAM
        # ══════════════════════════════════════════
        self.TELEGRAM_BOT_TOKEN = self._get('TELEGRAM_BOT_TOKEN', '')
        self.TELEGRAM_CHAT_ID = self._get('TELEGRAM_CHAT_ID', '')
        self.TELEGRAM_ADMIN_IDS = self._get_list('TELEGRAM_ADMIN_IDS', [])
        
        # ══════════════════════════════════════════
        # DATABASE
        # ══════════════════════════════════════════
        self.DATABASE_URL = self._get('DATABASE_URL', 'sqlite:///trading_bot.db')
        
        # ══════════════════════════════════════════
        # CAPITAL & POSITIONS
        # ══════════════════════════════════════════
        self.INITIAL_CAPITAL = self._get_float('INITIAL_CAPITAL', 10000)
        self.MAX_CAPITAL_PER_TRADE = self._get_float('MAX_CAPITAL_PER_TRADE', 2500)
        self.MAX_OPEN_POSITIONS = self._get_int('MAX_OPEN_POSITIONS', 4)
        self.MAX_TRADES_PER_DAY = self._get_int('MAX_TRADES_PER_DAY', 20)
        self.MAX_DAILY_LOSS = self._get_float('MAX_DAILY_LOSS', 0.03)
        
        # ══════════════════════════════════════════
        # OPTIONS SPECIFIC
        # ══════════════════════════════════════════
        self.OPTIONS_INSTRUMENTS = self._get_list('OPTIONS_INSTRUMENTS', ['NIFTY', 'BANKNIFTY'])
        self.NIFTY_LOT_SIZE = self._get_int('NIFTY_LOT_SIZE', 25)
        self.BANKNIFTY_LOT_SIZE = self._get_int('BANKNIFTY_LOT_SIZE', 15)
        self.MAX_LOTS_PER_TRADE = self._get_int('MAX_LOTS_PER_TRADE', 1)
        self.PREFERRED_EXPIRY = self._get('PREFERRED_EXPIRY', 'WEEKLY')
        self.PREFERRED_STRIKE = self._get('PREFERRED_STRIKE', 'ATM')
        self.MAX_PREMIUM_PER_LOT = self._get_float('MAX_PREMIUM_PER_LOT', 250)
        self.MIN_PREMIUM_PER_LOT = self._get_float('MIN_PREMIUM_PER_LOT', 20)
        self.CLOSE_BEFORE_EXPIRY_HOURS = self._get_int('CLOSE_BEFORE_EXPIRY_HOURS', 2)
        self.MAX_IV_THRESHOLD = self._get_float('MAX_IV_THRESHOLD', 30)
        
        # ══════════════════════════════════════════
        # RISK MANAGEMENT
        # ══════════════════════════════════════════
        self.STOP_LOSS_PERCENTAGE = self._get_float('STOP_LOSS_PERCENTAGE', 30.0)
        self.TAKE_PROFIT_PERCENTAGE = self._get_float('TAKE_PROFIT_PERCENTAGE', 50.0)
        self.TRAILING_STOP_PERCENTAGE = self._get_float('TRAILING_STOP_PERCENTAGE', 20.0)
        self.MAX_CONSECUTIVE_LOSSES = self._get_int('MAX_CONSECUTIVE_LOSSES', 5)
        self.CIRCUIT_BREAKER_COOLDOWN = self._get_int('CIRCUIT_BREAKER_COOLDOWN', 3600)
        
        # ══════════════════════════════════════════
        # MARKET TIMING
        # ══════════════════════════════════════════
        self.MARKET_OPEN_TIME = self._get('MARKET_OPEN_TIME', '09:15')
        self.MARKET_CLOSE_TIME = self._get('MARKET_CLOSE_TIME', '15:30')
        self.NO_NEW_TRADES_AFTER = self._get('NO_NEW_TRADES_AFTER', '14:30')
        self.CLOSE_ALL_POSITIONS_BY = self._get('CLOSE_ALL_POSITIONS_BY', '15:15')
        self.SCAN_INTERVAL = self._get_int('SCAN_INTERVAL', 30)
        
        # ══════════════════════════════════════════
        # BRAIN WEIGHTS
        # ══════════════════════════════════════════
        self.BRAIN_WEIGHT_TECHNICAL = self._get_float('BRAIN_WEIGHT_TECHNICAL', 0.40)
        self.BRAIN_WEIGHT_SENTIMENT = self._get_float('BRAIN_WEIGHT_SENTIMENT', 0.35)
        self.BRAIN_WEIGHT_PATTERN = self._get_float('BRAIN_WEIGHT_PATTERN', 0.25)
        
        # ══════════════════════════════════════════
        # LOGGING
        # ══════════════════════════════════════════
        self.LOG_LEVEL = self._get('LOG_LEVEL', 'INFO')
        self.LOG_TO_FILE = self._get_bool('LOG_TO_FILE', True)
        self.LOG_FILE_PATH = self._get('LOG_FILE_PATH', 'logs/bot.log')
    
    # ══════════════════════════════════════════════════════
    # HELPER METHODS - Get values from environment
    # ══════════════════════════════════════════════════════
    
    def _get(self, key: str, default: str = '') -> str:
        """Get string value from environment."""
        return os.getenv(key, default)
    
    def _get_bool(self, key: str, default: bool = False) -> bool:
        """Get boolean value from environment."""
        value = os.getenv(key, str(default)).lower()
        return value in ('true', '1', 'yes', 'on')
    
    def _get_int(self, key: str, default: int = 0) -> int:
        """Get integer value from environment."""
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default
    
    def _get_float(self, key: str, default: float = 0.0) -> float:
        """Get float value from environment."""
        try:
            return float(os.getenv(key, str(default)))
        except ValueError:
            return default
    
    def _get_list(self, key: str, default: List[str] = None) -> List[str]:
        """Get list value from environment (comma separated)."""
        if default is None:
            default = []
        value = os.getenv(key, '')
        if not value:
            return default
        return [item.strip() for item in value.split(',') if item.strip()]
    
    # ══════════════════════════════════════════════════════
    # VALIDATION
    # ══════════════════════════════════════════════════════
    
    def _validate(self):
        """Validate critical settings."""
        errors = []
        
        # Check if .env exists
        if not self._env_loaded:
            errors.append(".env file not found")
        
        # In production/live mode, require API keys
        if not self.PAPER_TRADING:
            if not self.DHAN_CLIENT_ID:
                errors.append("DHAN_CLIENT_ID is required for live trading")
            if not self.DHAN_ACCESS_TOKEN:
                errors.append("DHAN_ACCESS_TOKEN is required for live trading")
        
        # Validate brain weights sum to 1.0
        total_weight = (
            self.BRAIN_WEIGHT_TECHNICAL +
            self.BRAIN_WEIGHT_SENTIMENT +
            self.BRAIN_WEIGHT_PATTERN
        )
        if abs(total_weight - 1.0) > 0.01:
            errors.append(f"Brain weights must sum to 1.0, got {total_weight}")
        
        # Validate risk settings
        if self.STOP_LOSS_PERCENTAGE <= 0:
            errors.append("STOP_LOSS_PERCENTAGE must be positive")
        
        if self.TAKE_PROFIT_PERCENTAGE <= 0:
            errors.append("TAKE_PROFIT_PERCENTAGE must be positive")
        
        if self.INITIAL_CAPITAL <= 0:
            errors.append("INITIAL_CAPITAL must be positive")
        
        # Show errors but don't crash (for development)
        if errors and self.ENVIRONMENT == 'production':
            for error in errors:
                print(f"CONFIG ERROR: {error}")
            raise ConfigError("Configuration validation failed")
        elif errors:
            for error in errors:
                print(f"CONFIG WARNING: {error}")
    
    # ══════════════════════════════════════════════════════
    # CONVENIENCE METHODS
    # ══════════════════════════════════════════════════════
    
    def is_paper_mode(self) -> bool:
        """Check if running in paper trading mode."""
        return self.PAPER_TRADING
    
    def is_live_mode(self) -> bool:
        """Check if running in live trading mode."""
        return not self.PAPER_TRADING
    
    def is_debug(self) -> bool:
        """Check if debug mode is enabled."""
        return self.DEBUG
    
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENVIRONMENT == 'production'
    
    def get_lot_size(self, instrument: str) -> int:
        """Get lot size for an instrument."""
        if instrument.upper() == 'NIFTY':
            return self.NIFTY_LOT_SIZE
        elif instrument.upper() == 'BANKNIFTY':
            return self.BANKNIFTY_LOT_SIZE
        else:
            return 1
    
    # ══════════════════════════════════════════════════════
    # TOKEN UPDATE METHODS (NEW - for Telegram /set_token)
    # ══════════════════════════════════════════════════════
    
    def update_dhan_token(self, new_token: str) -> bool:
        """
        Update Dhan access token in 3 places:
        1. In memory (current running session)
        2. In os.environ (current process)
        3. In .env file (survives restart)
        
        Args:
            new_token: The new Dhan access token
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not new_token or not new_token.strip():
                raise ValueError("Token cannot be empty")
            
            new_token = new_token.strip()
            
            # 1. Update in memory
            self.DHAN_ACCESS_TOKEN = new_token
            
            # 2. Update environment variable
            os.environ["DHAN_ACCESS_TOKEN"] = new_token
            
            # 3. Update .env file (persists across restarts)
            if self._env_path and self._env_path.exists():
                set_key(str(self._env_path), "DHAN_ACCESS_TOKEN", new_token)
            
            return True
            
        except Exception as e:
            print(f"[Settings] Failed to update token: {e}")
            return False
    
    def get_masked_token(self) -> str:
        """
        Return masked token for safe display.
        Example: 'eyJ0eX...k4Mg'
        """
        token = self.DHAN_ACCESS_TOKEN
        if not token or len(token) < 10:
            return "NOT SET"
        return f"{token[:6]}...{token[-4:]}"
    
    def print_config(self):
        """Print current configuration (hide sensitive data)."""
        print("\n" + "=" * 55)
        print("  TRADING BOT CONFIGURATION")
        print("=" * 55)
        
        print(f"\n  Environment:     {self.ENVIRONMENT}")
        print(f"  Debug:           {self.DEBUG}")
        print(f"  Trading Mode:    {'PAPER' if self.PAPER_TRADING else 'LIVE'}")
        print(f"  Trading Type:    {self.TRADING_TYPE}")
        
        print(f"\n  Capital:         Rs.{self.INITIAL_CAPITAL:,.0f}")
        print(f"  Per Trade:       Rs.{self.MAX_CAPITAL_PER_TRADE:,.0f}")
        print(f"  Max Positions:   {self.MAX_OPEN_POSITIONS}")
        print(f"  Max Trades/Day:  {self.MAX_TRADES_PER_DAY}")
        
        print(f"\n  Instruments:     {', '.join(self.OPTIONS_INSTRUMENTS)}")
        print(f"  NIFTY Lot:       {self.NIFTY_LOT_SIZE}")
        print(f"  BANKNIFTY Lot:   {self.BANKNIFTY_LOT_SIZE}")
        print(f"  Max Lots:        {self.MAX_LOTS_PER_TRADE}")
        
        print(f"\n  Stop Loss:       {self.STOP_LOSS_PERCENTAGE}%")
        print(f"  Take Profit:     {self.TAKE_PROFIT_PERCENTAGE}%")
        print(f"  Max Daily Loss:  {self.MAX_DAILY_LOSS * 100}%")
        
        print(f"\n  Market Open:     {self.MARKET_OPEN_TIME}")
        print(f"  Market Close:    {self.MARKET_CLOSE_TIME}")
        print(f"  Scan Interval:   {self.SCAN_INTERVAL} seconds")
        
        # API Keys (show if present, not the actual values)
        print(f"\n  Dhan API:        {'Configured' if self.DHAN_CLIENT_ID else 'NOT SET'}")
        print(f"  Dhan Token:      {self.get_masked_token()}")  # ← CHANGED: uses masked token
        print(f"  Finnhub API:     {'Configured' if self.FINNHUB_API_KEY else 'NOT SET'}")
        print(f"  Telegram Bot:    {'Configured' if self.TELEGRAM_BOT_TOKEN else 'NOT SET'}")
        
        print("\n" + "=" * 55)


# ══════════════════════════════════════════════════════════
# GLOBAL SETTINGS INSTANCE
# ══════════════════════════════════════════════════════════
# Create a single instance that the entire app uses

settings = Settings()


# ══════════════════════════════════════════════════════════
# TEST - Run this file directly to test
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\nTesting settings.py...")
    
    # Print all config
    settings.print_config()
    
    # Test convenience methods
    print(f"\n  Paper Mode:      {settings.is_paper_mode()}")
    print(f"  NIFTY Lot Size:  {settings.get_lot_size('NIFTY')}")
    
    # Test new token methods
    print(f"  Masked Token:    {settings.get_masked_token()}")
    
    print("\n  Settings loaded successfully!")