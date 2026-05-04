import asyncio
import re
import os
import sys
import time
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatMemberStatus

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
WORKER_COUNT = int(os.getenv("WORKER_COUNT", 10))

temp_sessions = {}
processing_users = {}

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

async def destroy_worker(chat_id, member_ids, worker_id, session_string):
    client = Client(f"destroy_w_{worker_id}", session_string=session_string, 
                   api_id=API_ID, api_hash=API_HASH, in_memory=True)
    await client.start()
    
    banned = 0
    total = len(member_ids)
    flood_count = 0
    
    for member_id in member_ids:
        try:
            await client.ban_chat_member(chat_id, member_id)
            banned += 1
            
            if banned % 100 == 0:
                print(f"💀 Worker {worker_id + 1}: {banned}/{total}")
                
        except Exception as e:
            error = str(e)
            if "FLOOD_WAIT" in error:
                flood_count += 1
                wait_time = int(re.search(r"(\d+)", error).group(1))
                print(f"🌊 Worker {worker_id + 1}: Flood wait {wait_time}s")
                await asyncio.sleep(wait_time)
                try:
                    await client.ban_chat_member(chat_id, member_id)
                    banned += 1
                except:
                    pass
            else:
                continue
    
    await client.stop()
    return banned, flood_count

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    await message.reply_text(
        f"💀 DESTROY MODE BOT 💀\n\n"
        f"Send your Pyrogram session string\n"
        f"Then: /destroy group_link_or_id\n\n"
        f"Workers: {WORKER_COUNT}"
    )

@app.on_message(filters.private & filters.command("destroy"))
async def destroy_command(client, message):
    user_id = message.from_user.id
    
    if user_id in processing_users and processing_users.get(user_id):
        await message.reply_text("⏳ Already running...")
        return
    
    if user_id not in temp_sessions:
        await message.reply_text("❌ Send session string first")
        return
    
    if len(message.command) < 2:
        await message.reply_text("❌ /destroy group_link_or_id")
        return
    
    processing_users[user_id] = True
    session_string = temp_sessions[user_id]
    chat_input = message.command[1]
    
    status_msg = await message.reply_text(f"💀 STARTING...")
    
    user_client = None
    chat_id = None
    chat_title = None
    
    try:
        user_client = Client("user", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await user_client.start()
        
        me = await user_client.get_me()
        await status_msg.edit_text(f"✅ Logged in: {me.first_name}\n\n🔍 Accessing group...")
        
        # Extract invite code from private link
        if "t.me/+" in chat_input:
            invite_code = chat_input.split("t.me/+")[-1]
            await status_msg.edit_text(f"🔗 Joining group...")
            
            # WAHI PURANA TARIKA - Direct join_chat
            try:
                chat = await user_client.join_chat(invite_code)
                chat_id = chat.id
                chat_title = chat.title
                await status_msg.edit_text(f"✅ Joined: {chat_title}")
            except Exception as e:
                if "ALREADY_PARTICIPANT" in str(e):
                    await status_msg.edit_text(f"✅ Already member, fetching info...")
                    # Get chat by invite code
                    chat = await user_client.get_chat(invite_code)
                    chat_id = chat.id
                    chat_title = chat.title
                else:
                    await status_msg.edit_text(f"❌ Join failed: {str(e)[:100]}")
                    return
        
        elif "t.me/" in chat_input:
            username = chat_input.split("t.me/")[-1]
            chat = await user_client.get_chat(username)
            chat_id = chat.id
            chat_title = chat.title
            await status_msg.edit_text(f"✅ Found: {chat_title}")
        
        elif chat_input.lstrip("-").isdigit():
            chat_id = int(chat_input)
            chat = await user_client.get_chat(chat_id)
            chat_title = chat.title
            await status_msg.edit_text(f"✅ Found: {chat_title}")
        
        else:
            await status_msg.edit_text("❌ Invalid format")
            return
        
        await status_msg.edit_text(f"👑 Checking admin...")
        
        member = await user_client.get_chat_member(chat_id, me.id)
        
        if member.status == ChatMemberStatus.OWNER:
            await status_msg.edit_text(f"✅ Owner")
        elif member.status == ChatMemberStatus.ADMINISTRATOR:
            if member.privileges and member.privileges.can_restrict_members:
                await status_msg.edit_text(f"✅ Admin with ban power")
            else:
                await status_msg.edit_text("❌ No ban permission")
                return
        else:
            await status_msg.edit_text(f"❌ Not admin")
            return
        
        await status_msg.edit_text(f"📥 Fetching members...")
        
        member_ids = []
        async for member_obj in user_client.get_chat_members(chat_id):
            if member_obj.user.id != me.id:
                member_ids.append(member_obj.user.id)
        
        await user_client.stop()
        user_client = None
        
        total = len(member_ids)
        
        if total == 0:
            await status_msg.edit_text("✅ No members to ban")
            return
        
        await status_msg.edit_text(
            f"💀 DESTROY STARTED 💀\n\n"
            f"Group: {chat_title}\n"
            f"Members: {total}\n"
            f"Workers: {WORKER_COUNT}\n"
            f"Will continue until all banned!\n\n"
            f"🔥 BANNING..."
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
                task = destroy_worker(chat_id, chunk, i, session_string)
                tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        total_banned = sum(r[0] for r in results)
        total_floods = sum(r[1] for r in results)
        elapsed = time.time() - start_time
        
        await status_msg.edit_text(
            f"💀 GROUP DESTROYED 💀\n\n"
            f"✅ Banned: {total_banned}/{total}\n"
            f"⏱️ Time: {elapsed/60:.2f} minutes\n"
            f"⚡ Speed: {total_banned/elapsed:.1f} bans/sec"
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
    
    if processing_users.get(user_id):
        return
    
    session_string = message.text.strip()
    
    if len(session_string) < 30:
        await message.reply_text("❌ Invalid session")
        return
    
    validation_msg = await message.reply_text("🔄 Validating...")
    
    is_valid, result = await validate_session(session_string, API_ID, API_HASH)
    
    if not is_valid:
        await validation_msg.edit_text(f"❌ Invalid: {str(result)[:100]}")
        return
    
    temp_sessions[user_id] = session_string
    
    await validation_msg.edit_text(
        f"✅ SESSION READY!\n\n"
        f"👤 Account: {result.first_name}\n"
        f"🆔 User ID: {result.id}\n"
        f"🔧 Workers: {WORKER_COUNT}\n\n"
        f"📌 Now send:\n/destroy https://t.me/+YOUR_INVITE_CODE\n\n"
        f"⚠️ Account must be ADMIN in target group"
    )

if __name__ == "__main__":
    print(f"🔥 DESTROY MODE BOT WITH {WORKER_COUNT} WORKERS")
    app.run()
