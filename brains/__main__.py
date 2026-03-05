"""
Brains package entry point.
Runs when you execute: python -m brains
"""

from brains import (
    __version__,
    list_available_brains,
    get_brain_status,
)

print("\n" + "=" * 60)
print("  BRAINS PACKAGE")
print("=" * 60)

print(f"\n  Version: {__version__}")

print("\n  Available Brains:")
for brain in list_available_brains():
    status_icon = "✅" if brain['status'] == 'active' else "⏳"
    print(f"    {status_icon} {brain['name']:<12} ({brain['weight']:.0%})")
    print(f"       {brain['description']}")

print("\n  Quick Start:")
print("    from brains import get_coordinator")
print("    from data import get_market_data")
print("")
print("    coordinator = get_coordinator()")
print("    md = get_market_data()")
print("    signal = coordinator.analyze_symbol('NIFTY', md)")
print("    print(f\"Action: {signal['action']}\")")

# Try to get status
try:
    status = get_brain_status()
    if status['initialized']:
        print(f"\n  Status:")
        print(f"    Active Brains: {status['active_count']}")
        print(f"    Total Weight: {status['total_weight']:.0%}")
except Exception as e:
    print(f"\n  ⚠️  Full status unavailable: {e}")

print("\n" + "=" * 60 + "\n")