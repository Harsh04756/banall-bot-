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

print("Starting Ban All Bot...")

app = Client("ban_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def extract_chat_id(chat_input):
    if chat_input.lstrip("-").isdigit():
        return int(chat_input)
    match = re.search(r"t\.me/([a-zA-Z0-9_\+]+)", chat_input)
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
    await message.reply_text(
        "⚡ Ban All Bot\n\n"
        "Send me your Pyrogram session string\n"
        "Then use: /startban group_link_or_id\n\n"
        "IMPORTANT:\n"
        "Your account must be a MEMBER of the group\n"
        "Your account must be ADMIN with BAN permission\n\n"
        "Get session: https://telegram.tools/session-string-generator"
    )

@app.on_message(filters.private & filters.command("startban"))
async def startban(client, message):
    user_id = message.from_user.id
    
    if user_id in processing_users and processing_users[user_id]:
        await message.reply_text("⏳ Previous ban still running")
        return
    
    if user_id not in temp_sessions:
        await message.reply_text("❌ Send your session string first")
        return
    
    if len(message.command) < 2:
        await message.reply_text("❌ Usage: /startban group_link_or_id")
        return
    
    processing_users[user_id] = True
    session_string = temp_sessions[user_id]
    chat_input = message.command[1]
    
    status_msg = await message.reply_text("🔍 Checking...")
    
    user_client = None
    try:
        user_client = Client("user_session", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await user_client.start()
        
        me = await user_client.get_me()
        await status_msg.edit_text(f"✅ Logged in as: {me.first_name}\n\n📥 Accessing group...")
        
        chat_id = None
        try:
            if chat_input.startswith("https://t.me/+"):
                chat = await user_client.join_chat(chat_input)
                chat_id = chat.id
                await status_msg.edit_text(f"✅ Joined group: {chat.title}\n\nChecking admin status...")
            elif chat_input.startswith("https://t.me/"):
                username = chat_input.replace("https://t.me/", "")
                chat = await user_client.get_chat(username)
                chat_id = chat.id
                await status_msg.edit_text(f"✅ Found group: {chat.title}\n\nChecking admin status...")
            elif chat_input.lstrip("-").isdigit():
                chat_id = int(chat_input)
                chat = await user_client.get_chat(chat_id)
                await status_msg.edit_text(f"✅ Found group: {chat.title}\n\nChecking admin status...")
            else:
                await status_msg.edit_text("❌ Invalid group link format")
                return
        except Exception as e:
            error_str = str(e)
            if "USER_ALREADY_PARTICIPANT" in error_str:
                chat = await user_client.get_chat(chat_input)
                chat_id = chat.id
                await status_msg.edit_text(f"✅ Already member of: {chat.title}\n\nChecking admin status...")
            elif "USER_NOT_PARTICIPANT" in error_str:
                await status_msg.edit_text(
                    "❌ Your account is NOT a member of this group\n\n"
                    "Solution:\n"
                    "1. Join the group with your account first\n"
                    "2. Then try again\n\n"
                    f"Group link: {chat_input}"
                )
                return
            else:
                await status_msg.edit_text(f"❌ Cannot access group\n\nError: {error_str[:150]}")
                return
        
        try:
            member = await user_client.get_chat_member(chat_id, me.id)
        except Exception as e:
            await status_msg.edit_text(f"❌ Cannot get member info\n\nMake sure you are in the group")
            return
        
        if member.status == ChatMemberStatus.OWNER:
            has_ban_right = True
        elif member.status == ChatMemberStatus.ADMINISTRATOR:
            if member.privileges and member.privileges.can_restrict_members:
                has_ban_right = True
            else:
                await status_msg.edit_text("❌ You are admin but NO BAN PERMISSION\n\nAsk group owner to give you ban rights")
                return
        else:
            await status_msg.edit_text("❌ You are NOT an admin in this group\n\nMake sure your account is admin")
            return
        
        if not has_ban_right:
            await status_msg.edit_text("❌ No ban permission")
            return
        
        await status_msg.edit_text("📥 Fetching member list...")
        
        member_ids = []
        async for member_obj in user_client.get_chat_members(chat_id):
            if member_obj.user.id != me.id and member_obj.user.id != user_id:
                member_ids.append(member_obj.user.id)
        
        total = len(member_ids)
        
        if total == 0:
            await status_msg.edit_text("✅ No members to ban")
            return
        
        await status_msg.edit_text(f"🚀 Banning {total} members...")
        
        chunk_size = 50
        chunks = [member_ids[i:i + chunk_size] for i in range(0, len(member_ids), chunk_size)]
        
        semaphore = Semaphore(5)
        tasks = [ban_chunk(user_client, chat_id, chunk, semaphore) for chunk in chunks]
        
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
        await status_msg.edit_text(f"❌ Error: {str(e)[:200]}")
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
        await message.reply_text("❌ Invalid session string\n\nGenerate from: https://telegram.tools/session-string-generator")
        return
    
    validation_msg = await message.reply_text("🔄 Validating session...")
    
    is_valid, result = await validate_session(session_string, API_ID, API_HASH)
    
    if not is_valid:
        await validation_msg.edit_text(f"❌ Invalid session\n\n{str(result)[:150]}")
        return
    
    temp_sessions[user_id] = session_string
    
    await validation_msg.edit_text(
        f"✅ Session saved!\n\n"
        f"Logged in as: {result.first_name}\n\n"
        f"Now send:\n/startban https://t.me/yourgroup\n\n"
        f"⚠️ Your account must be admin and MEMBER of the group"
    )

if __name__ == "__main__":
    print("Bot started successfully!")
    app.run()
