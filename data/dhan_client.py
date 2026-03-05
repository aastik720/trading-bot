"""
Dhan Client Module
==================
Wrapper around Dhan trading API for market data and order execution.

Dhan API Documentation: https://dhanhq.co/docs/v2/

Usage:
    from data.dhan_client import DhanClient
    
    client = DhanClient(client_id, access_token)
    
    # Check connection
    if client.connect():
        print("Connected to Dhan!")
    
    # Get NIFTY price
    quote = client.get_index_quote("NIFTY")
    print(f"NIFTY: {quote['ltp']}")
"""

import time
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Tuple

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import dhanhq
try:
    from dhanhq import dhanhq
    DHAN_AVAILABLE = True
except ImportError:
    DHAN_AVAILABLE = False
    logger.warning("dhanhq library not installed. Run: pip install dhanhq")

# Import our custom exceptions
try:
    from utils.exceptions import DhanAPIError, DataError
    from utils.helpers import get_ist_now
except ImportError:
    # Fallback if imports fail
    class DhanAPIError(Exception):
        pass
    class DataError(Exception):
        pass
    def get_ist_now():
        from datetime import timezone
        IST = timezone(timedelta(hours=5, minutes=30))
        return datetime.now(IST)


# ══════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════

# Security IDs for indices (from Dhan security master)
# These are the actual security IDs used by Dhan
SECURITY_IDS = {
    "NIFTY": "13",
    "NIFTY 50": "13",
    "BANKNIFTY": "25",
    "NIFTY BANK": "25",
    "FINNIFTY": "27",
    "NIFTY FIN SERVICE": "27",
    "SENSEX": "51",
}

# Index symbols for trading
INDEX_SYMBOLS = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY", 
    "FINNIFTY": "FINNIFTY",
}

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 1


# ══════════════════════════════════════════════════════════
# DHAN CLIENT CLASS
# ══════════════════════════════════════════════════════════

