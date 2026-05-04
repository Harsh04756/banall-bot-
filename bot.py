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

print(f"🔥 DESTROY MODE BOT STARTED WITH {WORKER_COUNT} WORKERS")

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
    
    for idx, member_id in enumerate(member_ids):
        try:
            await client.ban_chat_member(chat_id, member_id)
            banned += 1
            
            if banned % 50 == 0:
                print(f"💀 Worker {worker_id + 1}: {banned}/{total} banned")
                
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
        f"⚡ Workers: {WORKER_COUNT}\n\n"
        f"Send your Pyrogram session string\n"
        f"Then send: /destroy group_link_or_id\n\n"
        f"⚠️ Your account must be admin in the group"
    )

@app.on_message(filters.private & filters.command("destroy"))
async def destroy_command(client, message):
    user_id = message.from_user.id
    
    if user_id in processing_users and processing_users[user_id]:
        await message.reply_text("⏳ Destroy already in progress...")
        return
    
    if user_id not in temp_sessions:
        await message.reply_text("❌ Send your session string first")
        return
    
    if len(message.command) < 2:
        await message.reply_text("❌ /destroy group_link_or_id")
        return
    
    processing_users[user_id] = True
    session_string = temp_sessions[user_id]
    chat_input = message.command[1]
    
    status_msg = await message.reply_text(f"💀 INITIALIZING...")
    
    user_client = None
    chat_id = None
    chat_title = "Unknown"
    
    try:
        user_client = Client("user", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await user_client.start()
        
        me = await user_client.get_me()
        await status_msg.edit_text(f"✅ Logged in as: {me.first_name}\n\n🔍 Accessing group...")
        
        # Extract invite hash from private link
        if "t.me/+" in chat_input:
            invite_hash = chat_input.split("t.me/+")[-1]
            await status_msg.edit_text(f"🔗 Joining group using invite link...")
            
            try:
                # Join the group using the session
                chat = await user_client.join_chat(invite_hash)
                chat_id = chat.id
                chat_title = chat.title
                await status_msg.edit_text(f"✅ Joined group: {chat_title}")
            except Exception as e:
                error_str = str(e)
                if "USER_ALREADY_PARTICIPANT" in error_str:
                    await status_msg.edit_text(f"✅ Already a member, fetching group info...")
                    # Get chat by invite hash
                    try:
                        # Try to resolve via get_chat
                        chat = await user_client.get_chat(invite_hash)
                        chat_id = chat.id
                        chat_title = chat.title
                    except:
                        # Search in dialogs
                        async for dialog in user_client.get_dialogs():
                            if dialog.chat.invite_link and invite_hash in dialog.chat.invite_link:
                                chat_id = dialog.chat.id
                                chat_title = dialog.chat.title
                                break
                        if not chat_id:
                            await status_msg.edit_text(f"❌ Cannot find group. Please join manually first.")
                            return
                else:
                    await status_msg.edit_text(f"❌ Cannot join: {error_str[:100]}")
                    return
        
        # Public link or username
        elif "t.me/" in chat_input:
            username = chat_input.split("t.me/")[-1]
            await status_msg.edit_text(f"🔍 Getting group info...")
            try:
                chat = await user_client.get_chat(username)
                chat_id = chat.id
                chat_title = chat.title
                await status_msg.edit_text(f"✅ Found group: {chat_title}")
            except Exception as e:
                await status_msg.edit_text(f"❌ Cannot find group: {str(e)[:100]}")
                return
        
        # Direct ID
        elif chat_input.lstrip("-").isdigit():
            chat_id = int(chat_input)
            chat = await user_client.get_chat(chat_id)
            chat_title = chat.title
            await status_msg.edit_text(f"✅ Found group: {chat_title}")
        
        else:
            await status_msg.edit_text("❌ Invalid format. Use: /destroy https://t.me/+invitecode")
            return
        
        await status_msg.edit_text(f"👑 Checking admin permissions in {chat_title}...")
        
        try:
            member = await user_client.get_chat_member(chat_id, me.id)
        except Exception as e:
            await status_msg.edit_text(f"❌ Cannot check admin: {str(e)[:100]}\n\nMake sure you are a member of the group")
            return
        
        if member.status == ChatMemberStatus.OWNER:
            await status_msg.edit_text(f"✅ You are GROUP OWNER")
        elif member.status == ChatMemberStatus.ADMINISTRATOR:
            if member.privileges and member.privileges.can_restrict_members:
                await status_msg.edit_text(f"✅ You are ADMIN with ban permission")
            else:
                await status_msg.edit_text("❌ You are admin but NO BAN PERMISSION")
                return
        else:
            await status_msg.edit_text(f"❌ You are NOT admin\n\nStatus: {member.status}\n\nMake your account admin first")
            return
        
        await status_msg.edit_text(f"📥 Fetching member list...")
        
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
            f"💀 DESTROY MODE ENGAGED 💀\n\n"
            f"📛 Group: {chat_title}\n"
            f"👥 Members: {total}\n"
            f"🔧 Workers: {WORKER_COUNT}\n\n"
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
        await message.reply_text("❌ Invalid session string")
        return
    
    validation_msg = await message.reply_text("🔄 Validating...")
    
    is_valid, result = await validate_session(session_string, API_ID, API_HASH)
    
    if not is_valid:
        await validation_msg.edit_text(f"❌ Invalid: {str(result)[:100]}")
        return
    
    temp_sessions[user_id] = session_string
    
    await validation_msg.edit_text(
        f"✅ Session ready!\n\n"
        f"👤 Account: {result.first_name}\n"
        f"🔧 Workers: {WORKER_COUNT}\n\n"
        f"Send: /destroy https://t.me/+invitecode"
    )

if __name__ == "__main__":
    app.run()
