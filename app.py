# ============================================================
# SOCIAL FEED DASHBOARD - COMPLETE WITH SOURCE MANAGER & MOBILE VIEW
# ============================================================

from flask import Flask, jsonify, request, render_template_string, send_file
from flask_cors import CORS
from fetcher import fetch_facebook_posts
from datetime import datetime, timedelta
import json
import os
import logging
import requests
from io import BytesIO
import pytz
from zernio import Zernio
import hashlib
import io
import textwrap
from PIL import Image, ImageDraw, ImageFont

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ============================================================
# IMPORT CONFIG
# ============================================================

from config import ZERNIO_API_KEY, FACEBOOK_PROFILE_ID

# ============================================================
# IMPORT SOURCE MANAGER
# ============================================================

try:
    from source_manager import SourceManager, get_configured_sources, get_source_count, get_sources_summary
    SOURCE_MANAGER_AVAILABLE = True
except ImportError:
    SOURCE_MANAGER_AVAILABLE = False
    logger.warning("⚠️ Source Manager not available")

# ============================================================
# CONSTANTS
# ============================================================

TIMEZONE = "Africa/Nairobi"  # GMT+3
MIN_SCHEDULE_MINUTES = 5     # Minimum minutes ahead for scheduling

# ============================================================
# UPSTASH REDIS REST API
# ============================================================

class UpstashRedis:
    def __init__(self, url, token):
        self.url = url.rstrip('/')
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def _request(self, command, *args):
        try:
            url = f"{self.url}/{command}"
            for arg in args:
                import urllib.parse
                url += f"/{urllib.parse.quote(str(arg), safe='')}"
            
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('result')
            else:
                logger.error(f"Redis error: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Redis request error: {e}")
            return None
    
    def set(self, key, value, ex=None):
        try:
            if ex:
                return self._request('SET', key, value, 'EX', ex)
            return self._request('SET', key, value)
        except Exception as e:
            logger.error(f"Redis SET error: {e}")
            return None
    
    def get(self, key):
        try:
            return self._request('GET', key)
        except Exception as e:
            logger.error(f"Redis GET error: {e}")
            return None
    
    def delete(self, key):
        try:
            return self._request('DEL', key)
        except Exception as e:
            logger.error(f"Redis DEL error: {e}")
            return None
    
    def exists(self, key):
        try:
            return self._request('EXISTS', key)
        except Exception as e:
            logger.error(f"Redis EXISTS error: {e}")
            return None
    
    def ping(self):
        try:
            result = self._request('PING')
            return result == 'PONG'
        except Exception as e:
            logger.error(f"Redis PING error: {e}")
            return False

# Initialize Redis client
redis = None
REDIS_AVAILABLE = False

try:
    from config import UPSTASH_REDIS_URL, UPSTASH_REDIS_TOKEN
    
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        redis = UpstashRedis(UPSTASH_REDIS_URL, UPSTASH_REDIS_TOKEN)
        if redis.ping():
            REDIS_AVAILABLE = True
            logger.info("✅ Upstash Redis connected successfully!")
        else:
            logger.error("❌ Failed to ping Redis")
    else:
        logger.warning("⚠️ Upstash Redis credentials not configured")
        
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("⚠️ Redis not available")
except Exception as e:
    logger.error(f"❌ Redis initialization error: {e}")
    redis = None
    REDIS_AVAILABLE = False

# Redis keys
REDIS_KEY_POSTS = "social_feed:posts"
REDIS_KEY_HISTORY = "social_feed:history"
REDIS_KEY_SCHEDULED = "social_feed:scheduled"
REDIS_KEY_PROCESSED = "social_feed:processed"
REDIS_KEY_REMOVED = "social_feed:removed"  # For manually removed posts

# ============================================================
# POST TRACKING SYSTEM
# ============================================================

def get_processed_posts():
    """Get list of processed post IDs"""
    try:
        if REDIS_AVAILABLE and redis:
            data = redis.get(REDIS_KEY_PROCESSED)
            if data:
                return set(json.loads(data))
        return set()
    except Exception as e:
        logger.error(f"Error getting processed posts: {e}")
        return set()

def mark_post_as_processed(post_id):
    """Mark a post as processed (posted or scheduled)"""
    try:
        if REDIS_AVAILABLE and redis:
            processed = get_processed_posts()
            processed.add(str(post_id))
            redis.set(REDIS_KEY_PROCESSED, json.dumps(list(processed)))
            logger.info(f"✅ Marked post {post_id} as processed")
            return True
    except Exception as e:
        logger.error(f"Error marking post as processed: {e}")
    return False

def clear_processed_posts():
    """Clear processed posts tracking"""
    try:
        if REDIS_AVAILABLE and redis:
            redis.delete(REDIS_KEY_PROCESSED)
            return True
    except Exception as e:
        logger.error(f"Error clearing processed posts: {e}")
    return False

# ============================================================
# REMOVED POSTS TRACKING (for manual removal)
# ============================================================

def get_removed_posts():
    """Get list of manually removed post IDs"""
    try:
        if REDIS_AVAILABLE and redis:
            data = redis.get(REDIS_KEY_REMOVED)
            if data:
                return set(json.loads(data))
        return set()
    except Exception as e:
        logger.error(f"Error getting removed posts: {e}")
        return set()

def mark_post_as_removed(post_id):
    """Mark a post as manually removed"""
    try:
        if REDIS_AVAILABLE and redis:
            removed = get_removed_posts()
            removed.add(str(post_id))
            redis.set(REDIS_KEY_REMOVED, json.dumps(list(removed)))
            logger.info(f"🗑️ Marked post {post_id} as removed")
            return True
    except Exception as e:
        logger.error(f"Error marking post as removed: {e}")
    return False

def clear_removed_posts():
    """Clear removed posts tracking"""
    try:
        if REDIS_AVAILABLE and redis:
            redis.delete(REDIS_KEY_REMOVED)
            return True
    except Exception as e:
        logger.error(f"Error clearing removed posts: {e}")
    return False

# ============================================================
# DOWNLOAD POST AS JPG
# ============================================================

