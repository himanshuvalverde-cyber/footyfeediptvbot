from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import os
import json
import time
import hashlib
import random
import string
import aiohttp
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
import nest_asyncio
import threading

load_dotenv()
nest_asyncio.apply()

# ========== CONFIG ==========
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMINS = list(map(int, os.environ.get("ADMINS", "").split()))
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1003675965422"))

# Link Shortner API (vplink.in)
SHORTNER_API = os.environ.get("SHORTNER_API", "")
SHORTNER_BASE_URL = os.environ.get("SHORTNER_BASE_URL", "https://vplink.in/api")

# Playlist Server URL
PLAYLIST_URL = os.environ.get("PLAYLIST_URL", "https://playlist-p1tc.onrender.com")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "admin123")

print(f"📡 BOT_TOKEN: {BOT_TOKEN[:10]}...")
print(f"🎶 Playlist URL: {PLAYLIST_URL}")
print(f"🔑 Shortner API: {'✅ Set' if SHORTNER_API else '❌ Not Set'}")

# ========== BOT ==========
app = Client(
    "M3UBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ========== DATA STORAGE ==========
users_data = {}
pending_verifications = {}
DATA_FILE = "users_data.json"
PENDING_FILE = "pending_verifications.json"

def load_data():
    global users_data
    try:
        with open(DATA_FILE, "r") as f:
            users_data = json.load(f)
    except:
        users_data = {}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(users_data, f)

def load_pending():
    global pending_verifications
    try:
        with open(PENDING_FILE, "r") as f:
            pending_verifications = json.load(f)
    except:
        pending_verifications = {}

def save_pending():
    with open(PENDING_FILE, "w") as f:
        json.dump(pending_verifications, f)

load_data()
load_pending()

# ========== HELPER FUNCTIONS ==========

def generate_uid():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))

def generate_short_code():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

def get_expiry_date(days=7):
    return int((datetime.now() + timedelta(days=days)).timestamp())

def get_expiry_days_left(timestamp):
    if not timestamp:
        return 0
    remaining = timestamp - int(datetime.now().timestamp())
    if remaining <= 0:
        return 0
    return remaining // 86400

# ========== SHORTNER FUNCTIONS ==========

async def create_short_link(original_url):
    """Create short link using vplink.in API"""
    if not SHORTNER_API:
        print("⚠️ SHORTNER_API not set! Using original URL.")
        return original_url
    
    try:
        encoded_url = original_url.replace("&", "%26").replace("?", "%3F")
        api_url = f"{SHORTNER_BASE_URL}?api={SHORTNER_API}&url={encoded_url}&format=text"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=10) as response:
                if response.status == 200:
                    result = await response.text()
                    result = result.strip()
                    if result and result.startswith('http'):
                        return result
        return original_url
    except Exception as e:
        print(f"❌ Shortner exception: {e}")
        return original_url

# ========== PLAYLIST API FUNCTIONS ==========

