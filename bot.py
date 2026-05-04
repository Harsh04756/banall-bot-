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
print("⚠️ Bot does NOT need to be in group. User session will do everything.")

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
    client = Client(f"destroy_w_{worker_id}", session_string=session_string, 
                   api_id=API_ID, api_hash=API_HASH, in_memory=True)
    await client.start()
    
    banned = 0
    total = len(member_ids)
    flood_count = 0
    
    print(f"🔥 Worker {worker_id + 1}: Started, {total} members to ban")
    
    for idx, member_id in enumerate(member_ids):
        try:
            await client.ban_chat_member(chat_id, member_id)
            banned += 1
            
            if banned % 100 == 0:
                print(f"💀 Worker {worker_id + 1}: {banned}/{total} banned")
                await status_callback(f"Worker {worker_id + 1}: {banned}/{total}")
                
        except Exception as e:
            error = str(e)
            
            if "FLOOD_WAIT" in error:
                flood_count += 1
                wait_time = int(re.search(r"(\d+)", error).group(1))
                print(f"🌊 Worker {worker_id + 1}: Flood wait {wait_time}s (#{flood_count})")
                print(f"💀 Waiting then continuing...")
                await asyncio.sleep(wait_time)
                try:
                    await client.ban_chat_member(chat_id, member_id)
                    banned += 1
                except:
                    pass
                    
            elif "USER_ID_INVALID" in error or "USER_NOT_PARTICIPANT" in error:
                continue
            else:
                print(f"⚠️ Worker {worker_id + 1}: {error[:50]}")
                await asyncio.sleep(1)
    
    await client.stop()
    print(f"✅ Worker {worker_id + 1}: Completed, banned {banned} members")
    return banned, flood_count

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    await message.reply_text(
        f"💀 DESTROY MODE BOT 💀\n\n"
        f"⚡ Workers: {WORKER_COUNT}\n"
        f"🔥 Speed: {WORKER_COUNT*5}-{WORKER_COUNT*7} bans/sec\n"
        f"🤖 Bot does NOT need to be in group\n"
        f"👤 Your user account session will do the banning\n\n"
        f"Step 1: Send your Pyrogram session string\n"
        f"Step 2: Send /destroy group_link_or_id\n\n"
        f"⚠️ Your account must be ADMIN with BAN permission"
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
        await message.reply_text("❌ /destroy group_link_or_id\n\nExample: /destroy https://t.me/yourgroup")
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
        await status_msg.edit_text(f"✅ Logged in as: {me.first_name}\n\n🔍 Accessing group with your account...")
        
        chat_id = extract_chat_id(chat_input)
        
        if not chat_id:
            await status_msg.edit_text("❌ Invalid group link or ID")
            return
        
        # Try to get chat info using user session
        try:
            if str(chat_id).lstrip("-").isdigit():
                chat = await user_client.get_chat(int(chat_id))
            else:
                chat = await user_client.get_chat(chat_id)
        except Exception as e:
            error_msg = str(e)
            if "USER_NOT_PARTICIPANT" in error_msg:
                await status_msg.edit_text(
                    f"❌ Your account is NOT a member of this group\n\n"
                    f"Solution: Join the group with your Telegram account first\n"
                    f"Then try again\n\n"
                    f"Group: {chat_input}"
                )
                return
            else:
                await status_msg.edit_text(f"❌ Cannot access group: {error_msg[:100]}")
                return
        
        await status_msg.edit_text(f"✅ Group: {chat.title}\n👑 Checking admin permission...")
        
        try:
            member = await user_client.get_chat_member(chat.id, me.id)
        except Exception as e:
            await status_msg.edit_text(f"❌ Cannot verify admin status: {str(e)[:100]}\n\nMake sure your account is admin in the group")
            return
        
        if member.status == ChatMemberStatus.OWNER:
            has_ban_right = True
            await status_msg.edit_text(f"✅ You are GROUP OWNER - Full access")
        elif member.status == ChatMemberStatus.ADMINISTRATOR:
            if member.privileges and member.privileges.can_restrict_members:
                has_ban_right = True
                await status_msg.edit_text(f"✅ You are ADMIN with ban permission")
            else:
                await status_msg.edit_text("❌ You are admin but NO BAN PERMISSION")
                return
        else:
            await status_msg.edit_text(f"❌ You are NOT admin\n\nStatus: {member.status}\n\nMake your account admin in the group first")
            return
        
        await status_msg.edit_text(f"📥 Fetching member list using your account...")
        
        member_ids = []
        async for member_obj in user_client.get_chat_members(chat.id):
            if member_obj.user.id != me.id:
                member_ids.append(member_obj.user.id)
        
        await user_client.stop()
        user_client = None
        
        total = len(member_ids)
        
        if total == 0:
            await status_msg.edit_text("✅ No members to ban (only you in group)")
            return
        
        await status_msg.edit_text(
            f"💀 DESTROY MODE ENGAGED 💀\n\n"
            f"Group: {chat.title}\n"
            f"Members to destroy: {total}\n"
            f"Workers: {WORKER_COUNT}\n"
            f"Bot: NOT in group (your account is admin)\n"
            f"Flood waits: Will auto-resume\n\n"
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
                task = destroy_worker(chat.id, chunk, i, session_string, status_msg.edit_text)
                tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        total_banned = sum(r[0] for r in results)
        total_floods = sum(r[1] for r in results)
        elapsed = time.time() - start_time
        
        avg_speed = total_banned / elapsed if elapsed > 0 else 0
        
        await status_msg.edit_text(
            f"💀 GROUP DESTROYED 💀\n\n"
            f"✅ Banned: {total_banned}/{total}\n"
            f"⏱️ Time: {elapsed/60:.2f} minutes ({elapsed:.0f} seconds)\n"
            f"⚡ Speed: {avg_speed:.1f} bans/sec\n"
            f"🌊 Flood waits survived: {total_floods}\n"
            f"🤖 Bot was never in group - Your account did everything"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)[:200]}")
        print(f"Error: {e}")
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
        await message.reply_text("❌ Invalid session string\n\nGet from: telegram.tools/session-string-generator")
        return
    
    validation_msg = await message.reply_text("🔄 Validating session...")
    
    is_valid, result = await validate_session(session_string, API_ID, API_HASH)
    
    if not is_valid:
        await validation_msg.edit_text(f"❌ Invalid session: {str(result)[:100]}")
        return
    
    temp_sessions[user_id] = session_string
    
    await validation_msg.edit_text(
        f"✅ Session ready!\n\n"
        f"👤 Account: {result.first_name} (@{result.username or 'no username'})\n"
        f"🔧 Workers: {WORKER_COUNT}\n"
        f"🤖 Bot does NOT need to be in group\n\n"
        f"Send: /destroy group_link_or_id\n\n"
        f"⚠️ Your account must be ADMIN in the target group"
    )

if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"💀 DESTROY MODE BOT")
    print(f"Workers: {WORKER_COUNT}")
    print(f"Bot does NOT need to be in group")
    print(f"Your user session will do the banning")
    print(f"{'='*50}\n")
    app.run()
