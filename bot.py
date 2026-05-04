import asyncio
import re
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatMemberStatus

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
WORKER_COUNT = int(os.getenv("WORKER_COUNT", 10))

temp_sessions = {}
processing_users = {}

print(f"⚡ STARTING WITH {WORKER_COUNT} WORKERS")
print(f"Expected speed: {WORKER_COUNT * 5}-{WORKER_COUNT * 7} bans/sec")

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

async def ultra_fast_worker(chat_id, member_ids, worker_id, session_string, progress_dict):
    client = Client(f"w_{worker_id}", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
    await client.start()
    
    banned = 0
    total = len(member_ids)
    flood_count = 0
    
    for idx, member_id in enumerate(member_ids):
        try:
            await client.ban_chat_member(chat_id, member_id)
            banned += 1
            
            if banned % 20 == 0:
                progress_dict[worker_id] = banned
                
        except Exception as e:
            error = str(e)
            if "FLOOD_WAIT" in error:
                flood_count += 1
                wait_time = int(re.search(r"(\d+)", error).group(1))
                if wait_time > 10:
                    await asyncio.sleep(wait_time)
                    try:
                        await client.ban_chat_member(chat_id, member_id)
                        banned += 1
                    except:
                        pass
            elif "USER_ID_INVALID" in error:
                continue
            else:
                continue
    
    await client.stop()
    return banned, flood_count

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    await message.reply_text(
        f"⚡ {WORKER_COUNT}-WORKER ULTRA FAST BAN BOT\n\n"
        f"🚀 Speed: {WORKER_COUNT*5}-{WORKER_COUNT*7} bans/sec\n"
        f"⏱️ 7000 members: 1.5 - 2 minutes\n"
        f"🔧 Workers: {WORKER_COUNT} parallel\n\n"
        f"Send your Pyrogram session string\n"
        f"Then: /startban group_link_or_id"
    )

@app.on_message(filters.private & filters.command("startban"))
async def startban(client, message):
    user_id = message.from_user.id
    
    if user_id in processing_users and processing_users[user_id]:
        await message.reply_text("⏳ Ban already running")
        return
    
    if user_id not in temp_sessions:
        await message.reply_text("❌ Send session string first")
        return
    
    if len(message.command) < 2:
        await message.reply_text("❌ /startban group_link_or_id")
        return
    
    processing_users[user_id] = True
    session_string = temp_sessions[user_id]
    chat_input = message.command[1]
    
    status_msg = await message.reply_text(f"🔥 INITIALIZING {WORKER_COUNT} WORKERS...")
    
    try:
        test_client = Client("test", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await test_client.start()
        me = await test_client.get_me()
        
        chat_id = extract_chat_id(chat_input)
        if not chat_id:
            await status_msg.edit_text("❌ Invalid group link")
            return
        
        try:
            if chat_input.startswith("https://t.me/+"):
                chat = await test_client.join_chat(chat_input)
                chat_id = chat.id
            else:
                chat = await test_client.get_chat(chat_id)
                chat_id = chat.id
        except Exception:
            await status_msg.edit_text("❌ Join group first with your account")
            return
        
        member = await test_client.get_chat_member(chat_id, me.id)
        
        has_ban_right = False
        if member.status == ChatMemberStatus.OWNER:
            has_ban_right = True
        elif member.status == ChatMemberStatus.ADMINISTRATOR:
            if member.privileges and member.privileges.can_restrict_members:
                has_ban_right = True
        
        if not has_ban_right:
            await status_msg.edit_text("❌ No ban permission")
            return
        
        await test_client.stop()
        
        await status_msg.edit_text(f"📥 Fetching {WORKER_COUNT} members at once...")
        
        final_client = Client("final", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await final_client.start()
        
        member_ids = []
        async for member_obj in final_client.get_chat_members(chat_id):
            if member_obj.user.id != me.id and member_obj.user.id != user_id:
                member_ids.append(member_obj.user.id)
        
        await final_client.stop()
        
        total = len(member_ids)
        
        await status_msg.edit_text(f"🚀 {WORKER_COUNT} WORKERS BANNING {total} MEMBERS\n⏱️ ETA: {total//(WORKER_COUNT*5)//60} minutes")
        
        chunk_size = max(1, total // WORKER_COUNT)
        chunks = []
        for i in range(WORKER_COUNT):
            start_idx = i * chunk_size
            end_idx = start_idx + chunk_size if i < WORKER_COUNT - 1 else total
            if start_idx < total:
                chunks.append(member_ids[start_idx:end_idx])
        
        progress_dict = {i: 0 for i in range(len(chunks))}
        
        start_time = time.time()
        
        tasks = []
        for i, chunk in enumerate(chunks):
            if len(chunk) > 0:
                task = ultra_fast_worker(chat_id, chunk, i, session_string, progress_dict)
                tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        total_banned = sum(r[0] for r in results)
        total_floods = sum(r[1] for r in results)
        elapsed = time.time() - start_time
        avg_speed = total_banned / elapsed if elapsed > 0 else 0
        
        await status_msg.edit_text(
            f"✅ BANNING COMPLETE!\n\n"
            f"🎯 Banned: {total_banned}/{total}\n"
            f"⏱️ Time: {elapsed/60:.2f} minutes ({elapsed:.0f} seconds)\n"
            f"⚡ Speed: {avg_speed:.1f} bans/sec\n"
            f"🔧 Workers: {WORKER_COUNT}\n"
            f"🌊 Flood waits: {total_floods}"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)[:150]}")
    finally:
        if user_id in temp_sessions:
            del temp_sessions[user_id]
        processing_users[user_id] = False

@app.on_message(filters.private & filters.text & ~filters.command(["start", "startban"]))
async def save_session(client, message):
    user_id = message.from_user.id
    
    if user_id in processing_users and processing_users[user_id]:
        return
    
    session_string = message.text.strip()
    
    if len(session_string) < 30:
        await message.reply_text("❌ Invalid session\n\nGet from: telegram.tools/session-string-generator")
        return
    
    validation_msg = await message.reply_text("🔄 Validating session...")
    
    is_valid, result = await validate_session(session_string, API_ID, API_HASH)
    
    if not is_valid:
        await validation_msg.edit_text(f"❌ Invalid: {str(result)[:100]}")
        return
    
    temp_sessions[user_id] = session_string
    
    await validation_msg.edit_text(
        f"✅ SESSION READY WITH {WORKER_COUNT} WORKERS!\n\n"
        f"👤 Logged in as: {result.first_name}\n"
        f"🚀 Max speed: {WORKER_COUNT*5}-{WORKER_COUNT*7} bans/sec\n\n"
        f"Send: /startban https://t.me/yourgroup"
    )

if __name__ == "__main__":
    print(f"⚡ ULTRA FAST BOT WITH {WORKER_COUNT} WORKERS")
    print(f"🔥 Ready to ban at {WORKER_COUNT*5}-{WORKER_COUNT*7} bans/sec")
    app.run()
