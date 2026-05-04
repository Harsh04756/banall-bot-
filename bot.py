import asyncio
import re
import os
import sys
import time
import json
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatMemberStatus

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
WORKER_COUNT = int(os.getenv("WORKER_COUNT", 10))

temp_sessions = {}
processing_users = {}

print(f"🔥 DESTROY MODE BOT STARTED WITH {WORKER_COUNT} WORKERS")

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

async def destroy_worker(chat_id, member_ids, worker_id, session_string, status_callback):
    client = None
    banned = 0
    total = len(member_ids)
    flood_count = 0
    
    while True:
        try:
            if client is None:
                client = Client(f"destroy_w_{worker_id}", session_string=session_string, 
                               api_id=API_ID, api_hash=API_HASH, in_memory=True)
                await client.start()
                print(f"🔥 Worker {worker_id}: Started")
            
            for idx, member_id in enumerate(member_ids):
                try:
                    await client.ban_chat_member(chat_id, member_id)
                    banned += 1
                    
                    if banned % 100 == 0:
                        print(f"💀 Worker {worker_id}: {banned}/{total} banned")
                        await status_callback(f"Worker {worker_id+1}: {banned}/{total}")
                    
                except Exception as e:
                    error = str(e)
                    
                    if "FLOOD_WAIT" in error:
                        flood_count += 1
                        wait_time = int(re.search(r"(\d+)", error).group(1))
                        print(f"🌊 Worker {worker_id}: Flood wait {wait_time}s (#{flood_count})")
                        await asyncio.sleep(wait_time)
                        try:
                            await client.ban_chat_member(chat_id, member_id)
                            banned += 1
                        except:
                            pass
                            
                    elif "USER_ID_INVALID" in error or "USER_NOT_PARTICIPANT" in error:
                        continue
                    else:
                        print(f"⚠️ Worker {worker_id}: {error[:50]}")
                        await asyncio.sleep(1)
            
            if banned >= total:
                break
                
        except Exception as e:
            print(f"❌ Worker {worker_id}: Reconnecting...")
            if client:
                try:
                    await client.stop()
                except:
                    pass
                client = None
            await asyncio.sleep(5)
            continue
    
    if client:
        try:
            await client.stop()
        except:
            pass
    
    return banned, flood_count

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    await message.reply_text(
        f"💀 DESTROY MODE BOT 💀\n\n"
        f"⚡ Workers: {WORKER_COUNT}\n"
        f"🔥 Speed: {WORKER_COUNT*5}-{WORKER_COUNT*7} bans/sec\n\n"
        f"Step 1: Send your Pyrogram session string\n"
        f"Step 2: Send /destroy group_link_or_id\n\n"
        f"⚠️ Your account must be admin in the group"
    )

