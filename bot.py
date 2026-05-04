import asyncio
import os
import sys
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatMemberStatus
from asyncio import Semaphore
import time

def get_env_var(var_name):
    value = os.getenv(var_name)
    if not value:
        print(f"ERROR: {var_name} environment variable is not set")
        sys.exit(1)
    return value

API_ID = int(get_env_var("API_ID"))
API_HASH = get_env_var("API_HASH")
BOT_TOKEN = get_env_var("BOT_TOKEN")

temp_sessions = {}
processing_users = {}

print("Starting Ban All Bot...")

app = Client("ban_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

async def validate_session(session_string, api_id, api_hash):
    try:
        client = Client("test", session_string=session_string, api_id=api_id, api_hash=api_hash, in_memory=True)
        await client.start()
        me = await client.get_me()
        await client.stop()
        return True, me
    except Exception as e:
        return False, str(e)

async def ban_chunk(client, chat_id, user_chunk, semaphore):
    async with semaphore:
        banned = 0
        for user_id in user_chunk:
            try:
                await client.ban_chat_member(chat_id, user_id)
                banned += 1
                await asyncio.sleep(0.03)  # 30ms delay - fast but safe
            except Exception:
                pass
        return banned

async def ban_worker(client, chat_id, queue, semaphore, result_dict, worker_id):
    """Continuous worker that processes users from queue"""
    banned = 0
    while True:
        try:
            user_id = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        
        async with semaphore:
            try:
                await client.ban_chat_member(chat_id, user_id)
                banned += 1
                await asyncio.sleep(0.02)  # 20ms between bans
            except Exception:
                pass
        
        queue.task_done()
    
    result_dict[worker_id] = banned

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    await message.reply_text(
        "⚡ **Ban All Bot - Speed Mode**\n\n"
        "**STEP 1:** Send your Pyrogram session string\n"
        "**STEP 2:** Send group ID/username only\n\n"
        "📌 Format: `username` or `-100123456789`\n"
        "❌ Links not supported (speed ke liye)\n\n"
        "⚠️ Account must be **ADMIN** with **BAN RIGHTS**\n"
        "⚠️ Account must be **MEMBER** of group already\n\n"
        "🔗 Get session: https://telegram.tools/session-string-generator"
    )

@app.on_message(filters.private & filters.command("startban"))
async def startban(client, message):
    user_id = message.from_user.id
    
    if user_id in processing_users and processing_users[user_id]:
        await message.reply_text("⏳ Previous ban still running. Wait karo!")
        return
    
    if user_id not in temp_sessions:
        await message.reply_text("❌ Pehle session string bhejo!")
        return
    
    if len(message.command) < 2:
        await message.reply_text("❌ Usage: `/startban group_username` OR `/startban -100123456789`")
        return
    
    processing_users[user_id] = True
    session_string = temp_sessions[user_id]
    chat_input = message.command[1]
    
    status_msg = await message.reply_text("⚡ **Starting speed mode...**")
    
    user_client = None
    try:
        user_client = Client(
            "user_session",
            session_string=session_string,
            api_id=API_ID,
            api_hash=API_HASH,
            in_memory=True,
            workers=50  # Maximize workers
        )
        await user_client.start()
        
        me = await user_client.get_me()
        
        # Fast resolve - no link parsing, no joining, no checking
        try:
            if chat_input.startswith("-100"):
                chat_id = int(chat_input)
            elif chat_input.startswith("-"):
                chat_id = int(chat_input)
            elif chat_input.isdigit():
                chat_id = int(chat_input)
            else:
                # Assume username
                chat_id = chat_input.strip("@")
        except:
            await status_msg.edit_text("❌ Invalid format. Use username or numeric ID")
            return
        
        await status_msg.edit_text(f"✅ Connected as: {me.first_name}\n📥 Fetching members...")
        
        # Fetch members - skip self and admins
        member_ids = []
        admin_ids = set()
        
        async for member_obj in user_client.get_chat_members(chat_id):
            uid = member_obj.user.id
            # Skip self
            if uid == me.id:
                continue
            # Collect admins to skip
            if member_obj.status in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR]:
                admin_ids.add(uid)
                continue
            # Skip bots if you want
            # if member_obj.user.is_bot:
            #     continue
            member_ids.append(uid)
        
        total = len(member_ids)
        
        if total == 0:
            await status_msg.edit_text("✅ No non-admin members to ban!")
            return
        
        await status_msg.edit_text(f"🎯 **{total} members to ban**\n⚡ Starting bans...")
        
        # Use queue for better distribution
        queue = asyncio.Queue()
        for uid in member_ids:
            await queue.put(uid)
        
        # Multiple concurrent workers
        NUM_WORKERS = 15  # Heroku pe safe hai
        semaphore = Semaphore(20)  # 20 concurrent bans max
        result_dict = {}
        
        workers = [
            ban_worker(user_client, chat_id, queue, semaphore, result_dict, i)
            for i in range(NUM_WORKERS)
        ]
        
        start_time = time.time()
        await asyncio.gather(*workers)
        banned_count = sum(result_dict.values())
        elapsed = time.time() - start_time
        
        # Calculate speed
        speed = banned_count / elapsed if elapsed > 0 else 0
        
        await status_msg.edit_text(
            f"✅ **BANNING COMPLETE**\n\n"
            f"🎯 Banned: **{banned_count}/{total}**\n"
            f"⏱ Time: **{elapsed:.1f}s**\n"
            f"⚡ Speed: **{speed:.0f} bans/sec**\n\n"
            f"💀 Group clean!"
        )
        
    except Exception as e:
        error_msg = str(e)[:200]
        await status_msg.edit_text(f"❌ **Error:**\n`{error_msg}`")
    finally:
        if user_client:
            try:
                await user_client.stop()
            except:
                pass
        processing_users[user_id] = False

@app.on_message(filters.private & filters.text & ~filters.command(["start", "startban"]))
async def save_session(client, message):
    user_id = message.from_user.id
    
    if user_id in processing_users and processing_users[user_id]:
        return
    
    if user_id in temp_sessions:
        return
    
    session_string = message.text.strip()
    
    if len(session_string) < 30:
        await message.reply_text("❌ Invalid session string!")
        return
    
    validation_msg = await message.reply_text("🔄 Validating session...")
    
    is_valid, result = await validate_session(session_string, API_ID, API_HASH)
    
    if not is_valid:
        await validation_msg.edit_text(f"❌ Invalid session!\n{str(result)[:150]}")
        return
    
    temp_sessions[user_id] = session_string
    
    await validation_msg.edit_text(
        f"✅ **Session Saved!**\n\n"
        f"👤 Logged in as: **{result.first_name}**\n\n"
        f"Now send:\n`/startban group_username`\n\n"
        f"⚠️ Account must be admin & already in group"
    )

if __name__ == "__main__":
    print("Bot started successfully!")
    app.run()
