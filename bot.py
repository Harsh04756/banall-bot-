import asyncio
import re
import os
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from asyncio import Semaphore
import time

API_ID = "39913022"
API_HASH = "3aca64fcda769c4af7d0002119148e6b"
BOT_TOKEN = "8496518091:AAHYALw97mLgDRU-5D3B37rd5kF2KGuV2Do"

temp_sessions = {}

app = Client("ban_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def extract_chat_id(chat_input):
    if chat_input.lstrip("-").isdigit():
        return int(chat_input)
    match = re.search(r"t\.me/([a-zA-Z0-9_]+)", chat_input)
    if match:
        return match.group(1)
    return None

async def ban_chunk(client, chat_id, user_chunk, semaphore, chunk_num):
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

@app.on_message(filters.private & filters.command("startban"))
async def startban(client, message):
    user_id = message.from_user.id
    
    if user_id not in temp_sessions:
        await message.reply_text("Please send your Pyrogram session string first")
        return
    
    if len(message.command) < 2:
        await message.reply_text("Usage: /startban group_link_or_id")
        return
    
    session_string = temp_sessions[user_id]
    chat_input = message.command[1]
    chat_id = extract_chat_id(chat_input)
    
    if not chat_id:
        await message.reply_text("Invalid group link or ID")
        return
    
    status_msg = await message.reply_text("🔍 Verifying admin access...")
    
    user_client = None
    try:
        user_client = Client("user_session", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await user_client.start()
        
        me = await user_client.get_me()
        member = await user_client.get_chat_member(chat_id, me.id)
        
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await status_msg.edit_text("You are not an admin in this group")
            return
        
        if member.status != ChatMemberStatus.OWNER and not (member.privileges and member.privileges.can_restrict_members):
            await status_msg.edit_text("You don't have ban permission")
            return
        
        await status_msg.edit_text("📥 Fetching all members...")
        
        member_ids = []
        async for member_obj in user_client.get_chat_members(chat_id):
            if member_obj.user.id != me.id and member_obj.user.id != message.from_user.id:
                member_ids.append(member_obj.user.id)
        
        total = len(member_ids)
        
        if total == 0:
            await status_msg.edit_text("No members to ban")
            return
        
        await status_msg.edit_text(f"🚀 Banning {total} members at maximum speed...")
        
        chunk_size = 50
        chunks = [member_ids[i:i + chunk_size] for i in range(0, len(member_ids), chunk_size)]
        
        semaphore = Semaphore(5)
        tasks = []
        
        for i, chunk in enumerate(chunks):
            task = ban_chunk(user_client, chat_id, chunk, semaphore, i)
            tasks.append(task)
        
        start_time = time.time()
        results = await asyncio.gather(*tasks)
        banned_count = sum(results)
        elapsed = time.time() - start_time
        
        await status_msg.edit_text(
            f"✅ BANNING COMPLETE\n\n"
            f"Banned: {banned_count}/{total}\n"
            f"Time: {elapsed:.1f} seconds\n"
            f"Speed: {banned_count/elapsed:.1f} users/sec"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"Error: {str(e)[:100]}")
    finally:
        if user_client:
            await user_client.stop()
        if user_id in temp_sessions:
            del temp_sessions[user_id]

@app.on_message(filters.private & filters.text & ~filters.command(["start", "startban"]))
async def save_session(client, message):
    session_string = message.text.strip()
    if len(session_string) > 50:
        temp_sessions[message.from_user.id] = session_string
        await message.reply_text("✅ Session ready. Send /startban group_link_or_id")
    else:
        await message.reply_text("Invalid session string")

if __name__ == "__main__":
    app.run()