async def create_user_on_server(uid, password, days=7):
    """Create a user on the playlist server"""
    try:
        create_url = f"{PLAYLIST_URL}/admin/create?key={ADMIN_KEY}&uid={uid}&pass={password}&days={days}"
        print(f"🔗 Creating user: {create_url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(create_url, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"✅ Server response: {data}")
                    if data.get("status") == "success":
                        return {"success": True, "data": data}
                    else:
                        return {"success": False, "error": data.get("error", "Unknown error")}
                else:
                    return {"success": False, "error": f"Server returned {response.status}"}
    except Exception as e:
        print(f"❌ Create user error: {e}")
        return {"success": False, "error": str(e)}

async def create_custom_user_on_server(uid, password, days=7):
    """Create a user on the playlist server using custom endpoint"""
    try:
        create_url = f"{PLAYLIST_URL}/admin/create-custom?key={ADMIN_KEY}&uid={uid}&pass={password}&days={days}"
        print(f"🔗 Creating custom user: {create_url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(create_url, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"✅ Custom create response: {data}")
                    if data.get("status") == "success":
                        return {"success": True, "data": data}
                    else:
                        return {"success": False, "error": data.get("error", "Unknown error")}
                else:
                    return {"success": False, "error": f"Server returned {response.status}"}
    except Exception as e:
        print(f"❌ Custom create error: {e}")
        return {"success": False, "error": str(e)}

async def extend_playlist_on_server(uid, password):
    """Extend user's playlist on the server"""
    try:
        extend_url = f"{PLAYLIST_URL}/extend?uid={uid}&pass={password}"
        print(f"🔗 Extending playlist: {extend_url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(extend_url, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        return {
                            "success": True,
                            "new_expiry": data.get("new_expiry"),
                            "days_left": data.get("days_left")
                        }
                    else:
                        return {"success": False, "error": data.get("error", "Unknown error")}
                else:
                    return {"success": False, "error": f"Server returned {response.status}"}
    except Exception as e:
        print(f"❌ Extend error: {e}")
        return {"success": False, "error": str(e)}

# ========== COMMANDS ==========

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    user = message.from_user
    user_id = str(user.id)
    first_name = user.first_name or "User"
    
    # Check for verification callback
    if len(message.text.split()) > 1:
        args = message.text.split()[1]
        if args.startswith("verify_"):
            short_code = args.replace("verify_", "")
            await process_verification(client, message, short_code)
            return
    
    # Check if user already has a playlist
    if user_id in users_data:
        days_left = get_expiry_days_left(users_data[user_id].get("expiry", 0))
        if days_left > 0:
            uid = users_data[user_id].get("uid")
            password = users_data[user_id].get("password")
            playlist_url = f"{PLAYLIST_URL}/playlist.m3u?uid={uid}&pass={password}"
            
            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Extend Playlist", callback_data=f"extend_{uid}_{password}")],
                [InlineKeyboardButton("📥 Get Playlist", url=playlist_url)],
                [InlineKeyboardButton("📊 Status", callback_data="status")]
            ])
            
            await message.reply_text(
                f"🔄 **Your playlist is already active!**\n\n"
                f"📅 **Days remaining:** {days_left}\n"
                f"🔗 **Your Playlist:**\n`{playlist_url}`\n\n"
                f"⏳ **Expires in {days_left} days**",
                reply_markup=buttons,
                parse_mode=ParseMode.MARKDOWN
            )
            return
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Generate Playlist", callback_data="generate")],
        [InlineKeyboardButton("📢 Updates Channel", url="https://t.me/REPLAYBYFOOTYFEED")],
        [InlineKeyboardButton("💬 Support", url="https://t.me/valverdeae")]
    ])
    
    await message.reply_text(
        f"🚹 **Hello, {first_name}!**\n\n"
        f"🎶 **Generate Your Footy Feed Playlist**\n\n"
        f"• 🌟 Experience more than 2000 Indian Channels For FREE!\n"
        f"• 🆔 Playlist comes with LOGO and EPG Guide for all Channels!\n"
        f"• 🎤 All Channels will be Multi Audio and Multi Quality.\n"
        f"• 🚀 Bufferless Guaranteed.\n"
        f"• 📺 All Popular Indian channels!\n\n"
        f"👉 **Click the button below to generate your playlist!**",
        reply_markup=buttons,
        parse_mode=ParseMode.MARKDOWN
    )

@app.on_message(filters.command("generate") & filters.private)
async def generate_cmd(client, message):
    await process_generate(client, message)

@app.on_message(filters.command("extend") & filters.private)
async def extend_cmd(client, message):
    """Extend your playlist by 7 days"""
    user_id = str(message.from_user.id)
    
    if user_id not in users_data:
        await message.reply_text(
            "❌ **No active playlist found!**\n\n"
            "Please use /generate to create a playlist first.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    data = users_data[user_id]
    uid = data.get("uid")
    password = data.get("password")
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Extend", callback_data=f"extend_{uid}_{password}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="close")]
    ])
    
    await message.reply_text(
        f"🔄 **Extend Playlist**\n\n"
        f"Your playlist will be extended by **7 days**.\n\n"
        f"Click **Yes, Extend** to continue.",
        reply_markup=buttons,
        parse_mode=ParseMode.MARKDOWN
    )

