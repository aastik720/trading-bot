# Save as: test_data_layer.py (in root folder)
"""
Quick test for Data Layer
"""

print("\n" + "=" * 60)
print("  DATA LAYER - QUICK TEST")
print("=" * 60)

# Test 1: Import data package
print("\n1. Testing imports...")
try:
    from data import DhanClient, FinnhubClient, MarketData
    print("   ✅ All classes imported")
except ImportError as e:
    print(f"   ❌ Import error: {e}")

try:
    from data import get_dhan_client, get_finnhub_client, get_market_data
    print("   ✅ All factory functions imported")
except ImportError as e:
    print(f"   ❌ Import error: {e}")

# Test 2: Create instances
print("\n2. Creating instances...")
try:
    dhan = get_dhan_client()
    print(f"   ✅ DhanClient: connected={dhan.is_connected()}")
except Exception as e:
    print(f"   ❌ DhanClient error: {e}")

try:
    finnhub = get_finnhub_client()
    print(f"   ✅ FinnhubClient: configured={finnhub.is_configured()}")
except Exception as e:
    print(f"   ❌ FinnhubClient error: {e}")

try:
    md = get_market_data()
    print(f"   ✅ MarketData: created")
except Exception as e:
    print(f"   ❌ MarketData error: {e}")

# Test 3: Get status
print("\n3. MarketData Status...")
try:
    status = md.get_status()
    print(f"   Dhan Connected:     {'✅' if status['dhan_connected'] else '⚠️ '} {status['dhan_connected']}")
    print(f"   Finnhub Configured: {'✅' if status['finnhub_configured'] else '⚠️ '} {status['finnhub_configured']}")
    print(f"   Market Open:        {'✅' if status['market_open'] else '🔴'} {status['market_open']}")
except Exception as e:
    print(f"   ❌ Status error: {e}")

# Test 4: Get prices
print("\n4. Getting Prices...")
try:
    for symbol in ["NIFTY", "BANKNIFTY"]:
        quote = md.get_quote(symbol)
        live = "LIVE" if quote.get('is_live') else "MOCK"
        print(f"   {symbol}: ₹{quote['ltp']:,.2f} ({live})")
except Exception as e:
    print(f"   ❌ Price error: {e}")

# Test 5: Get option chain
print("\n5. Getting Option Chain...")
try:
    chain = md.get_option_chain("NIFTY")
    live = "LIVE" if chain.get('is_live') else "MOCK"
    print(f"   Spot: ₹{chain['spot_price']:,.2f}")
    print(f"   ATM:  {chain['atm_strike']}")
    print(f"   Calls: {len(chain['calls'])}, Puts: {len(chain['puts'])}")
    print(f"   Data: {live}")
except Exception as e:
    print(f"   ❌ Option chain error: {e}")

# Test 6: Get news
print("\n6. Getting News...")
try:
    news = md.get_news(limit=3)
    print(f"   Fetched {len(news)} articles")
    for article in news[:2]:
        headline = article['headline'][:45] + "..." if len(article['headline']) > 45 else article['headline']
        print(f"   • {headline}")
except Exception as e:
    print(f"   ❌ News error: {e}")

# Test 7: Cache stats
print("\n7. Cache Stats...")
try:
    stats = md.get_cache_stats()
    print(f"   Hits: {stats['hits']}, Misses: {stats['misses']}")
    print(f"   Hit Rate: {stats['hit_rate']}%")
except Exception as e:
    print(f"   ❌ Cache error: {e}")

print("\n" + "=" * 60)
print("  DATA LAYER TEST COMPLETE!")
print("=" * 60 + "\n")