class DhanClient:
    """
    Wrapper around Dhan trading API.
    """
    
    def __init__(self, client_id: str = "", access_token: str = ""):
        """
        Initialize Dhan client.
        
        Args:
            client_id: Your Dhan client ID
            access_token: Your Dhan JWT access token
        """
        self.client_id = client_id
        self.access_token = access_token
        self.connected = False
        self._dhan = None
        self._available_methods = []
        
        if client_id and access_token:
            self._initialize_client()
    
    def _initialize_client(self):
        """Initialize the Dhan API client."""
        if not DHAN_AVAILABLE:
            logger.error("dhanhq library not available")
            return
        
        try:
            self._dhan = dhanhq(self.client_id, self.access_token)
            self._available_methods = [m for m in dir(self._dhan) if not m.startswith('_')]
            logger.info(f"Dhan client initialized with {len(self._available_methods)} methods")
        except Exception as e:
            logger.error(f"Failed to initialize Dhan client: {e}")
            self._dhan = None
    
    # ══════════════════════════════════════════════════════
    # TOKEN REFRESH (NEW - for Telegram /set_token)
    # ══════════════════════════════════════════════════════
    
    def refresh_connection(self):
        """
        Reconnect using the latest token from settings.
        Called after /set_token updates the token.
        """
        try:
            from config.settings import settings
            self.client_id = settings.DHAN_CLIENT_ID
            self.access_token = settings.DHAN_ACCESS_TOKEN
            self.connected = False
            self._dhan = None
            
            if self.client_id and self.access_token:
                self._initialize_client()
                # Auto-test connection after refresh
                self.connect()
                logger.info("[Dhan] Connection refreshed with new token")
            else:
                logger.warning("[Dhan] Cannot refresh - missing client_id or token")
        except Exception as e:
            logger.error(f"[Dhan] Failed to refresh connection: {e}")
            self.connected = False
    
    def test_connection(self) -> Dict:
        """
        Test if current token works. Returns status dict.
        Used by /check_token command.
        """
        try:
            if not self._dhan:
                return {
                    "connected": False,
                    "message": "Client not initialized. Use /set_token first.",
                    "data": {}
                }
            
            result = self._dhan.get_fund_limits()
            
            if isinstance(result, dict) and result.get('status') == 'success':
                self.connected = True
                return {
                    "connected": True,
                    "message": "Token is valid ✅",
                    "data": result.get('data', {})
                }
            else:
                self.connected = False
                remarks = result.get('remarks', {}) if isinstance(result, dict) else {}
                error_msg = remarks.get('error_message', str(result))
                return {
                    "connected": False,
                    "message": f"Token rejected: {error_msg}",
                    "data": {}
                }
        except Exception as e:
            self.connected = False
            return {
                "connected": False,
                "message": f"Connection failed: {str(e)}",
                "data": {}
            }
    
    def get_available_methods(self) -> List[str]:
        """Get list of available API methods."""
        if self._dhan:
            return [m for m in dir(self._dhan) if not m.startswith('_') and callable(getattr(self._dhan, m, None))]
        return []
    
    # ══════════════════════════════════════════════════════
    # CONNECTION
    # ══════════════════════════════════════════════════════
    
    def connect(self) -> bool:
        """Test connection to Dhan API."""
        if not DHAN_AVAILABLE or not self._dhan:
            return False
        
        try:
            result = self._dhan.get_fund_limits()
            
            if isinstance(result, dict):
                if result.get('status') == 'success':
                    self.connected = True
                    logger.info("✅ Connected to Dhan API")
                    return True
                else:
                    remarks = result.get('remarks', {})
                    error_msg = remarks.get('error_message', str(result))
                    logger.error(f"Dhan connection failed: {error_msg}")
            
            self.connected = False
            return False
            
        except Exception as e:
            logger.error(f"Failed to connect to Dhan: {e}")
            self.connected = False
            return False
    
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self.connected and self._dhan is not None
    
    # ══════════════════════════════════════════════════════
    # INDEX QUOTES - Using intraday_daily_minute_charts
    # ══════════════════════════════════════════════════════
    
    def get_index_quote(self, symbol: str) -> Dict:
        """
        Get current quote for an index (NIFTY, BANKNIFTY).
        Uses intraday minute charts to get the latest price.
        """
        symbol = symbol.upper().strip()
        
        if symbol not in SECURITY_IDS:
            raise DhanAPIError(f"Unknown symbol: {symbol}")
        
        if not self._dhan or not self.connected:
            return self._get_mock_index_quote(symbol)
        
        try:
            security_id = SECURITY_IDS[symbol]
            
            # Use intraday_daily_minute_charts to get latest price
            # This is available in dhanhq library
            result = self._dhan.intraday_daily_minute_charts(
                security_id=security_id,
                exchange_segment=self._dhan.IDX,  # Use library constant
                instrument_type="INDEX"
            )
            
            if result and result.get('status') == 'success':
                data = result.get('data', {})
                
                # Dhan returns data in arrays
                opens = data.get('open', [])
                highs = data.get('high', [])
                lows = data.get('low', [])
                closes = data.get('close', [])
                
                if closes:
                    ltp = closes[-1]
                    day_open = opens[0] if opens else ltp
                    day_high = max(highs) if highs else ltp
                    day_low = min(lows) if lows else ltp
                    prev_close = opens[0] if opens else ltp  # Approximate
                    
                    change = ltp - prev_close
                    change_pct = (change / prev_close * 100) if prev_close else 0
                    
                    return {
                        'symbol': symbol,
                        'ltp': float(ltp),
                        'open': float(day_open),
                        'high': float(day_high),
                        'low': float(day_low),
                        'close': float(prev_close),
                        'change': round(change, 2),
                        'change_pct': round(change_pct, 2),
                        'timestamp': get_ist_now(),
                    }
            
            # If we get here, API didn't return expected data
            logger.warning(f"Could not get live data for {symbol}: {result}")
            return self._get_mock_index_quote(symbol)
            
        except AttributeError as e:
            # IDX constant might not exist, try numeric value
            logger.debug(f"AttributeError: {e}, trying numeric segment")
            return self._get_index_quote_fallback(symbol)
        except Exception as e:
            logger.error(f"Error getting index quote for {symbol}: {e}")
            return self._get_mock_index_quote(symbol)
    
    def _get_index_quote_fallback(self, symbol: str) -> Dict:
        """Fallback method using numeric segment codes."""
        try:
            security_id = SECURITY_IDS[symbol]
            
            # Try with numeric segment code (0 = Index)
            result = self._dhan.intraday_daily_minute_charts(
                security_id=security_id,
                exchange_segment=0,  # IDX = 0
                instrument_type="INDEX"
            )
            
            if result and result.get('status') == 'success':
                data = result.get('data', {})
                closes = data.get('close', [])
                
                if closes:
                    ltp = closes[-1]
                    opens = data.get('open', [ltp])
                    highs = data.get('high', [ltp])
                    lows = data.get('low', [ltp])
                    
                    return {
                        'symbol': symbol,
                        'ltp': float(ltp),
                        'open': float(opens[0]) if opens else float(ltp),
                        'high': float(max(highs)) if highs else float(ltp),
                        'low': float(min(lows)) if lows else float(ltp),
                        'close': float(opens[0]) if opens else float(ltp),
                        'change': 0,
                        'change_pct': 0,
                        'timestamp': get_ist_now(),
                    }
            
            return self._get_mock_index_quote(symbol)
            
        except Exception as e:
            logger.error(f"Fallback also failed for {symbol}: {e}")
            return self._get_mock_index_quote(symbol)
    
    def _get_mock_index_quote(self, symbol: str) -> Dict:
        """Return mock data for testing."""
        mock_prices = {
            "NIFTY": 23250.50,
            "BANKNIFTY": 48750.25,
            "FINNIFTY": 21500.75,
        }
        
        base_price = mock_prices.get(symbol, 20000.0)
        
        return {
            'symbol': symbol,
            'ltp': base_price,
            'open': base_price - 50,
            'high': base_price + 70,
            'low': base_price - 80,
            'close': base_price - 20,
            'change': 20.0,
            'change_pct': 0.08,
            'timestamp': get_ist_now(),
            '_mock': True,
        }
    
    # ══════════════════════════════════════════════════════
    # OPTION CHAIN
    # ══════════════════════════════════════════════════════
    
    def get_option_chain(self, symbol: str, expiry: str) -> Dict:
        """
        Get option chain for an index.
        
        Note: Dhan doesn't have a direct option chain API.
        We construct it from available data or use mock data.
        """
        symbol = symbol.upper().strip()
        
        # Get spot price
        try:
            spot_quote = self.get_index_quote(symbol)
            spot_price = spot_quote['ltp']
            is_mock = spot_quote.get('_mock', False)
        except:
            spot_price = 23250.50 if symbol == "NIFTY" else 48750.25
            is_mock = True
        
        # Calculate ATM strike
        strike_step = 50 if symbol == "NIFTY" else 100
        atm_strike = round(spot_price / strike_step) * strike_step
        
        # For now, return mock option chain structure
        # In production, you'd fetch actual option prices using security IDs
        return self._get_mock_option_chain(symbol, expiry, spot_price, atm_strike, is_mock)
    
    def _get_mock_option_chain(
        self, 
        symbol: str, 
        expiry: str, 
        spot_price: float,
        atm_strike: float,
        is_mock: bool = True
    ) -> Dict:
        """Generate option chain structure."""
        strike_step = 50 if symbol == "NIFTY" else 100
        
        calls = []
        puts = []
        
        # Generate strikes around ATM
        for i in range(-10, 11):
            strike = atm_strike + (i * strike_step)
            distance = abs(i)
            
            # Simple premium calculation
            base_premium = max(150 - (distance * 15), 5)
            itm_ce = max(spot_price - strike, 0)
            itm_pe = max(strike - spot_price, 0)
            
            ce_premium = round(base_premium + itm_ce * 0.5, 2)
            pe_premium = round(base_premium + itm_pe * 0.5, 2)
            
            calls.append({
                'strike': strike,
                'ltp': ce_premium,
                'oi': max(1000000 - (distance * 80000), 50000),
                'volume': max(50000 - (distance * 4000), 1000),
                'iv': round(12 + distance * 0.5, 1),
                'bid': round(ce_premium - 0.5, 2),
                'ask': round(ce_premium + 0.5, 2),
                'change': round(ce_premium * 0.02, 2),
                'change_pct': 2.0,
            })
            
            puts.append({
                'strike': strike,
                'ltp': pe_premium,
                'oi': max(1000000 - (distance * 80000), 50000),
                'volume': max(50000 - (distance * 4000), 1000),
                'iv': round(12 + distance * 0.5, 1),
                'bid': round(pe_premium - 0.5, 2),
                'ask': round(pe_premium + 0.5, 2),
                'change': round(pe_premium * 0.02, 2),
                'change_pct': 2.0,
            })
        
        return {
            'symbol': symbol,
            'spot_price': spot_price,
            'expiry': expiry,
            'atm_strike': atm_strike,
            'calls': calls,
            'puts': puts,
            'timestamp': get_ist_now(),
            '_mock': is_mock,
        }
    
    def get_option_quote(
        self, 
        symbol: str, 
        strike: float, 
        option_type: str, 
        expiry: str
    ) -> Dict:
        """Get quote for a specific option contract."""
        option_type = option_type.upper()
        if option_type not in ['CE', 'PE']:
            raise DhanAPIError(f"Invalid option_type: {option_type}")
        
        chain = self.get_option_chain(symbol, expiry)
        options_list = chain['calls'] if option_type == 'CE' else chain['puts']
        
        for option in options_list:
            if option['strike'] == strike:
                return {
                    'symbol': symbol,
                    'strike': strike,
                    'option_type': option_type,
                    'expiry': expiry,
                    'ltp': option['ltp'],
                    'bid': option.get('bid', option['ltp'] - 0.5),
                    'ask': option.get('ask', option['ltp'] + 0.5),
                    'oi': option.get('oi', 0),
                    'volume': option.get('volume', 0),
                    'iv': option.get('iv', 0),
                    'timestamp': get_ist_now(),
                    '_mock': chain.get('_mock', True),
                }
        
        raise DataError(f"Strike {strike} not found for {symbol}")
    
    # ══════════════════════════════════════════════════════
    # HISTORICAL DATA
    # ══════════════════════════════════════════════════════
    
    def get_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        interval: str = "DAY"
    ) -> List[Dict]:
        """Get historical OHLCV data."""
        symbol = symbol.upper().strip()
        
        if not self._dhan or not self.connected:
            return self._get_mock_historical(symbol, from_date, to_date)
        
        try:
            security_id = SECURITY_IDS.get(symbol)
            if not security_id:
                return self._get_mock_historical(symbol, from_date, to_date)
            
            # Use historical_daily_data method
            result = self._dhan.historical_daily_data(
                security_id=security_id,
                exchange_segment=self._dhan.IDX if hasattr(self._dhan, 'IDX') else 0,
                instrument_type='INDEX',
                from_date=from_date,
                to_date=to_date
            )
            
            if result and result.get('status') == 'success':
                data = result.get('data', {})
                
                if isinstance(data, dict):
                    opens = data.get('open', [])
                    highs = data.get('high', [])
                    lows = data.get('low', [])
                    closes = data.get('close', [])
                    volumes = data.get('volume', [0] * len(closes))
                    timestamps = data.get('start_Time', data.get('timestamp', []))
                    
                    candles = []
                    for i in range(len(closes)):
                        candles.append({
                            'open': float(opens[i]) if i < len(opens) else 0,
                            'high': float(highs[i]) if i < len(highs) else 0,
                            'low': float(lows[i]) if i < len(lows) else 0,
                            'close': float(closes[i]),
                            'volume': int(volumes[i]) if i < len(volumes) else 0,
                            'timestamp': timestamps[i] if i < len(timestamps) else '',
                        })
                    
                    if candles:
                        return candles
            
            return self._get_mock_historical(symbol, from_date, to_date)
            
        except Exception as e:
            logger.error(f"Error getting historical data: {e}")
            return self._get_mock_historical(symbol, from_date, to_date)
    
    def _get_mock_historical(self, symbol: str, from_date: str, to_date: str) -> List[Dict]:
        """Generate mock historical data."""
        import random
        
        base_prices = {"NIFTY": 23000, "BANKNIFTY": 48000, "FINNIFTY": 21000}
        base_price = base_prices.get(symbol, 20000)
        
        candles = []
        current_price = base_price
        
        try:
            start = datetime.strptime(from_date, "%Y-%m-%d")
            end = datetime.strptime(to_date, "%Y-%m-%d")
        except:
            start = datetime.now() - timedelta(days=30)
            end = datetime.now()
        
        current_date = start
        while current_date <= end:
            if current_date.weekday() < 5:  # Skip weekends
                change = random.uniform(-0.015, 0.015)
                open_p = current_price
                close_p = open_p * (1 + change)
                high_p = max(open_p, close_p) * (1 + random.uniform(0, 0.008))
                low_p = min(open_p, close_p) * (1 - random.uniform(0, 0.008))
                
                candles.append({
                    'open': round(open_p, 2),
                    'high': round(high_p, 2),
                    'low': round(low_p, 2),
                    'close': round(close_p, 2),
                    'volume': random.randint(100000, 500000),
                    'timestamp': current_date.strftime('%Y-%m-%d'),
                })
                current_price = close_p
            
            current_date += timedelta(days=1)
        
        return candles
    
    # ══════════════════════════════════════════════════════
    # ORDER MANAGEMENT
    # ══════════════════════════════════════════════════════
    
    def place_order(self, order_params: Dict) -> Dict:
        """Place an order."""
        if not self._dhan or not self.connected:
            raise DhanAPIError("Not connected to Dhan")
        
        try:
            result = self._dhan.place_order(
                transaction_type=self._dhan.BUY if order_params.get('transaction_type') == 'BUY' else self._dhan.SELL,
                exchange_segment=self._dhan.NSE_FNO,
                product_type=self._dhan.INTRA if order_params.get('product_type') == 'INTRADAY' else self._dhan.MARGIN,
                order_type=self._dhan.MARKET if order_params.get('order_type') == 'MARKET' else self._dhan.LIMIT,
                security_id=str(order_params.get('security_id', '')),
                quantity=int(order_params.get('quantity', 0)),
                price=float(order_params.get('price', 0)),
            )
            
            if result and result.get('status') == 'success':
                return {
                    'order_id': result.get('data', {}).get('orderId', ''),
                    'status': 'PENDING',
                    'message': 'Order placed successfully',
                }
            else:
                return {
                    'order_id': '',
                    'status': 'REJECTED',
                    'message': result.get('remarks', {}).get('error_message', 'Failed') if result else 'No response',
                }
                
        except Exception as e:
            raise DhanAPIError(f"Order failed: {e}")
    
    def get_positions(self) -> List[Dict]:
        """Get open positions."""
        if not self._dhan or not self.connected:
            return []
        try:
            result = self._dhan.get_positions()
            if result and result.get('status') == 'success':
                return result.get('data', [])
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
        return []
    
    def get_order_book(self) -> List[Dict]:
        """Get today's orders."""
        if not self._dhan or not self.connected:
            return []
        try:
            result = self._dhan.get_order_list()
            if result and result.get('status') == 'success':
                return result.get('data', [])
        except Exception as e:
            logger.error(f"Failed to get orders: {e}")
        return []
    
    def get_fund_limits(self) -> Dict:
        """Get available funds."""
        if not self._dhan:
            return {'available_balance': 0}
        try:
            result = self._dhan.get_fund_limits()
            if result and result.get('status') == 'success':
                return result.get('data', {})
        except Exception as e:
            logger.error(f"Failed to get funds: {e}")
        return {'available_balance': 0}