@app.on_message(filters.command("status") & filters.private)
async def status_cmd(client, message):
    user_id = str(message.from_user.id)
    
    if user_id not in users_data:
        await message.reply_text(
            "❌ You don't have an active playlist. Use /generate to create one.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    data = users_data[user_id]
    days_left = get_expiry_days_left(data.get("expiry", 0))
    uid = data.get("uid", "Unknown")
    password = data.get("password", "Unknown")
    
    if days_left <= 0:
        await message.reply_text(
            f"❌ **Your playlist has expired!**\n\n"
            f"Please use /generate to get a new playlist.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    playlist_url = f"{PLAYLIST_URL}/playlist.m3u?uid={uid}&pass={password}"
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Extend Playlist", callback_data=f"extend_{uid}_{password}")],
        [InlineKeyboardButton("📥 Get Playlist", url=playlist_url)]
    ])
    
    await message.reply_text(
        f"📊 **Your Playlist Status**\n\n"
        f"📅 **Active:** {days_left} days remaining\n"
        f"🆔 **User ID:** `{uid}`\n"
        f"🔗 **Playlist URL:**\n`{playlist_url}`\n\n"
        f"⏳ **Expires on:** {datetime.fromtimestamp(data['expiry']).strftime('%Y-%m-%d %H:%M:%S')}",
        reply_markup=buttons,
        parse_mode=ParseMode.MARKDOWN
    )

@app.on_message(filters.command("admin") & filters.user(ADMINS))
async def admin_cmd(client, message):
    total_users = len(users_data)
    active_users = sum(1 for u in users_data.values() if u.get("expiry", 0) > int(datetime.now().timestamp()))
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users", callback_data="admin_users")],
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ])
    
    await message.reply_text(
        f"👑 **Admin Panel**\n\n"
        f"👥 **Total Users:** {total_users}\n"
        f"✅ **Active Users:** {active_users}\n"
        f"⏳ **Expired Users:** {total_users - active_users}\n\n"
        f"🔗 **Playlist Server:** {PLAYLIST_URL}\n"
        f"📢 **Channel:** {CHANNEL_ID}",
        reply_markup=buttons,
        parse_mode=ParseMode.MARKDOWN
    )

@app.on_message(filters.command("users") & filters.user(ADMINS))
async def users_cmd(client, message):
    """Show all users"""
    if not users_data:
        await message.reply_text("📋 No users found.")
        return
    
    response = "👥 **Users List**\n\n"
    for user_id, data in users_data.items():
        days_left = get_expiry_days_left(data.get("expiry", 0))
        status = "✅ Active" if days_left > 0 else "❌ Expired"
        response += f"• 🆔 `{user_id}`\n"
        response += f"  🔗 UID: `{data.get('uid')}`\n"
        response += f"  📅 {days_left} days left - {status}\n\n"
    
    await message.reply_text(response, parse_mode=ParseMode.MARKDOWN)

# ============================================================
# ✅ ADMIN APPROVE COMMAND
# ============================================================

