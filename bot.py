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

async def get_chat_id_and_title(user_client, chat_input, status_msg):
    """
    Detects and joins group from various input formats
    Returns: (chat_id, chat_title) or (None, error_message)
    """
    
    chat_input = chat_input.strip()
    
    # 1. PRIVATE INVITE LINK (t.me/+)
    if "t.me/+" in chat_input:
        # Extract invite hash
        if "t.me/+" in chat_input:
            parts = chat_input.split("t.me/+")
            invite_hash = parts[-1].split()[0].split("?")[0]
        
        await status_msg.edit_text(f"🔗 Joining private group with invite link...")
        
        try:
            # Try to join using the invite hash
            chat = await user_client.join_chat(invite_hash)
            return chat.id, chat.title
            
        except Exception as e:
            error_str = str(e)
            
            # If already a member
            if "USER_ALREADY_PARTICIPANT" in error_str:
                await status_msg.edit_text(f"✅ Already a member, searching group...")
                
                # Search in user's dialogs
                async for dialog in user_client.get_dialogs():
                    if dialog.chat.invite_link and invite_hash in dialog.chat.invite_link:
                        return dialog.chat.id, dialog.chat.title
                
                # Try to get by username pattern
                try:
                    # Some private groups might be accessible via username
                    async for dialog in user_client.get_dialogs():
                        if "t.me/+" not in str(dialog.chat.invite_link) and dialog.chat.username:
                            continue
                        return dialog.chat.id, dialog.chat.title
                except:
                    pass
                
                return None, "Already member but cannot locate chat. Please send a message in the group and try again."
            
            elif "INVITE_HASH_INVALID" in error_str:
                return None, "Invalid invite link. Link may be expired."
            
            elif "USER_ALREADY_PARTICIPANT" not in error_str:
                return None, f"Cannot join: {error_str[:100]}"
            
            else:
                return None, f"Join failed: {error_str[:100]}"
    
    # 2. PUBLIC USERNAME (t.me/username)
    elif "t.me/" in chat_input and "+" not in chat_input:
        username = chat_input.split("t.me/")[-1].split()[0].split("?")[0]
        await status_msg.edit_text(f"🔍 Accessing public group...")
        
        try:
            chat = await user_client.get_chat(username)
            return chat.id, chat.title
        except Exception as e:
            return None, f"Cannot find group: {str(e)[:100]}"
    
    # 3. DIRECT NUMERIC ID
    elif chat_input.lstrip("-").isdigit():
        chat_id = int(chat_input)
        await status_msg.edit_text(f"🔍 Getting group by ID...")
        
        try:
            chat = await user_client.get_chat(chat_id)
            return chat.id, chat.title
        except Exception as e:
            return None, f"Cannot access chat: {str(e)[:100]}"
    
    # 4. JUST THE INVITE HASH (without t.me)
    elif len(chat_input) >= 10 and not chat_input.startswith("http") and "+" in chat_input:
        # Might be just the hash part
        invite_hash = chat_input.split()[0]
        await status_msg.edit_text(f"🔗 Trying to join with invite hash...")
        
        try:
            chat = await user_client.join_chat(invite_hash)
            return chat.id, chat.title
        except Exception as e:
            return None, f"Cannot join: {str(e)[:100]}"
    
    else:
        return None, "Invalid format. Use:\n• https://t.me/+invitecode\n• https://t.me/username\n• -100123456789"

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    await message.reply_text(
        f"💀 DESTROY MODE BOT 💀\n\n"
        f"⚡ Workers: {WORKER_COUNT}\n\n"
        f"📌 How to use:\n"
        f"1. Send your Pyrogram session string\n"
        f"2. Then send: /destroy group_link_or_id\n\n"
        f"📎 Supported formats:\n"
        f"• https://t.me/+invitecode (private)\n"
        f"• https://t.me/username (public)\n"
        f"• -100123456789 (group ID)\n\n"
        f"⚠️ Your account must be admin in the group"
    )