def create_post_image(post_text, source_name=None):
    """Create a JPG image from post text"""
    try:
        # Create image
        img = Image.new('RGB', (800, 600), color='white')
        draw = ImageDraw.Draw(img)
        
        # Try to load a font, fallback to default
        try:
            font = ImageFont.truetype("arial.ttf", 18)
            title_font = ImageFont.truetype("arial.ttf", 24)
        except:
            font = ImageFont.load_default()
            title_font = ImageFont.load_default()
        
        # Draw header
        draw.rectangle([0, 0, 800, 60], fill='#667eea')
        draw.text((20, 15), "📱 Social Feed Post", fill='white', font=title_font)
        
        # Draw source if available
        if source_name:
            draw.text((20, 70), f"Source: {source_name}", fill='#666', font=font)
        
        # Draw content with word wrap
        y_position = 110
        wrapped_text = textwrap.wrap(post_text, width=50)
        for line in wrapped_text[:20]:  # Max 20 lines
            draw.text((20, y_position), line, fill='#333', font=font)
            y_position += 30
        
        # Draw footer
        draw.rectangle([0, 570, 800, 600], fill='#f0f0f0')
        draw.text((20, 575), f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", fill='#999', font=font)
        
        # Save to bytes
        img_bytes = BytesIO()
        img.save(img_bytes, format='JPEG', quality=90)
        img_bytes.seek(0)
        
        return img_bytes
    except Exception as e:
        logger.error(f"Error creating post image: {e}")
        return None

# ============================================================
# PERSISTENT STORAGE
# ============================================================

def get_data_dir():
    if os.path.exists('/tmp'):
        return '/tmp'
    return os.path.dirname(os.path.abspath(__file__))

DATA_DIR = get_data_dir()
POSTS_FILE_FALLBACK = os.path.join(DATA_DIR, 'posts_cache.json')
HISTORY_FILE_FALLBACK = os.path.join(DATA_DIR, 'post_history.json')

def save_posts(posts):
    try:
        if REDIS_AVAILABLE and redis:
            data = {
                'posts': posts,
                'last_updated': datetime.now().isoformat(),
                'count': len(posts)
            }
            redis.set(REDIS_KEY_POSTS, json.dumps(data), ex=86400)
            logger.info(f"💾 Saved {len(posts)} posts to Redis")
            return True
        else:
            return save_posts_fallback(posts)
    except Exception as e:
        logger.error(f"Error saving posts: {e}")
        return save_posts_fallback(posts)

def load_posts():
    try:
        if REDIS_AVAILABLE and redis:
            data = redis.get(REDIS_KEY_POSTS)
            if data:
                parsed = json.loads(data)
                return parsed.get('posts', [])
        return load_posts_fallback()
    except Exception as e:
        logger.error(f"Error loading posts: {e}")
        return load_posts_fallback()

def save_history(history):
    try:
        if REDIS_AVAILABLE and redis:
            redis.set(REDIS_KEY_HISTORY, json.dumps(history), ex=2592000)
            return True
        else:
            return save_history_fallback(history)
    except Exception as e:
        logger.error(f"Error saving history: {e}")
        return save_history_fallback(history)

def load_history():
    try:
        if REDIS_AVAILABLE and redis:
            data = redis.get(REDIS_KEY_HISTORY)
            if data:
                return json.loads(data)
        return load_history_fallback()
    except Exception as e:
        logger.error(f"Error loading history: {e}")
        return load_history_fallback()

def save_posts_fallback(posts):
    try:
        with open(POSTS_FILE_FALLBACK, 'w', encoding='utf-8') as f:
            json.dump({
                'posts': posts,
                'last_updated': datetime.now().isoformat(),
                'count': len(posts)
            }, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving posts to file: {e}")
        return False

def load_posts_fallback():
    try:
        if os.path.exists(POSTS_FILE_FALLBACK):
            with open(POSTS_FILE_FALLBACK, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('posts', [])
    except Exception as e:
        logger.error(f"Error loading posts from file: {e}")
    return []

def save_history_fallback(history):
    try:
        with open(HISTORY_FILE_FALLBACK, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving history to file: {e}")
        return False

def load_history_fallback():
    try:
        if os.path.exists(HISTORY_FILE_FALLBACK):
            with open(HISTORY_FILE_FALLBACK, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading history from file: {e}")
    return []

# ============================================================
# FACEBOOK POSTER CLASS
# ============================================================

os.environ['PYTHONHTTPSVERIFY'] = '0'

class FacebookPoster:
    def __init__(self):
        self.api_key = ZERNIO_API_KEY
        self.base_url = "https://zernio.com/api/v1"
        self.page_id = FACEBOOK_PROFILE_ID
        self.timezone = TIMEZONE
        self.min_schedule_minutes = MIN_SCHEDULE_MINUTES
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.client = Zernio(api_key=self.api_key)
        logger.info(f"📘 Facebook Poster initialized with Profile ID: {self.page_id}")
    
    def _extract_post_data(self, post_response):
        try:
            post_id = None
            post_url = None
            
            if hasattr(post_response, 'post'):
                post_obj = post_response.post
                if hasattr(post_obj, 'field_id'):
                    post_id = post_obj.field_id
                elif hasattr(post_obj, 'id'):
                    post_id = post_obj.id
                
                if hasattr(post_obj, 'platforms') and len(post_obj.platforms) > 0:
                    platform = post_obj.platforms[0]
                    if hasattr(platform, 'platformPostUrl'):
                        post_url = str(platform.platformPostUrl)
            
            elif isinstance(post_response, dict):
                if 'data' in post_response and 'post' in post_response['data']:
                    post_data = post_response['data']['post']
                    post_id = post_data.get('_id') or post_data.get('id')
                else:
                    post_id = post_response.get('id') or post_response.get('post_id')
                    post_url = post_response.get('url') or post_response.get('post_url')

            if not post_url and post_id:
                post_url = f"https://www.facebook.com/{self.page_id}/posts/{post_id}"

            return post_id or "success", post_url
        except Exception as e:
            logger.error(f"Error extracting post data: {e}")
            return "success", None
    
    def _clean_status(self, status):
        if not status:
            return "unknown"
        status_str = str(status)
        if 'Status11.' in status_str:
            status_str = status_str.replace('Status11.', '')
        return status_str.lower()
    
    def post_text(self, content):
        try:
            response = self.client.posts.create(
                content=content,
                platforms=[{"platform": "facebook", "accountId": self.page_id}],
                publish_now=True
            )
            post_id, post_url = self._extract_post_data(response)
            return {"success": True, "post_id": post_id, "url": post_url}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def post_with_image(self, content, image_url):
        try:
            response = self.client.posts.create(
                content=content,
                media_items=[{"url": image_url, "type": "image"}],
                platforms=[{"platform": "facebook", "accountId": self.page_id}],
                publish_now=True
            )
            post_id, post_url = self._extract_post_data(response)
            return {"success": True, "post_id": post_id, "url": post_url}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def post_with_images(self, content, image_urls):
        try:
            media_items = [{"url": url, "type": "image"} for url in image_urls[:5]]
            response = self.client.posts.create(
                content=content,
                media_items=media_items,
                platforms=[{"platform": "facebook", "accountId": self.page_id}],
                publish_now=True
            )
            post_id, post_url = self._extract_post_data(response)
            return {"success": True, "post_id": post_id, "url": post_url}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def schedule_post(self, content, scheduled_time_iso, image_urls=None):
        try:
            local_tz = pytz.timezone(self.timezone)
            try:
                scheduled_dt = datetime.fromisoformat(scheduled_time_iso)
                scheduled_dt = local_tz.localize(scheduled_dt)
                now_dt = datetime.now(local_tz)
                time_diff = (scheduled_dt - now_dt).total_seconds()
                
                if time_diff < self.min_schedule_minutes * 60:
                    return {"success": False, "error": f"Scheduled time must be at least {self.min_schedule_minutes} minutes in the future"}
            except Exception as e:
                return {"success": False, "error": f"Invalid time format: {scheduled_time_iso}"}
            
            media_items = None
            if image_urls:
                media_items = [{"url": url, "type": "image"} for url in image_urls[:5]]
            
            post_data = {
                "content": content,
                "platforms": [{"platform": "facebook", "accountId": self.page_id}],
                "scheduled_for": scheduled_time_iso,
                "timezone": self.timezone
            }
            if media_items:
                post_data["media_items"] = media_items
            
            response = self.client.posts.create(**post_data)
            post_id, _ = self._extract_post_data(response)
            return {"success": True, "post_id": post_id, "scheduled_for": scheduled_time_iso}
        except Exception as e:
            error_msg = str(e)
            if '409' in error_msg or 'already scheduled' in error_msg:
                error_msg = "This content was already scheduled recently. Please use different content."
            return {"success": False, "error": error_msg}

facebook_poster = FacebookPoster()

# ============================================================
# HTML DASHBOARD - COMPLETE WITH SOURCE MANAGER & MOBILE VIEW
# ============================================================

DASHBOARD_HTML = r'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
    <title>Social Feed Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Inter', sans-serif; background: #f0f2f5; color: #1a1a2e; min-height: 100vh; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #c1c7cd; border-radius: 10px; }
        
        .header { background: #ffffff; border-bottom: 1px solid #e9ecef; padding: 16px 32px; position: sticky; top: 0; z-index: 100; }
        .header-content { max-width: 1400px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; }
        .header-left { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
        .logo { display: flex; align-items: center; gap: 10px; }
        .logo-icon { width: 38px; height: 38px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 20px; color: white; }
        .logo h1 { font-size: 22px; font-weight: 800; color: #1a1a2e; }
        .logo h1 span { color: #667eea; }
        .badge { background: #e9ecef; color: #495057; padding: 2px 12px; border-radius: 20px; font-size: 11px; font-weight: 600; }
        .badge.live { background: #28a745; color: white; animation: pulse 2s infinite; }
        .badge.sources { background: #667eea; color: white; cursor: pointer; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }
        
        .header-right { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
        .header-stats { display: flex; gap: 24px; }
        .stat-mini { text-align: center; }
        .stat-mini .number { font-size: 18px; font-weight: 700; color: #1a1a2e; }
        .stat-mini .label { font-size: 10px; color: #868e96; text-transform: uppercase; font-weight: 600; }
        
        .btn-group { display: flex; gap: 8px; flex-wrap: wrap; }
        .btn { padding: 9px 20px; border: none; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; transition: all 0.25s ease; display: flex; align-items: center; gap: 8px; font-family: 'Inter', sans-serif; }
        .btn-primary { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
        .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(102,126,234,0.4); }
        .btn-facebook { background: #1877f2; color: white; }
        .btn-facebook:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(24,119,242,0.3); }
        .btn-warning { background: #ffc107; color: #1a1a2e; }
        .btn-warning:hover { transform: translateY(-2px); }
        .btn-secondary { background: #e9ecef; color: #495057; }
        .btn-secondary:hover { background: #dee2e6; }
        .btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none !important; }
        
        .spinner { display: none; animation: spin 0.8s linear infinite; }
        .btn.loading .spinner { display: inline-block; }
        .btn.loading .btn-text { display: none; }
        @keyframes spin { to { transform: rotate(360deg); } }
        
        .toast-container { position: fixed; top: 80px; right: 24px; z-index: 999; display: flex; flex-direction: column; gap: 10px; }
        .toast { background: #1a1a2e; color: white; padding: 14px 24px; border-radius: 12px; font-size: 14px; font-weight: 500; box-shadow: 0 10px 40px rgba(0,0,0,0.2); animation: slideIn 0.4s ease; min-width: 280px; display: flex; align-items: center; gap: 12px; }
        .toast.success { border-left: 4px solid #28a745; }
        .toast.error { border-left: 4px solid #dc3545; }
        .toast.warning { border-left: 4px solid #ffc107; }
        .toast.info { border-left: 4px solid #667eea; }
        @keyframes slideIn { from { opacity: 0; transform: translateX(100px); } to { opacity: 1; transform: translateX(0); } }
        .toast .icon { font-size: 20px; }
        .toast .msg { flex: 1; }
        .toast .close { cursor: pointer; opacity: 0.5; transition: opacity 0.2s; font-size: 18px; }
        .toast .close:hover { opacity: 1; }
        
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; padding: 24px 32px 0; max-width: 1400px; margin: 0 auto; }
        .stat-card { background: #ffffff; border-radius: 12px; padding: 18px 22px; border: 1px solid #e9ecef; transition: all 0.2s ease; }
        .stat-card:hover { border-color: #667eea; box-shadow: 0 4px 20px rgba(102,126,234,0.08); }
        .stat-card .value { font-size: 26px; font-weight: 800; color: #1a1a2e; }
        .stat-card .label { color: #868e96; font-size: 13px; font-weight: 500; margin-top: 2px; }
        .stat-card .icon { font-size: 22px; margin-bottom: 4px; }
        
        .tabs { display: flex; gap: 4px; background: #ffffff; padding: 4px; border-radius: 12px; border: 1px solid #e9ecef; margin: 16px 32px 0; max-width: 1400px; overflow-x: auto; }
        .tab-btn { padding: 10px 24px; border: none; border-radius: 8px; background: transparent; color: #868e96; font-weight: 600; font-size: 14px; cursor: pointer; transition: all 0.2s ease; font-family: 'Inter', sans-serif; flex: 1; white-space: nowrap; }
        .tab-btn:hover { background: #f1f3f5; color: #1a1a2e; }
        .tab-btn.active { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; box-shadow: 0 4px 15px rgba(102,126,234,0.3); }
        .tab-content { display: none; padding: 20px 32px; max-width: 1400px; margin: 0 auto; }
        .tab-content.active { display: block; }
        
        .filters { display: flex; gap: 8px; flex-wrap: wrap; background: #ffffff; padding: 8px; border-radius: 12px; border: 1px solid #e9ecef; margin-bottom: 20px; overflow-x: auto; }
        .filter-btn { padding: 8px 18px; border: none; border-radius: 8px; background: transparent; color: #868e96; font-weight: 600; font-size: 13px; cursor: pointer; transition: all 0.2s ease; font-family: 'Inter', sans-serif; white-space: nowrap; }
        .filter-btn:hover { background: #f1f3f5; color: #1a1a2e; }
        .filter-btn.active { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; box-shadow: 0 4px 15px rgba(102,126,234,0.3); }
        .filter-btn .count { background: rgba(255,255,255,0.2); padding: 1px 8px; border-radius: 10px; font-size: 11px; margin-left: 4px; }
        .filter-btn.active .count { background: rgba(255,255,255,0.2); }
        
        .posts-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 24px; }
        .post-card { background: #ffffff; border-radius: 16px; overflow: hidden; border: 1px solid #e9ecef; transition: all 0.3s cubic-bezier(0.25,0.46,0.45,0.94); animation: fadeInUp 0.5s ease forwards; opacity: 0; cursor: pointer; }
        .post-card:hover { transform: translateY(-4px); box-shadow: 0 12px 40px rgba(0,0,0,0.08); border-color: #667eea; }
        .post-card:active { transform: scale(0.98); }
        @keyframes fadeInUp { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
        .post-card:nth-child(1) { animation-delay: 0.03s; }
        .post-card:nth-child(2) { animation-delay: 0.06s; }
        .post-card:nth-child(3) { animation-delay: 0.09s; }
        .post-card:nth-child(4) { animation-delay: 0.12s; }
        .post-card:nth-child(5) { animation-delay: 0.15s; }
        .post-card:nth-child(6) { animation-delay: 0.18s; }
        .post-card:nth-child(7) { animation-delay: 0.21s; }
        .post-card:nth-child(8) { animation-delay: 0.24s; }
        .post-card:nth-child(9) { animation-delay: 0.27s; }
        
        .post-image-wrap { position: relative; width: 100%; padding-top: 56.25%; background: #f8f9fa; overflow: hidden; }
        .post-image-wrap img { position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; transition: transform 0.5s ease; }
        .post-card:hover .post-image-wrap img { transform: scale(1.02); }
        .post-image-wrap .no-image { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 40px; opacity: 0.2; }
        .post-source-tag { position: absolute; top: 12px; left: 12px; background: rgba(0,0,0,0.75); backdrop-filter: blur(10px); padding: 4px 14px; border-radius: 20px; font-size: 11px; font-weight: 600; color: #667eea; border: 1px solid rgba(102,126,234,0.2); }
        .post-status-badge { position: absolute; top: 12px; right: 50px; padding: 4px 12px; border-radius: 20px; font-size: 10px; font-weight: 600; background: #28a745; color: white; }
        
        .btn-remove {
            position: absolute;
            top: 12px;
            right: 12px;
            background: rgba(220, 53, 69, 0.9);
            color: white;
            border: none;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.25s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            line-height: 1;
            z-index: 10;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.2);
        }
        .btn-remove:hover { background: #dc3545; transform: scale(1.1); box-shadow: 0 4px 15px rgba(220, 53, 69, 0.4); }
        .btn-remove:active { transform: scale(0.9); }
        
        .post-content { padding: 18px 20px 16px; }
        .post-text { font-size: 14px; line-height: 1.7; color: #2d3436; margin-bottom: 14px; display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden; }
        .post-text.quoted { border-left: 3px solid #667eea; padding-left: 14px; font-style: italic; color: #636e72; }
        .post-text .hashtag { color: #667eea; font-weight: 500; }
        .post-meta { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; padding-top: 14px; border-top: 1px solid #f1f3f5; }
        .post-time { font-size: 12px; color: #adb5bd; }
        
        .btn-download { background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; border: none; padding: 6px 16px; border-radius: 8px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.25s ease; display: flex; align-items: center; gap: 6px; font-family: 'Inter', sans-serif; }
        .btn-download:hover { transform: translateY(-2px); box-shadow: 0 4px 15px rgba(40,167,69,0.3); }
        
        .btn-action { background: #667eea; color: white; border: none; padding: 6px 16px; border-radius: 8px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.25s ease; font-family: 'Inter', sans-serif; }
        .btn-action:hover { transform: translateY(-2px); box-shadow: 0 4px 15px rgba(102,126,234,0.3); }
        .btn-action.post-now { background: #1877f2; }
        .btn-action.post-now:hover { box-shadow: 0 4px 15px rgba(24,119,242,0.3); }
        .btn-action.schedule { background: #ffc107; color: #1a1a2e; }
        .btn-action.schedule:hover { box-shadow: 0 4px 15px rgba(255,193,7,0.3); }
        
        /* ============================================================
           FULL POST VIEW MODAL
           ============================================================ */
        .modal-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.7);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            padding: 20px;
            backdrop-filter: blur(5px);
        }
        .modal-overlay.active {
            display: flex;
        }
        .modal {
            background: #ffffff;
            border-radius: 16px;
            max-width: 700px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            padding: 0;
            animation: modalIn 0.3s ease;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        @keyframes modalIn {
            from { opacity: 0; transform: scale(0.95) translateY(20px); }
            to { opacity: 1; transform: scale(1) translateY(0); }
        }
        .modal-header {
            padding: 16px 20px;
            border-bottom: 1px solid #e9ecef;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            background: #ffffff;
            z-index: 10;
            border-radius: 16px 16px 0 0;
        }
        .modal-header h2 {
            font-size: 18px;
            font-weight: 700;
            color: #1a1a2e;
        }
        .modal-close {
            background: none;
            border: none;
            font-size: 28px;
            cursor: pointer;
            color: #868e96;
            transition: color 0.2s;
            padding: 0 8px;
        }
        .modal-close:hover { color: #1a1a2e; }
        .modal-body {
            padding: 20px;
            max-height: calc(90vh - 70px);
            overflow-y: auto;
        }
        .modal-body .post-image-full {
            width: 100%;
            max-height: 400px;
            object-fit: contain;
            border-radius: 8px;
            margin-bottom: 16px;
            background: #f8f9fa;
        }
        .modal-body .post-text-full {
            font-size: 16px;
            line-height: 1.8;
            color: #2d3436;
            margin-bottom: 16px;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .modal-body .post-text-full .hashtag { color: #667eea; font-weight: 500; }
        .modal-body .post-meta-full {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
            padding-top: 16px;
            border-top: 1px solid #e9ecef;
            font-size: 13px;
            color: #868e96;
        }
        .modal-body .post-actions-full {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid #e9ecef;
        }
        .modal-body .post-actions-full .btn { flex: 1; justify-content: center; min-width: 100px; }
        
        .loading-state { grid-column: 1/-1; text-align: center; padding: 60px 20px; }
        .loading-state .loader { width: 40px; height: 40px; border: 3px solid #f1f3f5; border-top-color: #667eea; border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 16px; }
        
        .empty-state { grid-column: 1/-1; text-align: center; padding: 80px 20px; }
        .empty-state .icon { font-size: 72px; margin-bottom: 16px; opacity: 0.3; }
        .empty-state h3 { color: #868e96; font-weight: 500; font-size: 22px; margin-bottom: 8px; }
        .empty-state p { color: #adb5bd; font-size: 15px; }
        
        .schedule-form { background: #ffffff; border-radius: 16px; padding: 24px; border: 1px solid #e9ecef; margin-bottom: 24px; }
        .schedule-form h2 { margin-bottom: 20px; font-size: 24px; }
        .schedule-form .subtitle { color: #868e96; font-size: 14px; margin-bottom: 20px; }
        .form-group { margin-bottom: 16px; }
        .form-group label { display: block; font-weight: 600; margin-bottom: 6px; font-size: 14px; color: #495057; }
        .form-group input, .form-group textarea, .form-group select { width: 100%; padding: 10px 12px; border: 1px solid #e9ecef; border-radius: 8px; font-family: 'Inter', sans-serif; font-size: 14px; transition: border-color 0.2s; }
        .form-group input:focus, .form-group textarea:focus, .form-group select:focus { outline: none; border-color: #667eea; box-shadow: 0 0 0 3px rgba(102,126,234,0.1); }
        .form-group textarea { resize: vertical; min-height: 100px; }
        .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        .form-actions { display: flex; gap: 12px; margin-top: 20px; }
        .form-actions .btn { flex: 1; justify-content: center; }
        
        .info-box { background: #f0f7ff; border: 1px solid #1877f2; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .info-box .label { font-size: 13px; color: #495057; }
        .info-box .value { font-weight: 600; color: #1877f2; }
        
        .queue-item { background: #ffffff; padding: 16px 20px; border-radius: 12px; border: 1px solid #e9ecef; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
        .queue-item:hover { border-color: #667eea; }
        .queue-item .info { flex: 1; min-width: 200px; }
        .queue-item .info .title { font-weight: 600; }
        .queue-item .info .details { font-size: 13px; color: #868e96; margin-top: 4px; }
        .queue-item .badge-facebook { background: #1877f2; color: white; padding: 2px 10px; border-radius: 12px; font-size: 11px; }
        .queue-item .badge-scheduled { background: #ffc107; color: #1a1a2e; padding: 2px 10px; border-radius: 12px; font-size: 11px; }
        .queue-item .actions { display: flex; gap: 8px; flex-wrap: wrap; }
        
        .footer { text-align: center; padding: 20px 32px; color: #adb5bd; font-size: 13px; border-top: 1px solid #e9ecef; background: #ffffff; }
        .footer span { color: #667eea; }
        
        /* Sources Dropdown */
        .sources-dropdown { position: relative; display: inline-block; }
        .sources-dropdown-content {
            display: none;
            position: absolute;
            top: 100%;
            right: 0;
            background: #ffffff;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 12px;
            min-width: 280px;
            max-height: 350px;
            overflow-y: auto;
            z-index: 100;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }
        .sources-dropdown-content.active { display: block; }
        .sources-dropdown-content .source-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 6px 0;
            border-bottom: 1px solid #f1f3f5;
            font-size: 13px;
        }
        .sources-dropdown-content .source-item:last-child { border-bottom: none; }
        .sources-dropdown-content .source-item .cat {
            background: #f0f2f5;
            padding: 1px 8px;
            border-radius: 10px;
            font-size: 10px;
        }
        .sources-dropdown-content .source-item .prio {
            background: #667eea;
            color: white;
            padding: 1px 8px;
            border-radius: 10px;
            font-size: 10px;
        }
        
        @media (max-width: 768px) {
            .header { padding: 12px 16px; }
            .header-content { flex-direction: column; align-items: stretch; gap: 10px; }
            .header-left { justify-content: space-between; }
            .logo h1 { font-size: 18px; }
            .header-right { flex-direction: column; align-items: stretch; gap: 10px; }
            .header-stats { justify-content: space-around; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); padding: 12px 16px 0; gap: 10px; }
            .stat-card { padding: 14px 16px; }
            .stat-card .value { font-size: 20px; }
            .tabs { flex-direction: row; margin: 12px 16px; overflow-x: auto; padding: 4px; gap: 4px; }
            .tab-btn { padding: 8px 16px; font-size: 13px; flex: none; }
            .tab-content { padding: 12px 16px; }
            .posts-grid { grid-template-columns: 1fr; gap: 16px; }
            .form-row { grid-template-columns: 1fr; }
            .queue-item { flex-direction: column; align-items: stretch; }
            .queue-item .actions { justify-content: stretch; }
            .queue-item .actions .btn { flex: 1; justify-content: center; }
            .toast-container { top: 70px; right: 12px; left: 12px; }
            .toast { min-width: auto; font-size: 13px; padding: 12px 16px; }
            .info-box { flex-direction: column; text-align: center; }
            .btn-remove { width: 24px; height: 24px; font-size: 14px; top: 8px; right: 8px; }
            .modal { max-width: 100%; margin: 10px; max-height: 95vh; }
            .modal-body { padding: 16px; }
            .modal-body .post-text-full { font-size: 15px; }
            .sources-dropdown-content { position: fixed; top: auto; bottom: 0; left: 0; right: 0; max-height: 60vh; border-radius: 16px 16px 0 0; }
        }
        @media (max-width: 480px) {
            .stat-card .value { font-size: 17px; }
            .stat-card .icon { font-size: 18px; }
            .post-text { font-size: 13px; -webkit-line-clamp: 4; }
            .btn { font-size: 12px; padding: 8px 14px; }
            .modal-body .post-text-full { font-size: 14px; }
        }
    </style>
</head>
<body>
    <div class="toast-container" id="toastContainer"></div>
    
    <!-- FULL POST VIEW MODAL -->
    <div class="modal-overlay" id="postModal">
        <div class="modal">
            <div class="modal-header">
                <h2 id="modalTitle">📄 Post Details</h2>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body" id="modalBody">
                <div id="modalContent">Loading...</div>
            </div>
        </div>
    </div>
    
    <header class="header">
        <div class="header-content">
            <div class="header-left">
                <div class="logo">
                    <div class="logo-icon">📊</div>
                    <h1>Social<span>Feed</span></h1>
                </div>
                <span class="badge live">● LIVE</span>
                <span class="badge" id="cacheBadge">Loading...</span>
                <span class="badge sources" id="sourcesBadge" onclick="toggleSourcesDropdown()">📡 Loading...</span>
            </div>
            <div class="header-right">
                <div class="header-stats">
                    <div class="stat-mini">
                        <div class="number" id="postCount">0</div>
                        <div class="label">Posts</div>
                    </div>
                    <div class="stat-mini">
                        <div class="number" id="sourceCount">0</div>
                        <div class="label">Sources</div>
                    </div>
                    <div class="stat-mini">
                        <div class="number" id="lastUpdate">-</div>
                        <div class="label">Updated</div>
                    </div>
                </div>
                <div class="btn-group">
                    <div class="sources-dropdown">
                        <button class="btn btn-secondary" onclick="toggleSourcesDropdown()" style="font-size:12px;padding:6px 12px;">
                            📋 Sources ▼
                        </button>
                        <div class="sources-dropdown-content" id="sourcesDropdown">
                            <div id="sourcesList">Loading...</div>
                        </div>
                    </div>
                    <button class="btn btn-secondary" onclick="clearCache()">🗑️ Clear</button>
                    <button class="btn btn-primary" id="refreshBtn" onclick="fetchPosts()">
                        <span class="spinner">⟳</span>
                        <span class="btn-text">🔄 Fetch Posts</span>
                    </button>
                </div>
            </div>
        </div>
    </header>
    
    <div class="stats-grid" id="statsGrid">
        <div class="stat-card">
            <div class="icon">📝</div>
            <div class="value" id="totalPosts">0</div>
            <div class="label">Total Posts</div>
        </div>
        <div class="stat-card">
            <div class="icon">📸</div>
            <div class="value" id="totalImages">0</div>
            <div class="label">With Images</div>
        </div>
        <div class="stat-card">
            <div class="icon">💬</div>
            <div class="value" id="totalQuotes">0</div>
            <div class="label">Quotes</div>
        </div>
        <div class="stat-card">
            <div class="icon">📋</div>
            <div class="value" id="totalSources">0</div>
            <div class="label">Sources</div>
        </div>
    </div>
    
    <div class="tabs">
        <button class="tab-btn active" data-tab="feed">📱 Feed</button>
        <button class="tab-btn" data-tab="post">📤 Post Now</button>
        <button class="tab-btn" data-tab="schedule">📅 Schedule</button>
        <button class="tab-btn" data-tab="history">✅ History</button>
    </div>
    
    <!-- FEED TAB -->
    <div class="tab-content active" id="tab-feed">
        <div class="filters" id="filters">
            <button class="filter-btn active" data-filter="all">📋 All <span class="count" id="countAll">0</span></button>
            <button class="filter-btn" data-filter="images">🖼️ Images <span class="count" id="countImages">0</span></button>
            <button class="filter-btn" data-filter="quotes">💬 Quotes <span class="count" id="countQuotes">0</span></button>
        </div>
        <div class="posts-grid" id="postsGrid">
            <div class="empty-state">
                <div class="icon">📭</div>
                <h3>No Posts Loaded</h3>
                <p>Click the "Fetch Posts" button above to load content</p>
                <button class="btn btn-primary" onclick="fetchPosts()" style="margin-top:20px;padding:12px 32px;font-size:16px;">🚀 Fetch Posts Now</button>
            </div>
        </div>
    </div>
    
    <!-- POST NOW TAB -->
    <div class="tab-content" id="tab-post">
        <div class="schedule-form">
            <h2>📤 Post to Facebook Now</h2>
            <p class="subtitle">Post immediately to your Facebook page</p>
            <div class="info-box">
                <span class="label">📘 Posting to: <strong style="color:#1877f2;">Facebook Page</strong></span>
                <span class="label">🆔 Profile ID: <strong style="color:#1877f2;" id="profileDisplay">Loading...</strong></span>
            </div>
            <form id="postForm" onsubmit="submitPostNow(event)">
                <div class="form-group">
                    <label>Post Content</label>
                    <textarea id="postContent" placeholder="Write your Facebook post here..." required></textarea>
                </div>
                <div class="form-group">
                    <label>Image URL (Optional)</label>
                    <input type="text" id="postMedia" placeholder="https://example.com/image.jpg">
                    <small style="color:#868e96;">Add one image URL or leave blank for text-only post</small>
                </div>
                <div class="form-actions">
                    <button type="submit" class="btn btn-facebook">🚀 Post Now</button>
                    <button type="reset" class="btn btn-secondary">Clear</button>
                </div>
            </form>
        </div>
        <div id="postResult"></div>
    </div>
    
    <!-- SCHEDULE TAB -->
    <div class="tab-content" id="tab-schedule">
        <div class="schedule-form">
            <h2>📅 Schedule Post to Facebook</h2>
            <p class="subtitle">Schedule a post for a specific time</p>
            <div class="info-box">
                <span class="label">📘 Posting to: <strong style="color:#1877f2;">Facebook Page</strong></span>
                <span class="label">🆔 Profile ID: <strong style="color:#1877f2;" id="scheduleProfileDisplay">Loading...</strong></span>
            </div>
            <form id="scheduleForm" onsubmit="submitSchedule(event)">
                <div class="form-group">
                    <label>Post Content</label>
                    <textarea id="scheduleContent" placeholder="Write your Facebook post here..." required></textarea>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Scheduled Date & Time</label>
                        <input type="datetime-local" id="scheduleTime" required>
                        <small style="color:#868e96;" id="timeHint">⏰ Must be at least 5 minutes from now</small>
                    </div>
                    <div class="form-group">
                        <label>Image URL (Optional)</label>
                        <input type="text" id="scheduleMedia" placeholder="https://example.com/image.jpg">
                    </div>
                </div>
                <div class="form-actions">
                    <button type="submit" class="btn btn-warning">📅 Schedule Post</button>
                    <button type="reset" class="btn btn-secondary">Clear</button>
                </div>
            </form>
        </div>
        <div id="scheduleResult"></div>
    </div>
    
    <!-- HISTORY TAB -->
    <div class="tab-content" id="tab-history">
        <h2 style="margin-bottom:16px;">✅ Posted History</h2>
        <div id="historyList"><p style="color:#868e96;">Loading history...</p></div>
    </div>
    
    <div class="footer">
        Built with <span>❤️</span> • <span id="postCountFooter">0</span> posts loaded • Facebook via Zernio
    </div>
    
    <script>
        let allPosts = [];
        let currentFilter = 'all';
        let isLoading = false;
        let profileId = '';
        
        // ============================================================
        // TOAST NOTIFICATIONS
        // ============================================================
        function showToast(message, type, duration) {
            type = type || 'info';
            duration = duration || 4000;
            const container = document.getElementById('toastContainer');
            const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
            const toast = document.createElement('div');
            toast.className = 'toast ' + type;
            toast.innerHTML = '<span class="icon">' + (icons[type] || 'ℹ️') + '</span>' +
                '<span class="msg">' + message + '</span>' +
                '<span class="close" onclick="this.parentElement.remove()">✕</span>';
            container.appendChild(toast);
            setTimeout(function() {
                if (toast.parentElement) {
                    toast.style.opacity = '0';
                    toast.style.transform = 'translateX(100px)';
                    setTimeout(function() { toast.remove(); }, 300);
                }
            }, duration);
        }
        
        // ============================================================
        // FULL POST VIEW MODAL
        // ============================================================
        function openModal(postId) {
            const post = allPosts.find(function(p) { return p.id === postId; });
            if (!post) { showToast('❌ Post not found', 'error'); return; }
            
            const modal = document.getElementById('postModal');
            const content = document.getElementById('modalContent');
            
            let html = '';
            if (post.images && post.images.length > 0) {
                html += '<img src="' + post.images[0] + '" alt="Post image" class="post-image-full" loading="lazy" onerror="this.style.display=\'none\'">';
            }
            let displayText = post.text || '(No text content)';
            displayText = displayText.replace(/#([a-zA-Z0-9_]+)/g, '<span class="hashtag">#$1</span>');
            html += '<div class="post-text-full">' + displayText + '</div>';
            html += '<div class="post-meta-full">';
            html += '<span>📌 ' + (post.source_name || 'Unknown') + '</span>';
            html += '<span>🕐 ' + (post.time || 'N/A') + '</span>';
            html += '</div>';
            html += '<div class="post-actions-full">';
            html += '<button class="btn btn-download" onclick="downloadPostAsJpg(\'' + post.id + '\'); closeModal();">🖼️ Download JPG</button>';
            html += '<button class="btn btn-action post-now" onclick="loadPostForPostNow(\'' + post.id + '\'); closeModal();">📤 Post Now</button>';
            html += '<button class="btn btn-action schedule" onclick="loadPostForSchedule(\'' + post.id + '\'); closeModal();">📅 Schedule</button>';
            html += '<button class="btn btn-secondary" style="background:#dc3545;color:white;" onclick="removePostFromFeed(\'' + post.id + '\'); closeModal();">🗑️ Remove</button>';
            html += '</div>';
            
            content.innerHTML = html;
            document.getElementById('modalTitle').textContent = '📄 Post from ' + (post.source_name || 'Unknown');
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';
        }
        
        function closeModal() {
            document.getElementById('postModal').classList.remove('active');
            document.body.style.overflow = '';
        }
        // Close modal on overlay click
        document.getElementById('postModal').addEventListener('click', function(e) {
            if (e.target === this) closeModal();
        });
        // Close modal on Escape key
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') closeModal();
        });
        
        // ============================================================
        // REMOVE POST FROM FEED (PERSISTENT - SAVES TO REDIS)
        // ============================================================
        async function removePostFromFeed(postId) {
            if (!confirm('Remove this post from the feed permanently?')) return;
            try {
                const response = await fetch('/api/post/remove', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ post_id: postId })
                });
                const data = await response.json();
                if (data.success) {
                    allPosts = allPosts.filter(function(p) { return p.id !== postId; });
                    renderPosts(allPosts);
                    updateStats(allPosts);
                    updateFilters(allPosts);
                    showToast('🗑️ Post removed from feed permanently', 'success');
                } else {
                    throw new Error(data.error || 'Failed to remove');
                }
            } catch (error) {
                showToast('❌ Error: ' + error.message, 'error');
            }
        }
        
        // ============================================================
        // TIME VALIDATION
        // ============================================================
        function validateScheduleTime(scheduledTime) {
            const selectedDate = new Date(scheduledTime);
            const now = new Date();
            const minTime = new Date(now.getTime() + 5 * 60000);
            if (selectedDate < minTime) {
                const minTimeStr = minTime.toLocaleTimeString();
                return { valid: false, message: '⏰ Scheduled time must be at least 5 minutes from now.\nMinimum time: ' + minTimeStr };
            }
            return { valid: true };
        }
        
        function setDefaultScheduleTime() {
            const now = new Date();
            const defaultTime = new Date(now.getTime() + 2 * 60 * 60 * 1000);
            defaultTime.setMinutes(Math.ceil(defaultTime.getMinutes() / 15) * 15);
            defaultTime.setSeconds(0);
            defaultTime.setMilliseconds(0);
            const year = defaultTime.getFullYear();
            const month = String(defaultTime.getMonth() + 1).padStart(2, '0');
            const day = String(defaultTime.getDate()).padStart(2, '0');
            const hours = String(defaultTime.getHours()).padStart(2, '0');
            const minutes = String(defaultTime.getMinutes()).padStart(2, '0');
            document.getElementById('scheduleTime').value = year + '-' + month + '-' + day + 'T' + hours + ':' + minutes;
        }
        
        function updateTimeHint() {
            const now = new Date();
            const minTime = new Date(now.getTime() + 5 * 60000);
            let hours = minTime.getHours();
            const ampm = hours >= 12 ? 'PM' : 'AM';
            hours = hours % 12;
            hours = hours ? hours : 12;
            const minutes = String(minTime.getMinutes()).padStart(2, '0');
            const hint = document.getElementById('timeHint');
            if (hint) {
                hint.textContent = '⏰ Must be at least 5 minutes from now (minimum: ' + hours + ':' + minutes + ' ' + ampm + ')';
                hint.style.color = '#6c757d';
            }
        }
        
        // ============================================================
        // SOURCES DROPDOWN
        // ============================================================
        async function loadSourcesInfo() {
            try {
                const response = await fetch('/api/sources');
                const data = await response.json();
                if (data.success) {
                    document.getElementById('sourcesBadge').textContent = '📡 ' + data.count + ' sources';
                    document.getElementById('sourceCount').textContent = data.count;
                    window.sourcesData = data;
                }
            } catch (e) {
                document.getElementById('sourcesBadge').textContent = '📡 Error';
            }
        }
        
        async function toggleSourcesDropdown() {
            const dropdown = document.getElementById('sourcesDropdown');
            if (dropdown.classList.contains('active')) {
                dropdown.classList.remove('active');
                return;
            }
            try {
                let data = window.sourcesData;
                if (!data) {
                    const response = await fetch('/api/sources');
                    data = await response.json();
                }
                if (data.success) {
                    let html = '<div style="font-weight:600;margin-bottom:8px;color:#1a1a2e;">📡 Configured Sources</div>';
                    html += '<div style="font-size:11px;color:#868e96;margin-bottom:8px;">Priority order (lower = higher)</div>';
                    const sorted = [...data.sources].sort((a, b) => (a.priority || 999) - (b.priority || 999));
                    sorted.forEach(function(s) {
                        html += '<div class="source-item">';
                        html += '<span>' + (s.name || s.id) + '</span>';
                        html += '<span><span class="cat">' + (s.category || 'General') + '</span> <span class="prio">#' + (s.priority || 'N/A') + '</span></span>';
                        html += '</div>';
                    });
                    const summary = data.summary || {};
                    const categories = summary.categories || {};
                    if (Object.keys(categories).length > 0) {
                        html += '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e9ecef;font-size:11px;color:#868e96;">';
                        html += '📂 Categories: ' + Object.entries(categories).map(function(kv) { return kv[0] + ' (' + kv[1] + ')'; }).join(', ');
                        html += '</div>';
                    }
                    html += '<div style="margin-top:4px;font-size:11px;color:#868e96;">📊 Total: ' + data.count + ' sources</div>';
                    document.getElementById('sourcesList').innerHTML = html;
                    dropdown.classList.add('active');
                }
            } catch (e) {
                document.getElementById('sourcesList').innerHTML = '❌ Error loading sources';
                dropdown.classList.add('active');
            }
        }
        // Close dropdown when clicking outside
        document.addEventListener('click', function(e) {
            const dropdown = document.getElementById('sourcesDropdown');
            const btn = e.target.closest('.sources-dropdown') || e.target.closest('#sourcesBadge');
            if (!btn && dropdown) {
                dropdown.classList.remove('active');
            }
        });
        
        // ============================================================
        // TAB SWITCHING
        // ============================================================
        document.querySelectorAll('.tab-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
                this.classList.add('active');
                const tabName = this.dataset.tab;
                document.querySelectorAll('.tab-content').forEach(function(tc) { tc.classList.remove('active'); });
                document.getElementById('tab-' + tabName).classList.add('active');
                if (tabName === 'post' || tabName === 'schedule') {
                    loadProfileId();
                    if (tabName === 'schedule') updateTimeHint();
                }
                if (tabName === 'history') loadHistory();
            });
        });
        
        // ============================================================
        // DOWNLOAD POST AS JPG
        // ============================================================
        async function downloadPostAsJpg(postId) {
            const post = allPosts.find(function(p) { return p.id === postId; });
            if (!post) { showToast('❌ Post not found', 'error'); return; }
            
            if (post.images && post.images.length > 0) {
                try {
                    showToast('🖼️ Downloading image...', 'info');
                    const response = await fetch('/api/download/single-image', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ image_url: post.images[0], filename: 'post_' + postId + '_' + new Date().toISOString().slice(0,10) })
                    });
                    if (response.ok) {
                        const blob = await response.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        let filename = 'post_' + postId + '_' + new Date().toISOString().slice(0,10) + '.jpg';
                        const cd = response.headers.get('content-disposition');
                        if (cd) { const m = cd.match(/filename="?([^"]+)"?/); if (m) filename = m[1]; }
                        a.download = filename;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                        showToast('✅ Image downloaded!', 'success');
                    } else {
                        throw new Error('Failed to download image');
                    }
                } catch (error) {
                    showToast('❌ Error: ' + error.message, 'error');
                    downloadPostAsJpgFallback(postId);
                }
            } else {
                downloadPostAsJpgFallback(postId);
            }
        }
        
        async function downloadPostAsJpgFallback(postId) {
            const post = allPosts.find(function(p) { return p.id === postId; });
            if (!post) { showToast('❌ Post not found', 'error'); return; }
            try {
                showToast('🖼️ Generating image...', 'info');
                const response = await fetch('/api/download/jpg', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: post.text || 'No text content', source: post.source_name || 'Unknown' })
                });
                if (response.ok) {
                    const blob = await response.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'post_' + postId + '_' + new Date().toISOString().slice(0,10) + '.jpg';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                    showToast('✅ Downloaded as JPG!', 'success');
                } else {
                    throw new Error('Failed to generate image');
                }
            } catch (error) {
                showToast('❌ Error: ' + error.message, 'error');
                downloadPostAsText(postId);
            }
        }
        
        function downloadPostAsText(postId) {
            const post = allPosts.find(function(p) { return p.id === postId; });
            if (!post) { showToast('❌ Post not found', 'error'); return; }
            let content = '';
            content += '='.repeat(60) + '\n📱 SOCIAL POST DOWNLOAD\n' + '='.repeat(60) + '\n\n';
            content += '📌 SOURCE: ' + (post.source_name || 'Unknown') + '\n';
            content += '🕐 TIME: ' + (post.time || 'N/A') + '\n';
            content += '🔗 LINK: ' + (post.post_link || 'N/A') + '\n\n';
            content += '-'.repeat(60) + '\n\n📝 CONTENT:\n';
            content += post.text || '(No text content)';
            content += '\n\n';
            if (post.images && post.images.length > 0) {
                content += '-'.repeat(60) + '\n🖼️ IMAGES:\n';
                post.images.forEach(function(img, i) { content += '  ' + (i+1) + '. ' + img + '\n'; });
            }
            content += '\n' + '='.repeat(60) + '\n📅 Downloaded: ' + new Date().toLocaleString() + '\n' + '='.repeat(60);
            const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'post_' + postId + '_' + new Date().toISOString().slice(0,10) + '.txt';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showToast('✅ Downloaded as text (fallback)', 'info');
        }
        
        // ============================================================
        // FETCH POSTS - ONLY ON BUTTON CLICK
        // ============================================================
        async function fetchPosts() {
            if (isLoading) return;
            isLoading = true;
            const btn = document.getElementById('refreshBtn');
            btn.classList.add('loading');
            btn.disabled = true;
            const grid = document.getElementById('postsGrid');
            grid.innerHTML = '<div class="loading-state"><div class="loader"></div><p>📡 Fetching latest posts...</p></div>';
            try {
                showToast('🔄 Fetching fresh posts...', 'info');
                const response = await fetch('/api/posts?limit=9');
                const data = await response.json();
                if (data.success) {
                    allPosts = data.posts || [];
                    renderPosts(allPosts);
                    updateStats(allPosts);
                    updateFilters(allPosts);
                    document.getElementById('cacheBadge').textContent = 'Fresh';
                    document.getElementById('cacheBadge').style.background = '#667eea';
                    document.getElementById('cacheBadge').style.color = 'white';
                    showToast('✅ Loaded ' + allPosts.length + ' posts!', 'success');
                } else {
                    throw new Error(data.error || 'Failed to fetch');
                }
            } catch (error) {
                console.error('Error:', error);
                showToast('❌ Error: ' + error.message, 'error');
                try {
                    const cacheResponse = await fetch('/api/cache');
                    const cacheData = await cacheResponse.json();
                    if (cacheData.success && cacheData.posts.length > 0) {
                        allPosts = cacheData.posts;
                        renderPosts(allPosts);
                        updateStats(allPosts);
                        updateFilters(allPosts);
                        document.getElementById('cacheBadge').textContent = 'Cached';
                        document.getElementById('cacheBadge').style.background = '#28a745';
                        document.getElementById('cacheBadge').style.color = 'white';
                        showToast('📂 Loaded ' + allPosts.length + ' posts from cache', 'info');
                    } else {
                        grid.innerHTML = '<div class="empty-state"><div class="icon">⚠️</div><h3>Failed to Load</h3><p>' + error.message + '</p></div>';
                    }
                } catch (e) {
                    grid.innerHTML = '<div class="empty-state"><div class="icon">⚠️</div><h3>Failed to Load</h3><p>' + error.message + '</p></div>';
                }
            }
            btn.classList.remove('loading');
            btn.disabled = false;
            isLoading = false;
        }
        
        // ============================================================
        // LOAD FROM CACHE ON START - NO AUTO-FETCH
        // ============================================================
        async function loadFromCacheOnStart() {
            try {
                const response = await fetch('/api/cache');
                const data = await response.json();
                if (data.success && data.posts.length > 0) {
                    allPosts = data.posts;
                    renderPosts(allPosts);
                    updateStats(allPosts);
                    updateFilters(allPosts);
                    document.getElementById('cacheBadge').textContent = 'Cached';
                    document.getElementById('cacheBadge').style.background = '#28a745';
                    document.getElementById('cacheBadge').style.color = 'white';
                    showToast('📂 Loaded ' + allPosts.length + ' posts from cache', 'info');
                } else {
                    document.getElementById('cacheBadge').textContent = 'Ready';
                    document.getElementById('cacheBadge').style.background = '#e9ecef';
                    document.getElementById('cacheBadge').style.color = '#495057';
                    const grid = document.getElementById('postsGrid');
                    grid.innerHTML = '<div class="empty-state"><div class="icon">📭</div><h3>No Posts Loaded</h3><p>Click the "Fetch Posts" button above to load content</p><button class="btn btn-primary" onclick="fetchPosts()" style="margin-top:20px;padding:12px 32px;font-size:16px;">🚀 Fetch Posts Now</button></div>';
                }
            } catch (e) { console.error('Error loading cache:', e); }
        }
        
        // ============================================================
        // CLEAR CACHE
        // ============================================================
        async function clearCache() {
            if (!confirm('Clear cached posts?')) return;
            try {
                const response = await fetch('/api/cache/clear', { method: 'DELETE' });
                const data = await response.json();
                if (data.success) {
                    allPosts = [];
                    renderPosts(allPosts);
                    updateStats(allPosts);
                    updateFilters(allPosts);
                    showToast('🗑️ Cache cleared', 'success');
                    document.getElementById('cacheBadge').textContent = 'Cleared';
                    document.getElementById('cacheBadge').style.background = '#dc3545';
                    document.getElementById('cacheBadge').style.color = 'white';
                }
            } catch (error) {
                showToast('❌ Error: ' + error.message, 'error');
            }
        }
        
        // ============================================================
        // RENDER POSTS - WITH REMOVE BUTTON & CLICK TO VIEW
        // ============================================================
        function renderPosts(posts) {
            const grid = document.getElementById('postsGrid');
            let filtered = posts;
            if (currentFilter === 'images') {
                filtered = posts.filter(function(p) { return p.images && p.images.length > 0; });
            } else if (currentFilter === 'quotes') {
                filtered = posts.filter(function(p) { return p.text && p.text.length < 200 && p.text.length > 10; });
            }
            
            if (!filtered || filtered.length === 0) {
                grid.innerHTML = '<div class="empty-state"><div class="icon">📭</div><h3>No posts available</h3><p>All posts have been processed or no posts match the filter</p></div>';
                return;
            }
            
            var html = '';
            filtered.forEach(function(post, index) {
                const hasImage = post.images && post.images.length > 0;
                const imageCount = hasImage ? post.images.length : 0;
                const isQuote = post.text && post.text.length < 200 && post.text.length > 10;
                const sourceName = post.source_name || 'Unknown';
                const sourceInitial = sourceName.charAt(0).toUpperCase();
                let displayText = post.text || '';
                if (displayText.length > 300) displayText = displayText.substring(0, 300) + '...';
                displayText = displayText.replace(/#([a-zA-Z0-9_]+)/g, '<span class="hashtag">#$1</span>');
                
                html += '<div class="post-card" onclick="openModal(\'' + post.id + '\')" style="animation-delay: ' + ((index % 9) * 0.03) + 's">';
                html += '<div class="post-image-wrap">';
                if (hasImage) {
                    html += '<img src="' + post.images[0] + '" alt="Post image" loading="lazy" onerror="this.parentElement.innerHTML=\'<div class=\\\'no-image\\\'>📄</div>\'">';
                    if (imageCount > 1) {
                        html += '<span style="position:absolute;bottom:12px;right:12px;background:rgba(0,0,0,0.75);backdrop-filter:blur(10px);padding:2px 10px;border-radius:12px;font-size:11px;color:white;">+' + (imageCount - 1) + ' more</span>';
                    }
                } else {
                    html += '<div class="no-image">📄</div>';
                }
                html += '<span class="post-source-tag">' + sourceInitial + ' ' + sourceName + '</span>';
                html += '<span class="post-status-badge">Available</span>';
                html += '<button class="btn-remove" onclick="event.stopPropagation(); removePostFromFeed(\'' + post.id + '\')" title="Remove from feed">✕</button>';
                html += '</div>';
                html += '<div class="post-content">';
                if (displayText) {
                    html += '<div class="post-text ' + (isQuote ? 'quoted' : '') + '">' + displayText + '</div>';
                }
                html += '<div class="post-meta">';
                html += '<span class="post-time">' + (post.time || 'N/A') + '</span>';
                html += '<div style="display:flex;gap:6px;flex-wrap:wrap;">';
                html += '<button class="btn-download" onclick="event.stopPropagation(); downloadPostAsJpg(\'' + post.id + '\')">🖼️ Download JPG</button>';
                html += '<button class="btn-action post-now" onclick="event.stopPropagation(); loadPostForPostNow(\'' + post.id + '\')">📤 Post Now</button>';
                html += '<button class="btn-action schedule" onclick="event.stopPropagation(); loadPostForSchedule(\'' + post.id + '\')">📅 Schedule</button>';
                html += '</div>';
                html += '</div></div></div>';
            });
            
            grid.innerHTML = html;
            document.getElementById('postCountFooter').textContent = filtered.length;
        }
        
        // ============================================================
        // UPDATE STATS
        // ============================================================
        function updateStats(posts) {
            if (!posts || posts.length === 0) {
                ['totalPosts','totalImages','totalQuotes','totalSources'].forEach(function(id) {
                    document.getElementById(id).textContent = '0';
                });
                document.getElementById('postCount').textContent = '0';
                document.getElementById('sourceCount').textContent = '0';
                document.getElementById('lastUpdate').textContent = '-';
                return;
            }
            const total = posts.length;
            const withImages = posts.filter(function(p) { return p.images && p.images.length > 0; }).length;
            const quotes = posts.filter(function(p) { return p.text && p.text.length < 200 && p.text.length > 10; }).length;
            const sources = new Set(posts.map(function(p) { return p.source_name; }));
            document.getElementById('totalPosts').textContent = total;
            document.getElementById('totalImages').textContent = withImages;
            document.getElementById('totalQuotes').textContent = quotes;
            document.getElementById('totalSources').textContent = sources.size;
            document.getElementById('postCount').textContent = total;
            document.getElementById('sourceCount').textContent = sources.size;
            document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
        }
        
        // ============================================================
        // UPDATE FILTERS
        // ============================================================
        function updateFilters(posts) {
            if (!posts) posts = allPosts;
            const images = posts.filter(function(p) { return p.images && p.images.length > 0; });
            const quotes = posts.filter(function(p) { return p.text && p.text.length < 200 && p.text.length > 10; });
            document.getElementById('countAll').textContent = posts.length;
            document.getElementById('countImages').textContent = images.length;
            document.getElementById('countQuotes').textContent = quotes.length;
        }
        
        // ============================================================
        // LOAD PROFILE ID
        // ============================================================
        async function loadProfileId() {
            try {
                const response = await fetch('/api/config/facebook-profile-id');
                const data = await response.json();
                if (data.success && data.profile_id) {
                    profileId = data.profile_id;
                    document.getElementById('profileDisplay').textContent = profileId;
                    document.getElementById('scheduleProfileDisplay').textContent = profileId;
                }
            } catch (e) { console.error('Error loading profile:', e); }
        }
        
        // ============================================================
        // LOAD POST FOR POST NOW
        // ============================================================
        function loadPostForPostNow(postId) {
            const post = allPosts.find(function(p) { return p.id === postId; });
            if (!post) { showToast('❌ Post not found', 'error'); return; }
            document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
            document.querySelector('[data-tab="post"]').classList.add('active');
            document.querySelectorAll('.tab-content').forEach(function(tc) { tc.classList.remove('active'); });
            document.getElementById('tab-post').classList.add('active');
            document.getElementById('postContent').value = post.text || '';
            document.getElementById('postForm').dataset.postId = postId;
            if (post.images && post.images.length > 0) {
                document.getElementById('postMedia').value = post.images[0];
                showToast('📝 Loaded with ' + post.images.length + ' image(s)', 'info');
            } else {
                document.getElementById('postMedia').value = '';
                showToast('📝 Loaded (no images)', 'info');
            }
            loadProfileId();
        }
        
        // ============================================================
        // LOAD POST FOR SCHEDULE
        // ============================================================
        function loadPostForSchedule(postId) {
            const post = allPosts.find(function(p) { return p.id === postId; });
            if (!post) { showToast('❌ Post not found', 'error'); return; }
            document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
            document.querySelector('[data-tab="schedule"]').classList.add('active');
            document.querySelectorAll('.tab-content').forEach(function(tc) { tc.classList.remove('active'); });
            document.getElementById('tab-schedule').classList.add('active');
            document.getElementById('scheduleContent').value = post.text || '';
            document.getElementById('scheduleForm').dataset.postId = postId;
            if (post.images && post.images.length > 0) {
                document.getElementById('scheduleMedia').value = post.images[0];
                showToast('📝 Loaded with ' + post.images.length + ' image(s)', 'info');
            } else {
                document.getElementById('scheduleMedia').value = '';
                showToast('📝 Loaded (no images)', 'info');
            }
            setDefaultScheduleTime();
            updateTimeHint();
            loadProfileId();
        }
        
        // ============================================================
        // SUBMIT POST NOW - WITH REMOVE FROM FEED
        // ============================================================
        async function submitPostNow(e) {
            e.preventDefault();
            const content = document.getElementById('postContent').value;
            const mediaUrl = document.getElementById('postMedia').value;
            const postId = document.getElementById('postForm').dataset.postId || null;
            if (!content) { showToast('❌ Please enter post content', 'error'); return; }
            try {
                showToast('🚀 Posting to Facebook...', 'info');
                const submitBtn = document.querySelector('#postForm button[type="submit"]');
                submitBtn.disabled = true;
                submitBtn.innerHTML = '⏳ Posting...';
                const response = await fetch('/api/post/now', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: content, image_url: mediaUrl || null, image_urls: mediaUrl ? [mediaUrl] : [], post_id: postId })
                });
                const data = await response.json();
                if (data.success) {
                    showToast('✅ Posted to Facebook successfully!', 'success');
                    document.getElementById('postForm').reset();
                    document.getElementById('postForm').dataset.postId = '';
                    document.getElementById('postResult').innerHTML = '<div style="background:#e8f5e9;border:1px solid #28a745;border-radius:8px;padding:16px;margin-top:16px;"><strong>✅ Posted Successfully!</strong><br>📝 ' + content.substring(0, 100) + (content.length > 100 ? '...' : '') + '<br>' + (mediaUrl ? '🖼️ With image<br>' : '') + '🆔 Post ID: ' + data.post_id + '<br>🔗 <a href="' + data.url + '" target="_blank">View Post</a></div>';
                    loadHistory();
                    allPosts = allPosts.filter(function(p) { return p.id !== postId; });
                    renderPosts(allPosts);
                    updateStats(allPosts);
                    updateFilters(allPosts);
                    showToast('✅ Post removed from feed', 'info');
                } else {
                    throw new Error(data.error || 'Failed to post');
                }
            } catch (error) {
                showToast('❌ Error: ' + error.message, 'error');
                document.getElementById('postResult').innerHTML = '<div style="background:#ffebee;border:1px solid #dc3545;border-radius:8px;padding:16px;margin-top:16px;"><strong>❌ Failed to Post</strong><br>' + error.message + '</div>';
            } finally {
                const submitBtn = document.querySelector('#postForm button[type="submit"]');
                submitBtn.disabled = false;
                submitBtn.innerHTML = '🚀 Post Now';
            }
        }
        
        // ============================================================
        // SUBMIT SCHEDULE - WITH REMOVE FROM FEED
        // ============================================================
        async function submitSchedule(e) {
            e.preventDefault();
            const content = document.getElementById('scheduleContent').value;
            const scheduledTime = document.getElementById('scheduleTime').value;
            const mediaUrl = document.getElementById('scheduleMedia').value;
            const postId = document.getElementById('scheduleForm').dataset.postId || null;
            if (!content) { showToast('❌ Please enter post content', 'error'); return; }
            if (!scheduledTime) { showToast('❌ Please select a date and time', 'error'); return; }
            const selectedDate = new Date(scheduledTime);
            const now = new Date();
            const minTime = new Date(now.getTime() + 5 * 60000);
            if (selectedDate < minTime) {
                showToast('⏰ Scheduled time must be at least 5 minutes from now', 'error', 5000);
                document.getElementById('scheduleTime').style.borderColor = '#dc3545';
                setTimeout(function() { document.getElementById('scheduleTime').style.borderColor = ''; }, 3000);
                return;
            }
            try {
                showToast('📅 Scheduling post...', 'info');
                const submitBtn = document.querySelector('#scheduleForm button[type="submit"]');
                submitBtn.disabled = true;
                submitBtn.innerHTML = '⏳ Scheduling...';
                const utcDate = new Date(selectedDate.getTime() - (selectedDate.getTimezoneOffset() * 60000));
                const scheduledIso = utcDate.toISOString();
                const response = await fetch('/api/post/schedule', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: content, scheduled_time: scheduledIso, image_urls: mediaUrl ? [mediaUrl] : [], post_id: postId })
                });
                const data = await response.json();
                if (data.success) {
                    const displayTime = selectedDate.toLocaleString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
                    showToast('✅ Scheduled for ' + displayTime, 'success');
                    document.getElementById('scheduleForm').reset();
                    document.getElementById('scheduleForm').dataset.postId = '';
                    document.getElementById('scheduleResult').innerHTML = '<div style="background:#e8f5e9;border:1px solid #28a745;border-radius:8px;padding:16px;margin-top:16px;"><strong>✅ Scheduled Successfully!</strong><br>📝 ' + content.substring(0, 100) + (content.length > 100 ? '...' : '') + '<br>' + (mediaUrl ? '🖼️ With image<br>' : '') + '🕐 Scheduled for: ' + displayTime + '<br>🆔 Post ID: ' + (data.post_id || 'scheduled') + '</div>';
                    loadHistory();
                    allPosts = allPosts.filter(function(p) { return p.id !== postId; });
                    renderPosts(allPosts);
                    updateStats(allPosts);
                    updateFilters(allPosts);
                    showToast('✅ Post removed from feed', 'info');
                } else {
                    if (data.error && (data.error.includes('409') || data.error.includes('already scheduled'))) {
                        showToast('⚠️ This content was already scheduled recently. Please use different content.', 'warning', 5000);
                    } else {
                        throw new Error(data.error || 'Failed to schedule');
                    }
                }
            } catch (error) {
                showToast('❌ Error: ' + error.message, 'error');
                document.getElementById('scheduleResult').innerHTML = '<div style="background:#ffebee;border:1px solid #dc3545;border-radius:8px;padding:16px;margin-top:16px;"><strong>❌ Failed to Schedule</strong><br>' + error.message + '</div>';
            } finally {
                const submitBtn = document.querySelector('#scheduleForm button[type="submit"]');
                submitBtn.disabled = false;
                submitBtn.innerHTML = '📅 Schedule Post';
            }
        }
        
        // ============================================================
        // LOAD HISTORY
        // ============================================================
        async function loadHistory() {
            try {
                const response = await fetch('/api/history');
                const data = await response.json();
                const container = document.getElementById('historyList');
                if (data.success && data.history && data.history.length > 0) {
                    var html = '';
                    data.history.slice().reverse().forEach(function(post) {
                        const isScheduled = post.scheduled_for && !post.posted_at;
                        const badge = isScheduled ? 'badge-scheduled' : 'badge-facebook';
                        const badgeText = isScheduled ? '📅 Scheduled' : 'Facebook';
                        const timeText = isScheduled ? post.scheduled_for : (post.posted_at || post.time || 'Now');
                        html += '<div class="queue-item"><div class="info">';
                        html += '<div class="title">' + (isScheduled ? '📅 ' : '✅ ') + (post.content || '').slice(0,100) + '...</div>';
                        html += '<div class="details"><span class="' + badge + '">' + badgeText + '</span> • 🕐 ' + timeText + (post.url ? ' • <a href="' + post.url + '" target="_blank">View</a>' : '') + '</div></div>';
                        html += '</div>';
                    });
                    container.innerHTML = html;
                } else {
                    container.innerHTML = '<p style="color:#868e96;">No posts published yet</p>';
                }
            } catch (error) {
                document.getElementById('historyList').innerHTML = '<p style="color:#868e96;">Error loading history</p>';
            }
        }
        
        // ============================================================
        // INITIALIZATION
        // ============================================================
        document.addEventListener('DOMContentLoaded', function() {
            loadFromCacheOnStart();
            loadHistory();
            loadProfileId();
            loadSourcesInfo();
            setDefaultScheduleTime();
            updateTimeHint();
            document.querySelectorAll('.filter-btn').forEach(function(btn) {
                btn.addEventListener('click', function() {
                    document.querySelectorAll('.filter-btn').forEach(function(b) { b.classList.remove('active'); });
                    this.classList.add('active');
                    currentFilter = this.dataset.filter;
                    renderPosts(allPosts);
                });
            });
        });
        
        document.addEventListener('keydown', function(e) {
            if (e.key === 'r' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); fetchPosts(); }
            if (e.key === 'Escape') { closeModal(); document.querySelectorAll('.toast').forEach(function(t) { t.remove(); }); }
        });
    </script>
</body>
</html>
'''

# ============================================================
# FLASK ROUTES
# ============================================================

@app.route('/')
def home():
    return render_template_string(DASHBOARD_HTML)

# ============================================================
# SOURCES ROUTE - Using Source Manager
# ============================================================

@app.route('/api/sources', methods=['GET'])
def get_sources():
    """Get configured source accounts using SourceManager"""
    try:
        if SOURCE_MANAGER_AVAILABLE:
            manager = SourceManager()
            sources = manager.get_sources()
            summary = manager.get_sources_summary()
        else:
            from config import SOURCE_ACCOUNTS
            sources = SOURCE_ACCOUNTS
            summary = {'total': len(sources), 'categories': {}, 'source_names': []}
        
        return jsonify({
            'success': True,
            'count': len(sources),
            'sources': sources,
            'summary': summary
        })
    except Exception as e:
        logger.error(f"Error getting sources: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

# ============================================================
# POST FETCHING ROUTES
# ============================================================

@app.route('/api/posts', methods=['GET'])
def get_posts():
    limit = request.args.get('limit', 9, type=int)
    try:
        logger.info(f"Fetching {limit} posts per source...")
        posts = fetch_facebook_posts(limit)
        save_posts(posts)
        
        # Get processed and removed post IDs
        processed = get_processed_posts()
        removed = get_removed_posts()
        
        # Filter out processed AND removed posts
        filtered_posts = [p for p in posts if p.get('id') not in processed and p.get('id') not in removed]
        
        logger.info(f"📊 Total: {len(posts)} fetched, {len(filtered_posts)} available, {len(processed)} processed, {len(removed)} removed")
        
        return jsonify({
            'success': True,
            'count': len(filtered_posts),
            'posts': filtered_posts,
            'total_fetched': len(posts),
            'processed_count': len(processed),
            'removed_count': len(removed),
            'fetched_at': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error fetching posts: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/cache', methods=['GET'])
def get_cache():
    posts = load_posts()
    processed = get_processed_posts()
    removed = get_removed_posts()
    filtered_posts = [p for p in posts if p.get('id') not in processed and p.get('id') not in removed]
    return jsonify({
        'success': True,
        'count': len(filtered_posts),
        'posts': filtered_posts,
        'from_cache': True
    })

@app.route('/api/cache/clear', methods=['DELETE'])
def clear_cache():
    try:
        if os.path.exists(POSTS_FILE_FALLBACK):
            os.remove(POSTS_FILE_FALLBACK)
        clear_processed_posts()
        clear_removed_posts()
        return jsonify({'success': True, 'message': 'Cache cleared'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# REMOVE POST ROUTE - PERSISTENT
# ============================================================

@app.route('/api/post/remove', methods=['POST'])
def remove_post():
    """Manually remove a post from the feed (persistent)"""
    data = request.json
    post_id = data.get('post_id')
    
    if not post_id:
        return jsonify({'success': False, 'error': 'Post ID is required'}), 400
    
    try:
        # Mark as removed in Redis
        mark_post_as_removed(post_id)
        logger.info(f"🗑️ Post {post_id} removed by user")
        
        return jsonify({
            'success': True,
            'message': 'Post removed successfully',
            'post_id': post_id
        })
    except Exception as e:
        logger.error(f"Error removing post: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# CONFIG ROUTE
# ============================================================

@app.route('/api/config/facebook-profile-id', methods=['GET'])
def get_facebook_profile_id():
    try:
        return jsonify({
            'success': True,
            'profile_id': FACEBOOK_PROFILE_ID
        })
    except Exception as e:
        logger.error(f"Error getting profile ID: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

# ============================================================
# DOWNLOAD ROUTES
# ============================================================

@app.route('/api/download/jpg', methods=['POST'])
def download_post_jpg():
    try:
        data = request.json
        text = data.get('text', 'No content')
        source = data.get('source', 'Unknown')
        
        img_bytes = create_post_image(text, source)
        if img_bytes:
            return send_file(
                img_bytes,
                mimetype='image/jpeg',
                as_attachment=True,
                download_name=f'post_{datetime.now().strftime("%Y%m%d_%H%M%S")}.jpg'
            )
        else:
            return jsonify({'success': False, 'error': 'Failed to generate image'}), 500
    except Exception as e:
        logger.error(f"Error generating JPG: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/download/single-image', methods=['POST'])
def download_single_image():
    try:
        data = request.json
        image_url = data.get('image_url')
        filename = data.get('filename', 'image')
        
        if not image_url:
            return jsonify({"success": False, "error": "No image URL provided"}), 400
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Referer': 'https://www.facebook.com/',
        }
        
        response = requests.get(image_url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            return jsonify({"success": False, "error": "Failed to download image"}), 500
        
        content_type = response.headers.get('content-type', 'image/jpeg')
        ext = 'jpg'
        if 'png' in content_type:
            ext = 'png'
        elif 'gif' in content_type:
            ext = 'gif'
        elif 'webp' in content_type:
            ext = 'webp'
        
        return send_file(
            io.BytesIO(response.content),
            mimetype=content_type,
            as_attachment=True,
            download_name=f"{filename}.{ext}"
        )
    except Exception as e:
        logger.error(f"Error downloading image: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================
# POST NOW ROUTE
# ============================================================

@app.route('/api/post/now', methods=['POST'])
def post_to_facebook_now():
    data = request.json
    
    try:
        content = data.get('content')
        image_url = data.get('image_url')
        image_urls = data.get('image_urls', [])
        post_id = data.get('post_id')
        
        if not content:
            return jsonify({'success': False, 'error': 'Content is required'}), 400
        
        logger.info(f"📨 Post Now: {content[:50]}...")
        
        if image_urls and len(image_urls) > 0:
            result = facebook_poster.post_with_images(content, image_urls)
        elif image_url:
            result = facebook_poster.post_with_image(content, image_url)
        else:
            result = facebook_poster.post_text(content)
        
        if result.get('success'):
            if post_id:
                mark_post_as_processed(post_id)
            
            history = load_history()
            history.append({
                'id': result.get('post_id', 'unknown'),
                'content': content,
                'platform': 'facebook',
                'posted_at': datetime.now().isoformat(),
                'url': result.get('url', ''),
                'original_post_id': post_id
            })
            save_history(history)
            logger.info(f"✅ Post successful: {result.get('post_id')}")
        else:
            logger.error(f"❌ Post failed: {result.get('error')}")
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error posting: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

# ============================================================
# SCHEDULE ROUTE
# ============================================================

@app.route('/api/post/schedule', methods=['POST'])
def schedule_facebook_post():
    data = request.json
    
    try:
        content = data.get('content')
        scheduled_time = data.get('scheduled_time')
        image_urls = data.get('image_urls', [])
        post_id = data.get('post_id')
        
        if not content:
            return jsonify({'success': False, 'error': 'Content is required'}), 400
        
        if not scheduled_time:
            return jsonify({'success': False, 'error': 'Scheduled time is required'}), 400
        
        if 'Z' in scheduled_time:
            scheduled_time = scheduled_time.replace('Z', '')
        if '+' in scheduled_time:
            scheduled_time = scheduled_time.split('+')[0]
        if 'T' not in scheduled_time:
            try:
                dt = datetime.fromisoformat(scheduled_time)
                scheduled_time = dt.strftime("%Y-%m-%dT%H:%M:%S")
            except:
                pass
        
        logger.info(f"📅 Schedule: {content[:50]}... at {scheduled_time}")
        
        result = facebook_poster.schedule_post(content, scheduled_time, image_urls)
        
        if result.get('success'):
            if post_id:
                mark_post_as_processed(post_id)
            
            history = load_history()
            history.append({
                'id': result.get('post_id', 'scheduled'),
                'content': content,
                'platform': 'facebook',
                'scheduled_for': scheduled_time,
                'status': result.get('status', 'scheduled'),
                'url': result.get('url', ''),
                'type': 'scheduled',
                'original_post_id': post_id
            })
            save_history(history)
            logger.info(f"✅ Post scheduled: {result.get('post_id')}")
        else:
            logger.error(f"❌ Schedule failed: {result.get('error')}")
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error scheduling: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

# ============================================================
# HISTORY ROUTE
# ============================================================

@app.route('/api/history', methods=['GET'])
def get_history():
    try:
        history = load_history()
        return jsonify({
            'success': True,
            'history': history
        })
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

# ============================================================
# HEALTH CHECK
# ============================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    processed = get_processed_posts()
    removed = get_removed_posts()
    status = {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'redis': {
            'available': REDIS_AVAILABLE,
            'connected': REDIS_AVAILABLE
        },
        'storage': {
            'type': 'redis' if REDIS_AVAILABLE else 'file',
            'directory': DATA_DIR
        },
        'timezone': TIMEZONE,
        'processed_count': len(processed),
        'removed_count': len(removed)
    }
    
    if REDIS_AVAILABLE and redis:
        try:
            redis.ping()
            status['redis']['connected'] = True
        except:
            status['redis']['connected'] = False
    
    return jsonify(status)

# ============================================================
# RUN SERVER
# ============================================================

if __name__ == '__main__':
    logger.info("🚀 Starting Social Feed Dashboard - Complete")
    logger.info("📱 Open http://localhost:5000")
    logger.info(f"🌍 Timezone: {TIMEZONE} (GMT+3)")
    logger.info(f"📘 Facebook Profile ID: {FACEBOOK_PROFILE_ID}")
    logger.info(f"💾 Storage: {'Redis' if REDIS_AVAILABLE else 'File (fallback)'}")
    app.run(debug=True, host='0.0.0.0', port=5000)