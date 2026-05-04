import asyncio
import re
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
user_waiting_for_session = {}

print("Starting Ban All Bot...")

app = Client("ban_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def extract_chat_id(chat_input):
    if chat_input.lstrip("-").isdigit():
        return int(chat_input)
    match = re.search(r"t\.me/([a-zA-Z0-9_]+)", chat_input)
    if match:
        return match.group(1)
    return None

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
                await asyncio.sleep(0.05)
            except Exception:
                pass
        return banned

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    user_id = message.from_user.id
    user_waiting_for_session[user_id] = True
    await message.reply_text(
        "⚡ Ban All Bot\n\n"
        "Please send me your Pyrogram session string\n\n"
        "How to get session:\n"
        "1. Go to: https://telegram.tools/session-string-generator\n"
        "2. Enter your phone number\n"
        "3. Enter verification code\n"
        "4. Enter 2FA password (if enabled)\n"
        "5. Copy the session string\n\n"
        "Then send: /startban group_link_or_id"
    )

@app.on_message(filters.private & filters.command("startban"))
async def startban(client, message):
    user_id = message.from_user.id
    
    if user_id in processing_users and processing_users[user_id] == True:
        await message.reply_text("⏳ Please wait, your previous ban is still running")
        return
    
    if user_id not in temp_sessions:
        await message.reply_text("❌ No session found\n\nPlease send your Pyrogram session string first")
        return
    
    if len(message.command) < 2:
        await message.reply_text("❌ Usage: /startban group_link_or_id\n\nExample: /startban https://t.me/yourgroup")
        return
    
    processing_users[user_id] = True
    session_string = temp_sessions[user_id]
    chat_input = message.command[1]
    chat_id = extract_chat_id(chat_input)
    
    if not chat_id:
        await message.reply_text("❌ Invalid group link or ID")
        processing_users[user_id] = False
        return
    
    status_msg = await message.reply_text("🔍 Checking admin permissions...")
    
    user_client = None
    try:
        user_client = Client("user_session", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await user_client.start()
        
        me = await user_client.get_me()
        await status_msg.edit_text(f"✅ Logged in as: {me.first_name}\n\n📥 Fetching group info...")
        
        try:
            member = await user_client.get_chat_member(chat_id, me.id)
        except Exception as e:
            await status_msg.edit_text(f"❌ Cannot access group\n\nMake sure you are admin in the group")
            processing_users[user_id] = False
            return
        
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await status_msg.edit_text("❌ You are not an admin in this group")
            processing_users[user_id] = False
            return
        
        has_ban_right = False
        if member.status == ChatMemberStatus.OWNER:
            has_ban_right = True
        elif member.privileges and member.privileges.can_restrict_members:
            has_ban_right = True
        
        if not has_ban_right:
            await status_msg.edit_text("❌ You don't have ban permission")
            processing_users[user_id] = False
            return
        
        await status_msg.edit_text("📥 Fetching all members...")
        
        member_ids = []
        async for member_obj in user_client.get_chat_members(chat_id):
            if member_obj.user.id != me.id and member_obj.user.id != user_id:
                member_ids.append(member_obj.user.id)
        
        total = len(member_ids)
        
        if total == 0:
            await status_msg.edit_text("✅ No members to ban")
            processing_users[user_id] = False
            return
        
        await status_msg.edit_text(f"🚀 Banning {total} members...")
        
        chunk_size = 50
        chunks = [member_ids[i:i + chunk_size] for i in range(0, len(member_ids), chunk_size)]
        
        semaphore = Semaphore(5)
        tasks = []
        
        for chunk in chunks:
            task = ban_chunk(user_client, chat_id, chunk, semaphore)
            tasks.append(task)
        
        start_time = time.time()
        results = await asyncio.gather(*tasks)
        banned_count = sum(results)
        elapsed = time.time() - start_time
        
        await status_msg.edit_text(
            f"✅ BANNING COMPLETE\n\n"
            f"Banned: {banned_count}/{total}\n"
            f"Time: {elapsed:.1f} seconds"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)[:100]}")
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
    
    if user_id in processing_users and processing_users[user_id] == True:
        return
    
    if user_id in temp_sessions:
        return
    
    session_string = message.text.strip()
    
    if len(session_string) < 30:
        await message.reply_text("❌ Invalid session string\n\nGenerate from: https://telegram.tools/session-string-generator")
        return
    
    validation_msg = await message.reply_text("🔄 Validating session...")
    
    is_valid, result = await validate_session(session_string, API_ID, API_HASH)
    
    if not is_valid:
        await validation_msg.edit_text(f"❌ Invalid session\n\n{str(result)[:100]}\n\nGenerate new session from telegram.tools")
        return
    
    temp_sessions[user_id] = session_string
    
    await validation_msg.edit_text(
        f"✅ Session saved!\n\n"
        f"Logged in as: {result.first_name}\n\n"
        f"Now send:\n/startban https://t.me/yourgroup"
    )

if __name__ == "__main__":
    print("Bot started successfully!")
    app.run()
