"""
Quick test to diagnose why commands don't respond.
Run this STANDALONE — not through your main bot.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ─── Step 1: Check your config ───
print("=" * 60)
print("  TELEGRAM BOT DIAGNOSTIC")
print("=" * 60)

from config.settings import settings

token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
admin_ids_raw = getattr(settings, "TELEGRAM_ADMIN_IDS", "")

print(f"\n1. Token: {'✅ Set' if token and ':' in token else '❌ Missing'}")
print(f"2. Chat ID: {chat_id}")
print(f"3. Raw ADMIN_IDS value: {repr(admin_ids_raw)}")
print(f"   Type: {type(admin_ids_raw)}")

# Parse admin IDs the same way your bot does
if isinstance(admin_ids_raw, str):
    admin_ids = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip()]
elif isinstance(admin_ids_raw, list):
    admin_ids = [int(x) for x in admin_ids_raw if x]
else:
    admin_ids = []

print(f"4. Parsed admin IDs: {admin_ids}")

YOUR_TELEGRAM_ID = 8526564458  # From your logs
print(f"\n5. Your Telegram user ID: {YOUR_TELEGRAM_ID}")
print(f"6. Is your ID in admin list? {'✅ YES' if YOUR_TELEGRAM_ID in admin_ids else '❌ NO ← THIS IS THE PROBLEM'}")

if YOUR_TELEGRAM_ID not in admin_ids:
    print(f"\n   ⚠️  FIX: Add {YOUR_TELEGRAM_ID} to TELEGRAM_ADMIN_IDS in .env")
    print(f"   Example: TELEGRAM_ADMIN_IDS={YOUR_TELEGRAM_ID}")

# ─── Step 2: Check handler imports ───
print(f"\n{'=' * 60}")
print("  CHECKING HANDLER IMPORTS")
print("=" * 60)

try:
    from telegram_bot.handlers import (
        cmd_start, cmd_stop, cmd_pause, cmd_resume, cmd_restart,
        cmd_status, cmd_health,
        cmd_portfolio, cmd_positions, cmd_trades, cmd_pnl,
        cmd_signals, cmd_brains, cmd_watchlist,
        cmd_settings, cmd_mode, cmd_risk, cmd_report,
        cmd_kill, cmd_close, cmd_closeall,
        cmd_help,
    )
    print("✅ All 22 command handlers imported OK")
except ImportError as e:
    print(f"❌ Import error: {e}")

try:
    from telegram_bot.handlers import handle_callback
    print("✅ handle_callback imported OK")
except ImportError:
    print("❌ handle_callback NOT found in handlers.py")
    print("   You need to update handlers.py with the new code!")

# ─── Step 3: Test sending a message ───
print(f"\n{'=' * 60}")
print("  TESTING MESSAGE SEND")
print("=" * 60)

try:
    from telegram import Bot

    async def test_send():
        async with Bot(token) as bot:
            me = await bot.get_me()
            print(f"✅ Bot connected: @{me.username} ({me.id})")
            
            await bot.send_message(
                chat_id=chat_id,
                text="🧪 <b>Diagnostic Test</b>\n\nIf you see this, message sending works!",
                parse_mode="HTML",
            )
            print(f"✅ Test message sent to chat {chat_id}")

    asyncio.run(test_send())

except Exception as e:
    print(f"❌ Send failed: {e}")
    if "Chat not found" in str(e):
        print(f"   ⚠️  Your TELEGRAM_CHAT_ID ({chat_id}) is wrong")
        print(f"   ⚠️  It should be your user ID: {YOUR_TELEGRAM_ID}")

print(f"\n{'=' * 60}")
print("  DONE")
print("=" * 60)