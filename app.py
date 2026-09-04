from flask import Flask, Response, jsonify, request
import json
import requests
from datetime import datetime, timedelta
import threading
import time
import os
import re
import logging
import secrets
from apscheduler.schedulers.background import BackgroundScheduler
from functools import wraps

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# USER DATABASE
# ============================================================

USERS_FILE = "users.json"
users_db = {}

def load_users():
    global users_db
    try:
        with open(USERS_FILE, "r") as f:
            users_db = json.load(f)
        logger.info(f"✅ Loaded {len(users_db)} users")
    except:
        users_db = {}
        logger.info("📝 Created new users database")

def save_users():
    with open(USERS_FILE, "w") as f:
        json.dump(users_db, f, indent=2)

load_users()

# ============================================================
# AUTHENTICATION DECORATOR
# ============================================================

def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        uid = request.args.get('uid')
        password = request.args.get('pass')
        
        if not uid or not password:
            return jsonify({"error": "Missing uid or pass parameter"}), 401
        
        user = users_db.get(uid)
        if not user or user.get('password') != password:
            return jsonify({"error": "Invalid uid or pass"}), 401
        
        if user.get('expiry', 0) < int(datetime.now().timestamp()):
            return jsonify({"error": "Playlist expired. Please extend."}), 403
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================================
# USER MANAGEMENT FUNCTIONS
# ============================================================

def generate_uid():
    return ''.join(secrets.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(10))

def generate_password():
    return ''.join(secrets.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(8))

def create_user(uid=None, password=None, days=7):
    if not uid:
        uid = generate_uid()
    if not password:
        password = generate_password()
    
    expiry = int((datetime.now() + timedelta(days=days)).timestamp())
    
    users_db[uid] = {
        "uid": uid,
        "password": password,
        "created_at": int(datetime.now().timestamp()),
        "expiry": expiry,
        "extended_count": 0,
        "last_extended": None
    }
    
    save_users()
    logger.info(f"✅ Created user: {uid} (expires in {days} days)")
    return uid, password

def extend_user(uid, days=7):
    if uid not in users_db:
        return None
    
    current_expiry = users_db[uid].get('expiry', 0)
    now = int(datetime.now().timestamp())
    
    if current_expiry < now:
        new_expiry = now + (days * 86400)
    else:
        new_expiry = current_expiry + (days * 86400)
    
    users_db[uid]['expiry'] = new_expiry
    users_db[uid]['extended_count'] = users_db[uid].get('extended_count', 0) + 1
    users_db[uid]['last_extended'] = now
    
    save_users()
    logger.info(f"✅ Extended user: {uid} by {days} days")
    return new_expiry