@app.on_message(filters.private & filters.command("destroy"))
async def destroy_command(client, message):
    user_id = message.from_user.id
    
    if user_id in processing_users and processing_users[user_id]:
        await message.reply_text("⏳ Destroy already in progress...")
        return
    
    if user_id not in temp_sessions:
        await message.reply_text("❌ Send your session string first\n\nGet from: telegram.tools/session-string-generator")
        return
    
    if len(message.command) < 2:
        await message.reply_text("❌ /destroy group_link_or_id\n\nExample: /destroy https://t.me/yourgroup\nOR: /destroy -100123456789")
        return
    
    processing_users[user_id] = True
    session_string = temp_sessions[user_id]
    chat_input = message.command[1]
    
    status_msg = await message.reply_text(f"💀 INITIALIZING DESTROY MODE...")
    
    user_client = None
    try:
        user_client = Client("user", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await user_client.start()
        
        me = await user_client.get_me()
        await status_msg.edit_text(f"✅ Logged in as: {me.first_name}\n\n🔍 Accessing group...")
        
        chat_id = None
        chat = None
        
        # Try different methods to get chat
        try:
            # Method 1: Direct ID
            if chat_input.lstrip("-").isdigit():
                chat_id = int(chat_input)
                chat = await user_client.get_chat(chat_id)
            
            # Method 2: Private invite link (t.me/+abc123)
            elif "+" in chat_input:
                invite_hash = chat_input.split("+")[-1]
                chat = await user_client.join_chat(invite_hash)
                chat_id = chat.id
            
            # Method 3: Public username
            elif "t.me/" in chat_input:
                username = chat_input.split("t.me/")[-1]
                if username.startswith("+"):
                    chat = await user_client.join_chat(username)
                else:
                    try:
                        chat = await user_client.get_chat(username)
                    except:
                        chat = await user_client.join_chat(username)
                chat_id = chat.id
            
            else:
                chat = await user_client.get_chat(chat_input)
                chat_id = chat.id
                
        except Exception as e:
            error_msg = str(e)
            if "USER_ALREADY_PARTICIPANT" in error_msg:
                if chat_input.lstrip("-").isdigit():
                    chat = await user_client.get_chat(int(chat_input))
                else:
                    username = chat_input.split("t.me/")[-1] if "t.me/" in chat_input else chat_input
                    chat = await user_client.get_chat(username)
                chat_id = chat.id
            else:
                await status_msg.edit_text(
                    f"❌ Cannot access group\n\n"
                    f"Error: {error_msg[:100]}\n\n"
                    f"Solutions:\n"
                    f"1. Make sure your account is a MEMBER of the group\n"
                    f"2. Make sure your account is ADMIN in the group\n"
                    f"3. Try using group ID instead of link\n\n"
                    f"To get group ID:\n"
                    f"Add @userinfobot to your group and send /id"
                )
                return
        
        await status_msg.edit_text(f"✅ Group: {chat.title}\n👑 Checking admin permissions...")
        
        try:
            member = await user_client.get_chat_member(chat_id, me.id)
        except Exception as e:
            await status_msg.edit_text(f"❌ You are not a member of this group\n\nJoin the group first with your Telegram account")
            return
        
        if member.status == ChatMemberStatus.OWNER:
            has_ban_right = True
        elif member.status == ChatMemberStatus.ADMINISTRATOR:
            if member.privileges and member.privileges.can_restrict_members:
                has_ban_right = True
            else:
                await status_msg.edit_text("❌ You are admin but NO BAN PERMISSION")
                return
        else:
            await status_msg.edit_text(f"❌ You are NOT admin\n\nYour status: {member.status}\n\nMake sure your account is admin in this group")
            return
        
        await status_msg.edit_text(f"📥 Fetching member list...")
        
        member_ids = []
        async for member_obj in user_client.get_chat_members(chat_id):
            if member_obj.user.id != me.id and member_obj.user.id != user_id:
                member_ids.append(member_obj.user.id)
        
        await user_client.stop()
        user_client = None
        
        total = len(member_ids)
        
        if total == 0:
            await status_msg.edit_text("✅ No members to ban")
            return
        
        await status_msg.edit_text(
            f"💀 DESTROY MODE ENGAGED 💀\n\n"
            f"Group: {chat.title}\n"
            f"Members to destroy: {total}\n"
            f"Workers: {WORKER_COUNT}\n"
            f"Will continue until: EVERYONE BANNED\n\n"
            f"🔥 STARTING DESTRUCTION..."
        )
        
        chunk_size = max(1, total // WORKER_COUNT)
        chunks = []
        for i in range(WORKER_COUNT):
            start_idx = i * chunk_size
            end_idx = start_idx + chunk_size if i < WORKER_COUNT - 1 else total
            if start_idx < total:
                chunks.append(member_ids[start_idx:end_idx])
        
        start_time = time.time()
        
        tasks = []
        for i, chunk in enumerate(chunks):
            if len(chunk) > 0:
                task = destroy_worker(chat_id, chunk, i, session_string, status_msg.edit_text)
                tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        total_banned = sum(r[0] for r in results)
        total_floods = sum(r[1] for r in results)
        elapsed = time.time() - start_time
        
        await status_msg.edit_text(
            f"💀 GROUP DESTROYED 💀\n\n"
            f"✅ Banned: {total_banned}/{total}\n"
            f"⏱️ Time: {elapsed/60:.2f} minutes\n"
            f"⚡ Speed: {total_banned/elapsed:.1f} bans/sec\n"
            f"🌊 Flood waits: {total_floods}"
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

@app.on_message(filters.private & filters.text & ~filters.command(["start", "destroy"]))
async def save_session(client, message):
    user_id = message.from_user.id
    
    if user_id in processing_users and processing_users[user_id]:
        return
    
    session_string = message.text.strip()
    
    if len(session_string) < 30:
        await message.reply_text("❌ Invalid session string\n\nGenerate from: telegram.tools/session-string-generator")
        return
    
    validation_msg = await message.reply_text("🔄 Validating session...")
    
    is_valid, result = await validate_session(session_string, API_ID, API_HASH)
    
    if not is_valid:
        await validation_msg.edit_text(f"❌ Invalid session: {str(result)[:100]}")
        return
    
    temp_sessions[user_id] = session_string
    
    await validation_msg.edit_text(
        f"✅ Session ready!\n\n"
        f"👤 Account: {result.first_name}\n"
        f"🔧 Workers: {WORKER_COUNT}\n\n"
        f"Send: /destroy group_link_or_id\n\n"
        f"Examples:\n"
        f"/destroy https://t.me/yourgroup\n"
        f"/destroy -100123456789"
    )

if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"💀 DESTROY MODE BOT")
    print(f"Workers: {WORKER_COUNT}")
    print(f"{'='*50}\n")
    app.run()
