import asyncio
import re
import os
import time
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
WORKER_COUNT = int(os.getenv("WORKER_COUNT", 10))

temp_sessions = {}
processing_users = {}

app = Client("ban_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

async def validate_session(session_string):
    try:
        client = Client("test", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await client.start()
        me = await client.get_me()
        await client.stop()
        return True, me
    except Exception as e:
        return False, str(e)

async def ban_worker(chat_id, member_ids, worker_id, session_string):
    client = Client(f"w_{worker_id}", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
    await client.start()
    
    banned = 0
    total = len(member_ids)
    
    for member_id in member_ids:
        try:
            await client.ban_chat_member(chat_id, member_id)
            banned += 1
            if banned % 50 == 0:
                print(f"Worker {worker_id+1}: {banned}/{total}")
        except Exception as e:
            if "FLOOD_WAIT" in str(e):
                wait = int(re.search(r"(\d+)", str(e)).group(1))
                await asyncio.sleep(wait)
                try:
                    await client.ban_chat_member(chat_id, member_id)
                    banned += 1
                except:
                    pass
            continue
    
    await client.stop()
    return banned

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    await message.reply_text(
        "💀 PRIVATE GROUP DESTROYER 💀\n\n"
        "1. Send your Pyrogram session string\n"
        "2. Send private invite link\n\n"
        "Example: https://t.me/+abc123xyz"
    )

@app.on_message(filters.private & filters.command("destroy"))
async def destroy(client, message):
    user_id = message.from_user.id
    
    if processing_users.get(user_id):
        await message.reply_text("Already running...")
        return
    
    if user_id not in temp_sessions:
        await message.reply_text("Send session string first")
        return
    
    if len(message.command) < 2:
        await message.reply_text("Send: /destroy https://t.me/+invitecode")
        return
    
    processing_users[user_id] = True
    session_string = temp_sessions[user_id]
    invite_link = message.command[1]
    
    msg = await message.reply_text("💀 STARTING...")
    
    try:
        # Extract invite code
        if "t.me/+" in invite_link:
            invite_code = invite_link.split("t.me/+")[-1].strip()
        else:
            invite_code = invite_link.strip()
        
        await msg.edit_text(f"🔗 Joining: {invite_code}")
        
        user = Client("user", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await user.start()
        
        me = await user.get_me()
        
        # Join group
        try:
            chat = await user.join_chat(invite_code)
            chat_id = chat.id
            chat_title = chat.title
            await msg.edit_text(f"✅ Joined: {chat_title}")
        except Exception as e:
            if "ALREADY_PARTICIPANT" in str(e):
                chat = await user.get_chat(invite_code)
                chat_id = chat.id
                chat_title = chat.title
                await msg.edit_text(f"✅ Already member: {chat_title}")
            else:
                await msg.edit_text(f"❌ Join failed: {str(e)[:100]}")
                return
        
        # Check admin
        member = await user.get_chat_member(chat_id, me.id)
        
        if member.status == ChatMemberStatus.OWNER:
            await msg.edit_text(f"✅ Owner detected")
        elif member.status == ChatMemberStatus.ADMINISTRATOR:
            if member.privileges and member.privileges.can_restrict_members:
                await msg.edit_text(f"✅ Admin with ban power")
            else:
                await msg.edit_text("❌ No ban permission")
                return
        else:
            await msg.edit_text(f"❌ Not admin")
            return
        
        # Get members
        await msg.edit_text(f"📥 Fetching members...")
        
        members = []
        async for m in user.get_chat_members(chat_id):
            if m.user.id != me.id:
                members.append(m.user.id)
        
        await user.stop()
        
        total = len(members)
        
        if total == 0:
            await msg.edit_text("No members to ban")
            return
        
        await msg.edit_text(f"💀 DESTROYING {total} MEMBERS with {WORKER_COUNT} workers 💀")
        
        # Split members
        chunk_size = total // WORKER_COUNT
        chunks = []
        for i in range(WORKER_COUNT):
            start = i * chunk_size
            end = start + chunk_size if i < WORKER_COUNT - 1 else total
            if start < total:
                chunks.append(members[start:end])
        
        # Start workers
        tasks = []
        for i, chunk in enumerate(chunks):
            if chunk:
                tasks.append(ban_worker(chat_id, chunk, i, session_string))
        
        start_time = time.time()
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start_time
        
        total_banned = sum(results)
        
        await msg.edit_text(
            f"💀 GROUP DESTROYED 💀\n\n"
            f"Banned: {total_banned}/{total}\n"
            f"Time: {elapsed/60:.1f} minutes\n"
            f"Speed: {total_banned/elapsed:.1f} bans/sec"
        )
        
    except Exception as e:
        await msg.edit_text(f"Error: {str(e)[:200]}")
    finally:
        processing_users[user_id] = False

@app.on_message(filters.private & filters.text & ~filters.command(["start", "destroy"]))
async def save_session(client, message):
    user_id = message.from_user.id
    
    session_string = message.text.strip()
    
    if len(session_string) < 30:
        await message.reply_text("Invalid session string")
        return
    
    msg = await message.reply_text("Validating...")
    
    valid, result = await validate_session(session_string)
    
    if not valid:
        await msg.edit_text(f"Invalid session: {result[:100]}")
        return
    
    temp_sessions[user_id] = session_string
    
    await msg.edit_text(
        f"✅ Session ready!\n"
        f"Account: {result.first_name}\n\n"
        f"Now send:\n/destroy https://t.me/+YOUR_INVITE_CODE"
    )

if __name__ == "__main__":
    print(f"🔥 PRIVATE GROUP DESTROYER - {WORKER_COUNT} workers")
    app.run()