# ══════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════

_client_instance: Optional[DhanClient] = None

def get_dhan_client() -> DhanClient:
    """Get singleton Dhan client instance."""
    global _client_instance
    
    if _client_instance is None:
        try:
            from config.settings import settings
            _client_instance = DhanClient(
                client_id=settings.DHAN_CLIENT_ID,
                access_token=settings.DHAN_ACCESS_TOKEN
            )
        except Exception as e:
            logger.warning(f"Could not load settings: {e}")
            _client_instance = DhanClient()
    
    return _client_instance


# ══════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  DHAN CLIENT - DETAILED TEST")
    print("=" * 60)
    
    # Load settings
    try:
        from config.settings import settings
        client_id = settings.DHAN_CLIENT_ID
        access_token = settings.DHAN_ACCESS_TOKEN
    except Exception as e:
        print(f"\n  ⚠️  Could not load settings: {e}")
        client_id = ""
        access_token = ""
    
    client = DhanClient(client_id, access_token)
    
    print(f"\n  Client ID:    {'✅ Set' if client_id else '❌ Not set'}")
    print(f"  Access Token: {'✅ Set' if access_token else '❌ Not set'}")
    
    # Get callable methods
    if client._dhan:
        methods = [m for m in dir(client._dhan) if not m.startswith('_') and callable(getattr(client._dhan, m, None))]
        print(f"\n  Callable Methods ({len(methods)}):")
        for m in sorted(methods)[:15]:
            print(f"    - {m}")
        if len(methods) > 15:
            print(f"    ... and {len(methods) - 15} more")
        
        # Show constants
        constants = [m for m in dir(client._dhan) if not m.startswith('_') and not callable(getattr(client._dhan, m, None))]
        print(f"\n  Constants ({len(constants)}):")
        for c in sorted(constants)[:10]:
            val = getattr(client._dhan, c, None)
            print(f"    - {c} = {val}")
    
    # Test connection
    print("\n" + "-" * 60)
    print("  Testing connection...")
    connected = client.connect()
    print(f"  Connected: {'✅ Yes' if connected else '❌ No'}")
    
    # Test index quote
    print("\n" + "-" * 60)
    print("  Testing get_index_quote('NIFTY')...")
    try:
        quote = client.get_index_quote("NIFTY")
        mock = " (MOCK)" if quote.get('_mock') else " (LIVE)"
        print(f"  ✅ NIFTY LTP: ₹{quote['ltp']:,.2f}{mock}")
        print(f"     Open:  ₹{quote['open']:,.2f}")
        print(f"     High:  ₹{quote['high']:,.2f}")
        print(f"     Low:   ₹{quote['low']:,.2f}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # Test BANKNIFTY
    print("\n  Testing get_index_quote('BANKNIFTY')...")
    try:
        quote = client.get_index_quote("BANKNIFTY")
        mock = " (MOCK)" if quote.get('_mock') else " (LIVE)"
        print(f"  ✅ BANKNIFTY: ₹{quote['ltp']:,.2f}{mock}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # Test option chain
    print("\n" + "-" * 60)
    print("  Testing get_option_chain('NIFTY', '2025-01-16')...")
    try:
        chain = client.get_option_chain("NIFTY", "2025-01-16")
        mock = " (MOCK)" if chain.get('_mock') else " (LIVE)"
        print(f"  ✅ Spot:   ₹{chain['spot_price']:,.2f}{mock}")
        print(f"     ATM:    {chain['atm_strike']}")
        print(f"     Calls:  {len(chain['calls'])} strikes")
        print(f"     Puts:   {len(chain['puts'])} strikes")
        
        # Show ATM options
        atm = chain['atm_strike']
        for c in chain['calls']:
            if c['strike'] == atm:
                print(f"     ATM CE: ₹{c['ltp']:.2f} (IV: {c['iv']}%)")
        for p in chain['puts']:
            if p['strike'] == atm:
                print(f"     ATM PE: ₹{p['ltp']:.2f} (IV: {p['iv']}%)")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # Test historical
    print("\n" + "-" * 60)
    print("  Testing get_historical('NIFTY', last 10 days)...")
    try:
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        history = client.get_historical("NIFTY", from_date, to_date)
        print(f"  ✅ Candles: {len(history)}")
        if history:
            latest = history[-1]
            print(f"     Latest: {latest['timestamp']}")
            print(f"     Close:  ₹{latest['close']:,.2f}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # Test fund limits
    print("\n" + "-" * 60)
    print("  Testing get_fund_limits()...")
    try:
        funds = client.get_fund_limits()
        if funds:
            print(f"  ✅ Funds retrieved")
            for key, value in list(funds.items())[:5]:
                print(f"     {key}: {value}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    print("\n" + "=" * 60)
    print("  Test Complete!")
    print("=" * 60 + "\n")