@app.on_message(filters.private & filters.command("destroy"))
async def destroy_command(client, message):
    user_id = message.from_user.id
    
    if user_id in processing_users and processing_users[user_id]:
        await message.reply_text("⏳ Destroy already in progress...")
        return
    
    if user_id not in temp_sessions:
        await message.reply_text("❌ Send your session string first\nUse /start for help")
        return
    
    if len(message.command) < 2:
        await message.reply_text("❌ Usage: /destroy group_link_or_id\n\nExample:\n/destroy https://t.me/+CepS41S6LWA3YTQ1")
        return
    
    processing_users[user_id] = True
    session_string = temp_sessions[user_id]
    chat_input = message.command[1]
    
    status_msg = await message.reply_text(f"💀 INITIALIZING DESTROY MODE...")
    
    user_client = None
    chat_id = None
    chat_title = None
    
    try:
        # Start user client
        user_client = Client("user", session_string=session_string, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await user_client.start()
        
        # Get user info
        me = await user_client.get_me()
        await status_msg.edit_text(f"✅ Logged in as: {me.first_name}\n\n📎 Processing group link...")
        
        # Detect and join group
        chat_id, chat_title = await get_chat_id_and_title(user_client, chat_input, status_msg)
        
        if chat_id is None:
            await status_msg.edit_text(f"❌ {chat_title}")
            return
        
        await status_msg.edit_text(f"✅ Group found: {chat_title}\n\n👑 Checking admin permissions...")
        
        # Check if user is admin/owner
        try:
            member = await user_client.get_chat_member(chat_id, me.id)
        except Exception as e:
            await status_msg.edit_text(f"❌ Cannot check admin status: {str(e)[:100]}\n\nMake sure you are a member of this group")
            return
        
        # Verify permissions
        if member.status == ChatMemberStatus.OWNER:
            await status_msg.edit_text(f"✅ You are the GROUP OWNER - Full access granted")
        elif member.status == ChatMemberStatus.ADMINISTRATOR:
            if member.privileges and member.privileges.can_restrict_members:
                await status_msg.edit_text(f"✅ You are ADMIN with ban permission")
            else:
                await status_msg.edit_text("❌ You are admin but NO BAN PERMISSION\n\nAsk group owner to give you ban rights")
                return
        else:
            await status_msg.edit_text(f"❌ You are NOT an admin in this group\n\nCurrent status: {member.status}\n\nMake your account admin first")
            return
        
        await status_msg.edit_text(f"📥 Fetching member list from {chat_title}...\n⏳ This may take a while for large groups...")
        
        # Fetch all members except bot itself
        member_ids = []
        async for member_obj in user_client.get_chat_members(chat_id):
            if member_obj.user.id != me.id:  # Don't ban yourself
                member_ids.append(member_obj.user.id)
        
        # Stop user client (workers will use their own)
        await user_client.stop()
        user_client = None
        
        total = len(member_ids)
        
        if total == 0:
            await status_msg.edit_text("✅ No members to ban (only you in the group)")
            return
        
        await status_msg.edit_text(
            f"💀 DESTROY MODE ENGAGED 💀\n\n"
            f"📛 Group: {chat_title}\n"
            f"👥 Members to ban: {total}\n"
            f"🔧 Workers: {WORKER_COUNT}\n"
            f"⚠️ This action is IRREVERSIBLE!\n\n"
            f"🔥 Starting destruction in 3 seconds..."
        )
        
        await asyncio.sleep(3)
        
        await status_msg.edit_text(
            f"💀 DESTROYING {chat_title} 💀\n\n"
            f"👥 Total: {total} members\n"
            f"⚡ Workers: {WORKER_COUNT}\n\n"
            f"🔄 Progress: 0/{total} (0%)"
        )
        
        # Split members into chunks for workers
        chunk_size = max(1, total // WORKER_COUNT)
        chunks = []
        for i in range(WORKER_COUNT):
            start_idx = i * chunk_size
            end_idx = start_idx + chunk_size if i < WORKER_COUNT - 1 else total
            if start_idx < total:
                chunks.append(member_ids[start_idx:end_idx])
        
        start_time = time.time()
        
        # Start worker tasks
        tasks = []
        for i, chunk in enumerate(chunks):
            if len(chunk) > 0:
                task = destroy_worker(chat_id, chunk, i, session_string)
                tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        total_banned = sum(r[0] for r in results)
        total_floods = sum(r[1] for r in results)
        elapsed = time.time() - start_time
        
        # Final result
        await status_msg.edit_text(
            f"💀 GROUP DESTROYED SUCCESSFULLY 💀\n\n"
            f"📛 Group: {chat_title}\n"
            f"✅ Banned: {total_banned}/{total}\n"
            f"⏱️ Time: {elapsed/60:.2f} minutes ({elapsed:.1f} seconds)\n"
            f"⚡ Speed: {total_banned/elapsed:.1f} bans/second\n"
            f"🌊 Flood waits: {total_floods}\n"
            f"🔧 Workers used: {WORKER_COUNT}\n\n"
            f"💀 DESTROY COMPLETE 💀"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ ERROR: {str(e)[:300]}\n\nPlease check:\n1. Session string is valid\n2. Account is admin in group\n3. Group link is correct")
    finally:
        if user_client:
            try:
                await user_client.stop()
            except:
                pass
        processing_users[user_id] = False
        # Don't delete session, keep for reuse

@app.on_message(filters.private & filters.text & ~filters.command(["start", "destroy"]))
async def save_session(client, message):
    user_id = message.from_user.id
    
    if user_id in processing_users and processing_users[user_id]:
        await message.reply_text("⏳ Please wait, destroy in progress...")
        return
    
    session_string = message.text.strip()
    
    if len(session_string) < 30:
        await message.reply_text("❌ Invalid session string (too short)\n\nGet your session from https://my.telegram.org")
        return
    
    validation_msg = await message.reply_text("🔄 Validating session string...")
    
    is_valid, result = await validate_session(session_string, API_ID, API_HASH)
    
    if not is_valid:
        await validation_msg.edit_text(f"❌ Invalid session: {str(result)[:100]}\n\nPlease generate a new Pyrogram session string")
        return
    
    temp_sessions[user_id] = session_string
    
    await validation_msg.edit_text(
        f"✅ SESSION READY!\n\n"
        f"👤 Account: {result.first_name}\n"
        f"🆔 User ID: {result.id}\n"
        f"🔧 Workers: {WORKER_COUNT}\n\n"
        f"📌 Now send:\n/destroy https://t.me/+invitecode\n\n"
        f"⚠️ Make sure your account is ADMIN in the target group!"
    )

if __name__ == "__main__":
    app.run()
