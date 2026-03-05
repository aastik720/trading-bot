"""
Send /start to your bot, then run this script.
It will print the user ID of whoever messaged the bot.
"""
import asyncio
from telegram import Bot

TOKEN = "8751501193:AAFRHXH9sDTRk17ZXSKaXRr5npthLFfrWGY"

async def main():
    async with Bot(TOKEN) as bot:
        # Get bot info
        me = await bot.get_me()
        print(f"Bot: @{me.username}")
        
        # Get recent messages
        updates = await bot.get_updates(limit=5)
        
        if not updates:
            print("\nNo messages found!")
            print("Send /start to your bot first, then run again.")
            return
        
        print(f"\nRecent messages:\n")
        seen = set()
        for update in updates:
            if update.message and update.message.from_user:
                user = update.message.from_user
                if user.id not in seen:
                    seen.add(user.id)
                    print(f"  Name:     {user.first_name} {user.last_name or ''}")
                    print(f"  Username: @{user.username or 'N/A'}")
                    print(f"  User ID:  {user.id}")
                    print(f"  Chat ID:  {update.message.chat.id}")
                    print()
        
        print("=" * 40)
        print("Add this to your .env file:")
        print("=" * 40)
        for uid in seen:
            print(f"TELEGRAM_ADMIN_IDS={uid}")
            print(f"TELEGRAM_CHAT_ID={uid}")

asyncio.run(main())