@app.on_message(filters.command("approve") & filters.user(ADMINS))
async def approve_cmd(client, message):
    """Approve a user and give them playlist access (Admin only)"""
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.reply_text(
                "📤 **Approve User**\n\n"
                "Usage: /approve user_id [days]\n"
                "Example: /approve 123456789 7\n\n"
                "Or reply to a user's message with:\n"
                "/approve 7\n\n"
                "📌 Default days: 7",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        user_id = None
        days = 7
        
        if message.reply_to_message:
            user_id = str(message.reply_to_message.from_user.id)
            if len(args) > 1:
                try:
                    days = int(args[1])
                except:
                    pass
        else:
            user_id = args[1]
            if len(args) > 2:
                try:
                    days = int(args[2])
                except:
                    pass
        
        if not user_id:
            await message.reply_text("❌ Could not identify user.")
            return
        
        if user_id in users_data:
            await message.reply_text(f"✅ User `{user_id}` already has access!", parse_mode=ParseMode.MARKDOWN)
            return
        
        uid = generate_uid()
        password = generate_short_code()
        
        result = await create_custom_user_on_server(uid, password, days)
        
        if not result.get("success"):
            await message.reply_text(
                f"❌ Failed to create user on server!\n\nError: {result.get('error', 'Unknown error')}",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        expiry = get_expiry_date(days)
        playlist_url = f"{PLAYLIST_URL}/playlist.m3u?uid={uid}&pass={password}"
        
        users_data[user_id] = {
            "uid": uid,
            "password": password,
            "expiry": expiry,
            "created_at": int(datetime.now().timestamp()),
            "approved_by": str(message.from_user.id),
            "approved_at": int(datetime.now().timestamp())
        }
        save_data()
        
        # Notify the user
        try:
            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Get Playlist", url=playlist_url)],
                [InlineKeyboardButton("🔄 Extend", callback_data=f"extend_{uid}_{password}")],
                [InlineKeyboardButton("📊 Status", callback_data="status")]
            ])
            
            await client.send_message(
                chat_id=int(user_id),
                text=f"✅ **Congratulations! You have been approved!**\n\n"
                     f"🎉 Your playlist has been activated for **{days} days**!\n\n"
                     f"🔗 **Your Playlist URL:**\n`{playlist_url}`\n\n"
                     f"🆔 UID: `{uid}`\n"
                     f"🔑 Password: `{password}`\n"
                     f"📅 **Expires in {days} days**\n\n"
                     f"🔄 Use /extend to extend your playlist.",
                reply_markup=buttons,
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        
        await message.reply_text(
            f"✅ **User Approved!**\n\n"
            f"👤 User ID: `{user_id}`\n"
            f"🆔 UID: `{uid}`\n"
            f"🔑 Password: `{password}`\n"
            f"📅 Days: {days}\n"
            f"🔗 Playlist: `{playlist_url}`",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")

@app.on_message(filters.command("unapprove") & filters.user(ADMINS))
async def unapprove_cmd(client, message):
    """Remove a user's access (Admin only)"""
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.reply_text("Usage: /unapprove user_id", parse_mode=ParseMode.MARKDOWN)
            return
        
        user_id = args[1] if not message.reply_to_message else str(message.reply_to_message.from_user.id)
        
        if user_id not in users_data:
            await message.reply_text(f"❌ User `{user_id}` does not have access.", parse_mode=ParseMode.MARKDOWN)
            return
        
        del users_data[user_id]
        save_data()
        
        try:
            await client.send_message(
                chat_id=int(user_id),
                text=f"❌ **Your playlist access has been removed!**\n\nPlease contact support.",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        
        await message.reply_text(f"✅ User `{user_id}` has been removed.", parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")

# ========== CALLBACKS ==========

@app.on_callback_query()
async def callback_handler(client, callback_query: CallbackQuery):
    data = callback_query.data
    
    if data == "generate":
        await callback_query.answer("🔄 Generating...")
        await process_generate(client, callback_query.message)
    
    elif data == "check_verification":
        await check_verification(client, callback_query)
    
    elif data.startswith("extend_"):
        parts = data.split("_")
        if len(parts) >= 3:
            uid = parts[1]
            password = parts[2]
            await handle_extend(client, callback_query, uid, password)
    
    elif data == "status":
        await status_cmd(client, callback_query.message)
        await callback_query.answer()
    
    elif data == "admin_users":
        await users_cmd(client, callback_query.message)
        await callback_query.answer()
    
    elif data == "admin_stats":
        total_users = len(users_data)
        active_users = sum(1 for u in users_data.values() if u.get("expiry", 0) > int(datetime.now().timestamp()))
        
        await callback_query.message.edit_text(
            f"📊 **Statistics**\n\n"
            f"👥 Total Users: {total_users}\n"
            f"✅ Active Users: {active_users}\n"
            f"⏳ Expired Users: {total_users - active_users}",
            parse_mode=ParseMode.MARKDOWN
        )
        await callback_query.answer()
    
    elif data == "close":
        await callback_query.message.delete()
        await callback_query.answer("Closed!")

# ========== VERIFICATION FUNCTIONS ==========

async def process_verification(client, message, short_code):
    """Process verification from start command - FIXED with proper user creation"""
    user_id = str(message.from_user.id)
    
    if short_code not in pending_verifications:
        await message.reply_text("❌ Invalid verification code. Please use /generate.")
        return
    
    data = pending_verifications[short_code]
    uid = data["uid"]
    password = short_code
    
    print(f"📤 Creating user on server: {uid}")
    
    # ✅ Try custom create first
    result = await create_custom_user_on_server(uid, password, 7)
    
    if not result or not result.get("success"):
        # Try regular create as fallback
        result = await create_user_on_server(uid, password, 7)
    
    if not result or not result.get("success"):
        await message.reply_text(
            f"❌ Failed to create playlist!\n\n"
            f"Error: {result.get('error', 'Unknown error') if result else 'Server unreachable'}\n\n"
            f"Please try again or contact support.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    playlist_url = f"{PLAYLIST_URL}/playlist.m3u?uid={uid}&pass={password}"
    
    users_data[user_id] = {
        "uid": uid,
        "password": password,
        "expiry": data["expiry"],
        "created_at": data["created_at"]
    }
    
    del pending_verifications[short_code]
    save_pending()
    save_data()
    
    days_left = get_expiry_days_left(data["expiry"])
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Get Playlist", url=playlist_url)],
        [InlineKeyboardButton("🔄 Extend", callback_data=f"extend_{uid}_{password}")],
        [InlineKeyboardButton("📊 Status", callback_data="status")]
    ])
    
    await message.reply_text(
        f"✅ **Verification Successful!**\n\n"
        f"🎉 Your playlist has been activated for **7 days**!\n\n"
        f"🔗 **Your Playlist URL:**\n`{playlist_url}`\n\n"
        f"🆔 UID: `{uid}`\n"
        f"🔑 Password: `{password}`\n"
        f"📅 **Expires in {days_left} days**\n\n"
        f"🔄 Use /extend to extend your playlist.",
        reply_markup=buttons,
        parse_mode=ParseMode.MARKDOWN
    )

async def check_verification(client, callback_query):
    user_id = str(callback_query.from_user.id)
    
    if user_id in users_data:
        days_left = get_expiry_days_left(users_data[user_id].get("expiry", 0))
        if days_left > 0:
            uid = users_data[user_id].get("uid")
            password = users_data[user_id].get("password")
            playlist_url = f"{PLAYLIST_URL}/playlist.m3u?uid={uid}&pass={password}"
            
            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Get Playlist", url=playlist_url)],
                [InlineKeyboardButton("🔄 Extend", callback_data=f"extend_{uid}_{password}")]
            ])
            
            await callback_query.message.edit_text(
                f"✅ **Already Verified!**\n\n"
                f"📅 **Active for {days_left} days**\n"
                f"🔗 **Your Playlist:**\n`{playlist_url}`",
                reply_markup=buttons,
                parse_mode=ParseMode.MARKDOWN
            )
            await callback_query.answer("✅ Already verified!")
            return
    
    for short_code, data in list(pending_verifications.items()):
        if data["user_id"] == user_id:
            uid = data["uid"]
            password = short_code
            
            result = await create_custom_user_on_server(uid, password, 7)
            
            if not result.get("success"):
                await callback_query.message.edit_text(
                    f"❌ Failed to create playlist!\n\nError: {result.get('error', 'Unknown error')}",
                    parse_mode=ParseMode.MARKDOWN
                )
                await callback_query.answer("❌ Failed!")
                return
            
            playlist_url = f"{PLAYLIST_URL}/playlist.m3u?uid={uid}&pass={password}"
            
            users_data[user_id] = {
                "uid": uid,
                "password": password,
                "expiry": data["expiry"],
                "created_at": data["created_at"]
            }
            
            del pending_verifications[short_code]
            save_pending()
            save_data()
            
            days_left = get_expiry_days_left(data["expiry"])
            
            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Get Playlist", url=playlist_url)],
                [InlineKeyboardButton("🔄 Extend", callback_data=f"extend_{uid}_{password}")]
            ])
            
            await callback_query.message.edit_text(
                f"✅ **Verification Successful!**\n\n"
                f"🎉 Your playlist has been activated for **7 days**!\n\n"
                f"🔗 **Your Playlist URL:**\n`{playlist_url}`\n\n"
                f"🆔 UID: `{uid}`\n"
                f"🔑 Password: `{password}`\n"
                f"📅 **Expires in {days_left} days**",
                reply_markup=buttons,
                parse_mode=ParseMode.MARKDOWN
            )
            await callback_query.answer("✅ Playlist activated!")
            return
    
    await callback_query.answer("❌ Please verify using the link first!", show_alert=True)