def get_user_info(uid):
    if uid not in users_db:
        return None
    
    user = users_db[uid].copy()
    user['days_left'] = max(0, (user['expiry'] - int(datetime.now().timestamp())) // 86400)
    return user

# ============================================================
# GLOBAL VARIABLES
# ============================================================

current_playlist = None
last_update = None
update_lock = threading.Lock()
current_events_data = {
    "ivan": [],
    "fancode": [],
    "sonyliv": []
}

# ============================================================
# M3U GENERATOR CLASS
# ============================================================

class M3UGenerator:
    def __init__(self):
        self.playlist_content = None
        self.metadata = {
            "name": "FluX-oW Live event (Auto updated)",
            "author": "iVan_FluX",
            "contact": "https://t.me/iVan_flux",
            "channel": "https://t.me/api_hub_by_ivan"
        }

    def parse_date(self, date_str):
        if not date_str:
            return None
        try:
            cleaned = date_str.replace('/', '-').strip()
            if '+' in cleaned:
                cleaned = cleaned.split('+')[0].strip()
            elif '-' in cleaned and cleaned.count('-') > 2:
                parts = cleaned.split('-')
                if len(parts) > 3:
                    cleaned = '-'.join(parts[:3]) + ' ' + parts[3] if len(parts) > 3 else cleaned
            
            return datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
        except:
            try:
                return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            except:
                try:
                    return datetime.strptime(date_str, "%Y/%m/%d %H:%M:%S")
                except:
                    return None

    def is_match_live(self, start_time, end_time=None):
        try:
            now = datetime.now()
            start = self.parse_date(start_time)
            if not start:
                return False
            if now < start:
                return False
            if end_time:
                end = self.parse_date(end_time)
                if end:
                    return now <= end
            end = start + timedelta(hours=3)
            return now <= end
        except:
            return False

    def get_category_from_title(self, title, cat=None):
        if cat:
            cat_lower = cat.lower()
            if 'cricket' in cat_lower:
                return 'Cricket'
            elif 'football' in cat_lower or 'soccer' in cat_lower:
                return 'Football'
            elif 'boxing' in cat_lower or 'wwe' in cat_lower:
                return 'Boxing/WWE'
            elif 'motorsport' in cat_lower or 'f1' in cat_lower or 'motogp' in cat_lower:
                return 'Motorsport'
            elif 'tennis' in cat_lower:
                return 'Tennis'
            elif 'baseball' in cat_lower:
                return 'Baseball'
            elif 'basketball' in cat_lower:
                return 'Basketball'
        
        if title:
            title_lower = title.lower()
            if 'cricket' in title_lower:
                return 'Cricket'
            elif 'football' in title_lower or 'soccer' in title_lower:
                return 'Football'
            elif 'boxing' in title_lower or 'wwe' in title_lower:
                return 'Boxing/WWE'
            elif 'motorsport' in title_lower or 'f1' in title_lower or 'motogp' in title_lower:
                return 'Motorsport'
            elif 'tennis' in title_lower:
                return 'Tennis'
            elif 'baseball' in title_lower:
                return 'Baseball'
            elif 'basketball' in title_lower:
                return 'Basketball'
        
        return 'Sports'

    def fetch_ivan_events(self):
        try:
            response = requests.get('https://events.ivan-flux.online/api/v1/user?username=valverdea', timeout=15)
            response.raise_for_status()
            data = response.json()
            
            events = data.get('events', [])
            live_events = []
            
            for event in events:
                event_info = event.get('eventInfo', {})
                start_time = event_info.get('startTime', '')
                end_time = event_info.get('endTime', '')
                status = event_info.get('Status', '')
                
                is_live = self.is_match_live(start_time, end_time)
                
                if status == 'Live' or is_live:
                    channels = event.get('channels_data', [])
                    filtered_channels = [
                        ch for ch in channels 
                        if ch.get('title') != 'Ivan-FluX' 
                        and ch.get('link') != 'https://fallback-video.ivan-fluxo.workers.dev/video/index.m3u8'
                        and ch.get('link')
                    ]
                    
                    if filtered_channels:
                        event['channels_data'] = filtered_channels
                        event['eventInfo']['Status'] = 'Live'
                        live_events.append(event)
            
            logger.info(f"✅ Found {len(live_events)} LIVE Ivan-Flux events")
            return live_events
        except Exception as e:
            logger.error(f"❌ Error fetching Ivan-Flux events: {e}")
            return []

    def fetch_fancode_events(self):
        try:
            response = requests.get('https://raw.githubusercontent.com/drmlive/fancode-live-events/refs/heads/main/fancode.json', timeout=15)
            response.raise_for_status()
            data = response.json()
            matches = data.get('matches', [])
            
            live_matches = []
            for match in matches:
                is_live = match.get('status', '').upper() == 'LIVE'
                has_stream = match.get('dai_url') or match.get('adfree_url')
                if is_live and has_stream:
                    live_matches.append(match)
            
            logger.info(f"✅ Found {len(live_matches)} LIVE Fancode events")
            return live_matches
        except Exception as e:
            logger.error(f"❌ Error fetching Fancode events: {e}")
            return []

    def fetch_sonyliv_events(self):
        try:
            sonyliv_url = os.environ.get('SONYLIV_JSON_URL', '')
            if sonyliv_url:
                try:
                    response = requests.get(sonyliv_url, timeout=15)
                    response.raise_for_status()
                    data = response.json()
                    matches = data.get('matches', [])
                    
                    live_matches = []
                    for match in matches:
                        if match.get('isLive', False):
                            has_stream = match.get('dai_url') or match.get('pub_url') or match.get('video_url')
                            if has_stream:
                                live_matches.append(match)
                    
                    logger.info(f"✅ Found {len(live_matches)} LIVE SonyLIV events")
                    return live_matches
                except:
                    pass
            return []
        except Exception as e:
            logger.error(f"❌ Error fetching SonyLIV events: {e}")
            return []

    def clean_link(self, link):
        if not link or link == "ok" or link == "":
            return None
        if link == "https://fallback-video.ivan-fluxo.workers.dev/video/index.m3u8":
            return None
        if '|' in link:
            parts = link.split('|')
            clean_url = parts[0]
            params = '|'.join(parts[1:])
            return f"{clean_url}|{params}"
        return link

    def process_ivan_event(self, event):
        channels = []
        event_info = event.get('eventInfo', {})
        event_name = event.get('title', 'Unknown Event')
        cat = event.get('cat', '')
        
        team_a = event_info.get('teamA', '')
        team_b = event_info.get('teamB', '')
        
        if team_a and team_b:
            title = f"🔴 LIVE {team_a} vs {team_b} - {event_name}"
        else:
            title = f"🔴 LIVE {event_name}"
        
        category = self.get_category_from_title(event_name, cat)
        
        for channel in event.get('channels_data', []):
            channel_title = channel.get('title', 'Stream')
            link = self.clean_link(channel.get('link', ''))
            
            if channel_title == 'Ivan-FluX':
                continue
            
            if link:
                channels.append({
                    'title': f"{title} - {channel_title}",
                    'link': link,
                    'logo': event.get('image', ''),
                    'group': category
                })
        
        return channels

    def process_fancode_event(self, event):
        channels = []
        
        dai_url = event.get('dai_url', '')
        adfree_url = event.get('adfree_url', '')
        
        title = event.get('title', 'Unknown Match')
        event_name = event.get('event_name', '')
        team_1 = event.get('team_1', '')
        team_2 = event.get('team_2', '')
        category = event.get('event_category', 'Sports')
        
        if team_1 and team_2:
            display_title = f"🔴 LIVE {team_1} vs {team_2}"
            if event_name:
                display_title = f"{display_title} ({event_name})"
        else:
            display_title = f"🔴 LIVE {title}"
        
        cat = self.get_category_from_title(category, category)
        
        if dai_url:
            clean_url = self.clean_link(dai_url)
            if clean_url:
                channels.append({
                    'title': f"{display_title} - Fancode Stream",
                    'link': clean_url,
                    'logo': event.get('src', ''),
                    'group': cat
                })
        
        if adfree_url and adfree_url != dai_url:
            clean_url = self.clean_link(adfree_url)
            if clean_url:
                channels.append({
                    'title': f"{display_title} - Adfree Stream",
                    'link': clean_url,
                    'logo': event.get('src', ''),
                    'group': cat
                })
        
        return channels

    def process_sonyliv_event(self, event):
        channels = []
        
        dai_url = event.get('dai_url', '')
        pub_url = event.get('pub_url', '')
        video_url = event.get('video_url', '')
        
        event_name = event.get('event_name', 'Unknown Event')
        match_name = event.get('match_name', '')
        broadcast_channel = event.get('broadcast_channel', '')
        category = event.get('event_category', 'Sports')
        
        if match_name:
            display_title = f"🔴 LIVE {match_name}"
        else:
            display_title = f"🔴 LIVE {event_name}"
        
        if broadcast_channel:
            display_title = f"{display_title} - {broadcast_channel}"
        
        cat = self.get_category_from_title(category, category)
        
        stream_urls = {
            'Main': dai_url,
            'Public': pub_url,
            'Video': video_url
        }
        
        for stream_type, url in stream_urls.items():
            if url:
                clean_url = self.clean_link(url)
                if clean_url:
                    channels.append({
                        'title': f"{display_title} ({stream_type})",
                        'link': clean_url,
                        'logo': event.get('src', ''),
                        'group': cat
                    })
        
        return channels

    def generate_m3u(self):
        global current_events_data
        
        logger.info("🔄 Starting playlist generation - LIVE EVENTS ONLY...")
        
        ivan_events = self.fetch_ivan_events()
        fancode_events = self.fetch_fancode_events()
        sonyliv_events = self.fetch_sonyliv_events()
        
        all_channels = []
        
        current_events_data['ivan'] = ivan_events
        for event in ivan_events:
            channels = self.process_ivan_event(event)
            all_channels.extend(channels)
        
        current_events_data['fancode'] = fancode_events
        for event in fancode_events:
            channels = self.process_fancode_event(event)
            all_channels.extend(channels)
        
        current_events_data['sonyliv'] = sonyliv_events
        for event in sonyliv_events:
            channels = self.process_sonyliv_event(event)
            all_channels.extend(channels)
        
        live_count = len(all_channels)
        logger.info(f"✅ Generated {live_count} LIVE stream channels")
        
        m3u_lines = []
        
        m3u_lines.append('#EXTM3U')
        m3u_lines.append(f'#PLAYLIST:{self.metadata["name"]}')
        m3u_lines.append(f'#AUTHOR:{self.metadata["author"]}')
        m3u_lines.append(f'#CONTACT (OWNER):{self.metadata["contact"]}')
        m3u_lines.append(f'#TELEGRAM CHANNEL:{self.metadata["channel"]}')
        m3u_lines.append(f'#Last update time:{datetime.now().strftime("%I:%M:%S %p %d-%m-%Y")}')
        m3u_lines.append(f'#Live Events:{live_count}')
        m3u_lines.append(f'#Source: Ivan-Flux: {len(ivan_events)} | Fancode: {len(fancode_events)} | SonyLIV: {len(sonyliv_events)}')
        m3u_lines.append('')
        
        for channel in all_channels:
            title = channel['title'].replace(',', ' ').replace('\n', ' ').strip()
            logo = channel.get('logo', '')
            group = channel.get('group', 'Sports')
            
            if logo:
                m3u_lines.append(f'#EXTINF:0 tvg-logo="{logo}" group-title="{group}",{title}')
            else:
                m3u_lines.append(f'#EXTINF:0 group-title="{group}",{title}')
            
            m3u_lines.append(channel['link'])
            m3u_lines.append('')
        
        self.playlist_content = '\n'.join(m3u_lines)
        return self.playlist_content

# Initialize generator
generator = M3UGenerator()

def update_playlist():
    global current_playlist, last_update
    
    with update_lock:
        try:
            logger.info("🔄 Updating playlist...")
            start_time = time.time()
            current_playlist = generator.generate_m3u()
            last_update = datetime.now()
            elapsed = time.time() - start_time
            logger.info(f"✅ Playlist updated successfully in {elapsed:.2f} seconds")
        except Exception as e:
            logger.error(f"❌ Error updating playlist: {e}")

# ============================================================
# AUTHENTICATED PLAYLIST ENDPOINT
# ============================================================

@app.route('/playlist.m3u')
@require_auth
def get_authenticated_playlist():
    global current_playlist
    
    # ✅ Force update if playlist is empty
    if current_playlist is None or current_playlist.count('#EXTINF:0') == 0:
        logger.info("🔄 Playlist is empty, forcing update...")
        update_playlist()
    
    if current_playlist is None or current_playlist.count('#EXTINF:0') == 0:
        # Return a simple placeholder playlist
        placeholder = """#EXTM3U
#PLAYLIST:No Live Events
#No live events available at the moment.

#EXTINF:-1,No Live Events
https://example.com/placeholder.m3u8
"""
        response = Response(placeholder, mimetype='application/vnd.apple.mpegurl')
        response.headers['Content-Disposition'] = 'inline; filename=live_playlist.m3u'
        return response
    
    uid = request.args.get('uid')
    user = get_user_info(uid)
    category_filter = request.args.get('category', '')
    
    content = current_playlist
    
    if category_filter:
        lines = content.split('\n')
        filtered_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith('#EXTINF:0'):
                match = re.search(r'group-title="([^"]+)"', line)
                if match:
                    group = match.group(1)
                    if group.lower() == category_filter.lower():
                        filtered_lines.append(line)
                        if i + 1 < len(lines):
                            filtered_lines.append(lines[i + 1])
                            filtered_lines.append('')
                i += 2
            else:
                if line.startswith('#') and not line.startswith('#EXTINF:0'):
                    if not line.startswith('#Total Streams:'):
                        filtered_lines.append(line)
                i += 1
        
        if filtered_lines:
            content = '\n'.join(filtered_lines)
        else:
            return f"No live events in category: {category_filter}", 404
    
    # Add user info header
    header_lines = content.split('\n')
    user_info = [
        f'#USER: {uid}',
        f'#EXPIRES: {datetime.fromtimestamp(user["expiry"]).strftime("%Y-%m-%d %H:%M:%S")}',
        f'#DAYS_LEFT: {user["days_left"]}',
        f'#EXTEND: {request.url_root}extend?uid={uid}&pass={user["password"]}'
    ]
    
    if header_lines and header_lines[0].startswith('#EXTM3U'):
        header_lines = [header_lines[0]] + user_info + [''] + header_lines[1:]
    else:
        header_lines = ['#EXTM3U'] + user_info + [''] + header_lines
    
    content = '\n'.join(header_lines)
    
    response = Response(content, mimetype='application/vnd.apple.mpegurl')
    response.headers['Content-Disposition'] = 'inline; filename=live_playlist.m3u'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ============================================================
# EXTEND ENDPOINTS
# ============================================================

@app.route('/extend')
def extend_playlist():
    uid = request.args.get('uid')
    password = request.args.get('pass')
    
    if not uid or not password:
        return jsonify({"error": "Missing uid or pass"}), 400
    
    user = users_db.get(uid)
    if not user or user.get('password') != password:
        return jsonify({"error": "Invalid credentials"}), 401
    
    new_expiry = extend_user(uid)
    if not new_expiry:
        return jsonify({"error": "User not found"}), 404
    
    days_left = (new_expiry - int(datetime.now().timestamp())) // 86400
    
    return jsonify({
        "status": "success",
        "message": "Playlist extended for 7 days!",
        "uid": uid,
        "new_expiry": datetime.fromtimestamp(new_expiry).strftime("%Y-%m-%d %H:%M:%S"),
        "days_left": days_left,
        "playlist_url": f"{request.url_root}playlist.m3u?uid={uid}&pass={password}"
    })

# ============================================================
# ADMIN ENDPOINTS
# ============================================================

@app.route('/admin/users')
def admin_users():
    admin_key = request.args.get('key', '')
    if admin_key != os.environ.get('ADMIN_KEY', 'admin123'):
        return jsonify({"error": "Invalid admin key"}), 401
    
    users_list = []
    for uid, user in users_db.items():
        users_list.append({
            "uid": uid,
            "password": user.get('password'),
            "created_at": datetime.fromtimestamp(user.get('created_at', 0)).strftime("%Y-%m-%d %H:%M:%S"),
            "expiry": datetime.fromtimestamp(user.get('expiry', 0)).strftime("%Y-%m-%d %H:%M:%S"),
            "days_left": max(0, (user.get('expiry', 0) - int(datetime.now().timestamp())) // 86400),
            "extended_count": user.get('extended_count', 0)
        })
    
    return jsonify({
        "total_users": len(users_list),
        "users": users_list
    })

@app.route('/admin/create')
def admin_create_user():
    admin_key = request.args.get('key', '')
    if admin_key != os.environ.get('ADMIN_KEY', 'admin123'):
        return jsonify({"error": "Invalid admin key"}), 401
    
    days = int(request.args.get('days', 7))
    uid, password = create_user(days=days)
    
    return jsonify({
        "status": "success",
        "uid": uid,
        "password": password,
        "expires_in": f"{days} days",
        "playlist_url": f"{request.url_root}playlist.m3u?uid={uid}&pass={password}"
    })

@app.route('/admin/create-custom')
def admin_create_custom():
    """Create a user with custom uid and password"""
    admin_key = request.args.get('key', '')
    if admin_key != os.environ.get('ADMIN_KEY', 'admin123'):
        return jsonify({"error": "Invalid admin key"}), 401
    
    uid = request.args.get('uid', '')
    password = request.args.get('pass', '')
    days = int(request.args.get('days', 7))
    
    if not uid or not password:
        return jsonify({"error": "Missing uid or pass"}), 400
    
    if uid in users_db:
        return jsonify({"error": "User already exists"}), 400
    
    expiry = int((datetime.now() + timedelta(days=days)).timestamp())
    
    users_db[uid] = {
        "uid": uid,
        "password": password,
        "created_at": int(datetime.now().timestamp()),
        "expiry": expiry,
        "extended_count": 0,
        "last_extended": None
    }
    
    save_users()
    logger.info(f"✅ Created custom user: {uid}")
    
    return jsonify({
        "status": "success",
        "uid": uid,
        "password": password,
        "expires_in": f"{days} days",
        "playlist_url": f"{request.url_root}playlist.m3u?uid={uid}&pass={password}"
    })

# ============================================================
# ORIGINAL ENDPOINTS
# ============================================================

@app.route('/')
def index():
    base_url = request.url_root.rstrip('/')
    
    total_streams = 0
    categories = {}
    
    if current_playlist:
        total_streams = current_playlist.count('#EXTINF:0')
        
        lines = current_playlist.split('\n')
        for line in lines:
            if line.startswith('#EXTINF:0') and 'group-title="' in line:
                match = re.search(r'group-title="([^"]+)"', line)
                if match:
                    category = match.group(1)
                    categories[category] = categories.get(category, 0) + 1
    
    next_update = (last_update + timedelta(hours=1)).strftime("%I:%M:%S %p") if last_update else "Not set"
    last_update_str = last_update.strftime("%I:%M:%S %p %d-%m-%Y") if last_update else "Never"
    
    category_buttons = ''.join([
        f'<button class="category-btn" data-category="{cat}">{cat} ({count})</button>'
        for cat, count in sorted(categories.items())
    ])
    
    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>🔴 LIVE M3U Playlist</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * {{ box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; background: #1a1a2e; color: #eee; }}
            .container {{ background: #16213e; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }}
            h1 {{ color: #e94560; margin-top: 0; display: flex; align-items: center; gap: 10px; }}
            .live-badge {{ background: #e94560; color: white; padding: 4px 12px; border-radius: 20px; font-size: 14px; animation: pulse 1.5s infinite; }}
            @keyframes pulse {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} 100% {{ opacity: 1; }} }}
            .status {{ padding: 15px; background: #1a1a2e; border-radius: 8px; margin: 20px 0; border: 1px solid #2a2a4e; }}
            .info {{ background: #1a1a2e; padding: 15px; border-radius: 8px; margin: 10px 0; border: 1px solid #2a2a4e; }}
            .button {{ display: inline-block; padding: 12px 24px; background: #e94560; color: white; text-decoration: none; border-radius: 6px; margin: 5px; border: none; cursor: pointer; font-size: 14px; }}
            .button:hover {{ background: #c73652; }}
            .button-green {{ background: #0f3460; }}
            .button-green:hover {{ background: #1a4a7a; }}
            .button-orange {{ background: #e94560; }}
            .button-orange:hover {{ background: #c73652; }}
            .button-purple {{ background: #533483; }}
            .button-purple:hover {{ background: #6a44a0; }}
            .footer {{ margin-top: 30px; color: #888; font-size: 14px; border-top: 1px solid #2a2a4e; padding-top: 20px; }}
            .badge {{ display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 12px; font-weight: bold; }}
            .badge-green {{ background: #0f3460; color: #eee; }}
            .badge-red {{ background: #e94560; color: white; }}
            code {{ background: #0d1b2a; padding: 10px; display: block; border-radius: 6px; word-break: break-all; font-size: 13px; border: 1px solid #1a3a5a; color: #8be9fd; }}
            .url-box {{ background: #0d1b2a; padding: 15px; border-radius: 6px; margin: 10px 0; border: 1px solid #1a3a5a; }}
            .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 15px 0; }}
            .stat-card {{ background: #0d1b2a; padding: 15px; border-radius: 6px; text-align: center; border: 1px solid #1a3a5a; }}
            .stat-number {{ font-size: 28px; font-weight: bold; color: #e94560; }}
            .stat-label {{ font-size: 12px; color: #888; margin-top: 5px; }}
            .category-buttons {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 15px 0; }}
            .category-btn {{ padding: 8px 16px; background: #1a1a2e; border: 1px solid #2a2a4e; border-radius: 20px; cursor: pointer; font-size: 13px; color: #eee; }}
            .category-btn:hover {{ background: #2a2a4e; }}
            .category-btn.active {{ background: #e94560; border-color: #e94560; color: white; }}
            @media (max-width: 600px) {{ .container {{ padding: 15px; }} .button {{ display: block; margin: 10px 0; }} }}
            .live-dot {{ display: inline-block; width: 12px; height: 12px; background: #e94560; border-radius: 50%; animation: pulse 1s infinite; margin-right: 8px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1><span class="live-dot"></span>LIVE M3U Playlist <span class="live-badge">🔴 LIVE</span></h1>
            
            <div class="status">
                <strong>Status:</strong> <span class="badge badge-red">● Live</span>
                <br><br>
                <strong>Last Update:</strong> {last_update_str}
                <br>
                <strong>Next Update:</strong> {next_update}
                <br>
                <strong>Live Streams:</strong> <span style="color: #e94560; font-weight: bold;">{total_streams}</span>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-number">{total_streams}</div>
                    <div class="stat-label">🔴 Live Streams</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number" style="color: #8be9fd;">{len(categories)}</div>
                    <div class="stat-label">📂 Categories</div>
                </div>
            </div>
            
            <div class="category-buttons">
                <button class="category-btn active" data-category="all">All ({total_streams})</button>
                {category_buttons}
            </div>
            
            <div style="margin: 20px 0;">
                <a href="/playlist.m3u" class="button">📥 Get LIVE Playlist</a>
                <a href="/update" class="button button-orange">🔄 Refresh</a>
                <a href="/stats" class="button button-purple">📊 Stats</a>
            </div>
            
            <div class="info">
                <h3>📋 Playlist URL</h3>
                <div class="url-box">
                    <code>{base_url}/playlist.m3u</code>
                </div>
                <button onclick="copyUrl()" class="button" style="padding: 8px 16px; font-size: 12px; background: #0f3460;">📋 Copy URL</button>
            </div>
            
            <div style="margin-top: 20px;">
                <h3>📱 How to Use</h3>
                <ol>
                    <li>Copy the URL above</li>
                    <li>Open your IPTV player (VLC, TiviMate, IPTV Extreme, etc.)</li>
                    <li>Add a new playlist and paste the URL</li>
                    <li>The playlist updates <strong>every hour</strong> with only LIVE events</li>
                </ol>
            </div>
            
            <div class="footer">
                <p>🤖 Powered by Ivan-Flux, Fancode &amp; SonyLIV | Updates every hour</p>
            </div>
        </div>
        
        <script>
        function copyUrl() {{
            const url = '{base_url}/playlist.m3u';
            navigator.clipboard.writeText(url).then(() => {{ alert('✅ URL copied!'); }}).catch(() => {{
                const input = document.createElement('input');
                input.value = url;
                document.body.appendChild(input);
                input.select();
                document.execCommand('copy');
                document.body.removeChild(input);
                alert('✅ URL copied!');
            }});
        }}
        
        document.querySelectorAll('.category-btn').forEach(btn => {{
            btn.addEventListener('click', function() {{
                document.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                const category = this.dataset.category;
                if (category === 'all') {{
                    window.location.href = '/playlist.m3u';
                }} else {{
                    window.location.href = '/playlist.m3u?category=' + encodeURIComponent(category);
                }}
            }});
        }});
        </script>
    </body>
    </html>
    '''
    
    return html

@app.route('/update')
def force_update():
    update_playlist()
    return jsonify({
        "status": "success",
        "message": "Playlist updated",
        "last_update": last_update.strftime("%I:%M:%S %p %d-%m-%Y") if last_update else "Never",
        "total_streams": current_playlist.count('#EXTINF:0') if current_playlist else 0
    })

@app.route('/stats')
def get_stats():
    stats = {
        "status": "ready" if current_playlist else "not_generated",
        "last_update": last_update.strftime("%I:%M:%S %p %d-%m-%Y") if last_update else "Never",
        "total_streams": 0,
        "categories": {},
        "sources": {
            "ivan_flux": len(current_events_data.get('ivan', [])),
            "fancode": len(current_events_data.get('fancode', [])),
            "sonyliv": len(current_events_data.get('sonyliv', []))
        }
    }
    
    if current_playlist:
        stats["total_streams"] = current_playlist.count('#EXTINF:0')
        
        lines = current_playlist.split('\n')
        for line in lines:
            if line.startswith('#EXTINF:0') and 'group-title="' in line:
                match = re.search(r'group-title="([^"]+)"', line)
                if match:
                    category = match.group(1)
                    stats["categories"][category] = stats["categories"].get(category, 0) + 1
    
    return jsonify(stats)

@app.route('/raw')
def get_raw_data():
    return jsonify({
        "live_events": {
            "ivan_flux": current_events_data.get('ivan', []),
            "fancode": current_events_data.get('fancode', []),
            "sonyliv": current_events_data.get('sonyliv', [])
        }
    })

# ============================================================
# TEST ENDPOINT
# ============================================================

@app.route('/test')
def test():
    """Test endpoint to check if server is running"""
    return jsonify({
        "status": "ok",
        "message": "Server is running",
        "timestamp": datetime.now().isoformat(),
        "users": len(users_db)
    })

# ============================================================
# MAIN
# ============================================================

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(update_playlist, 'interval', hours=1, id='playlist_update')
scheduler.start()

# Initial update
update_playlist()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