async def process_generate(client, message):
    user_id = str(message.from_user.id)
    
    if user_id in users_data:
        data = users_data[user_id]
        days_left = get_expiry_days_left(data.get("expiry", 0))
        if days_left > 0:
            uid = data.get("uid")
            password = data.get("password")
            playlist_url = f"{PLAYLIST_URL}/playlist.m3u?uid={uid}&pass={password}"
            
            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Get Playlist", url=playlist_url)],
                [InlineKeyboardButton("🔄 Extend", callback_data=f"extend_{uid}_{password}")]
            ])
            
            await message.reply_text(
                f"✅ **You already have an active playlist!**\n\n"
                f"📅 **Days remaining:** {days_left}\n"
                f"🔗 **Your Playlist:**\n`{playlist_url}`",
                reply_markup=buttons,
                parse_mode=ParseMode.MARKDOWN
            )
            return
    
    uid = generate_uid()
    short_code = generate_short_code()
    
    bot_username = (await client.get_me()).username
    verification_url = f"https://t.me/{bot_username}?start=verify_{short_code}"
    
    pending_verifications[short_code] = {
        "user_id": user_id,
        "uid": uid,
        "expiry": get_expiry_date(7),
        "created_at": int(datetime.now().timestamp())
    }
    save_pending()
    
    short_link = await create_short_link(verification_url)
    
    if not short_link:
        short_link = verification_url
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Verify Now", url=short_link)],
        [InlineKeyboardButton("🔄 I Have Verified", callback_data="check_verification")],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ])
    
    await message.reply_text(
        f"🔐 **Verification Required!**\n\n"
        f"Your playlist will be activated for **7 days**.\n\n"
        f"👉 **Click the button below to verify:**\n"
        f"`{short_link}`\n\n"
        f"⏳ After verification, click the **'I Have Verified'** button.",
        reply_markup=buttons,
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_extend(client, callback_query, uid, password):
    await callback_query.answer("⏳ Extending...")
    
    user_id = str(callback_query.from_user.id)
    result = await extend_playlist_on_server(uid, password)
    
    if result.get("success"):
        if user_id in users_data:
            new_expiry = result.get("new_expiry")
            if new_expiry:
                try:
                    dt = datetime.strptime(new_expiry, "%Y-%m-%d %H:%M:%S")
                    users_data[user_id]["expiry"] = int(dt.timestamp())
                except:
                    users_data[user_id]["expiry"] = int(new_expiry)
            save_data()
        
        days_left = result.get("days_left", 7)
        playlist_url = f"{PLAYLIST_URL}/playlist.m3u?uid={uid}&pass={password}"
        
        await callback_query.message.edit_text(
            f"✅ **Playlist Extended!**\n\n"
            f"🎉 Extended for **7 more days**!\n\n"
            f"📅 **Days left:** {days_left}\n"
            f"🔗 **Your Playlist:**\n`{playlist_url}`",
            parse_mode=ParseMode.MARKDOWN
        )
        await callback_query.answer("✅ Extended!")
    else:
        await callback_query.message.edit_text(
            f"❌ **Extension Failed!**\n\n"
            f"Error: {result.get('error', 'Unknown error')}",
            parse_mode=ParseMode.MARKDOWN
        )
        await callback_query.answer("❌ Failed!")

# ========== WEB SERVER ==========

def run_web_server():
    try:
        from flask import Flask, jsonify
        web_app = Flask(__name__)
        
        @web_app.route('/')
        @web_app.route('/ping')
        def health_check():
            return jsonify({
                "status": "alive",
                "service": "M3U Playlist Bot",
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "stats": {
                    "total_users": len(users_data),
                    "active_users": sum(1 for u in users_data.values() if u.get("expiry", 0) > int(datetime.now().timestamp()))
                }
            })
        
        port = int(os.environ.get('PORT', 10000))
        web_app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        print(f"Web server error: {e}")

# ========== MAIN ==========

if __name__ == "__main__":
    print("🎶 Starting M3U Playlist Bot...")
    print("✅ Bot is ready!")
    print(f"🔗 Shortner API: {'✅ Configured' if SHORTNER_API else '❌ Not configured'}")
    print(f"🎶 Playlist Server: {PLAYLIST_URL}")
    print("📌 Commands: /start, /generate, /extend, /status, /admin, /users, /approve, /unapprove")
    
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    app.run()
