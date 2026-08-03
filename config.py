# ============================================================
# CONFIGURATION FILE
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# API KEYS
# ============================================================

# SocialAPIs.io API Token
# Get yours from: https://socialapis.io/dashboard
SOCIAL_API_TOKEN = os.environ.get('SOCIAL_API_TOKEN', 'd4233569ef8db1ff6d9659f2b37efa4a58e38578b505df84fb2f6ef8f1a6f70b')

# Zernio API Key for scheduling
# Get yours from: https://zernio.com/dashboard
ZERNIO_API_KEY = os.environ.get('ZERNIO_API_KEY', 'sk_9d50208c1fc5ee719a7c50e639270ced37049c39b517b06cc8fce3fc6f5da6de')

# Facebook Profile ID in Zernio (this is Zernio's ID for your Facebook account)
FACEBOOK_PROFILE_ID = os.environ.get('FACEBOOK_PROFILE_ID', '6a6a3443df17280d93d5d359')

# ============================================================
# UPSTASH REDIS (for Vercel deployment)
# ============================================================

# Get from: https://console.upstash.com/redis
UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_REST_URL', '')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')

# ============================================================
# SOURCE ACCOUNTS (For Fetching Posts)
# ============================================================

SOURCE_ACCOUNTS = [
    {
        "id": "billionaire_vision",
        "name": "Billionaire Vision",
        "url": "https://www.facebook.com/profile.php?id=61590243822144",
        "category": "Motivation",
        "priority": 1
    },
    {
        "id": "unexpressedfeelings",
        "name": "Unexpressed Feelings",
        "url": "https://www.facebook.com/UnexpressedFeelings4U",
        "category": "Inspiration",
        "priority": 2
    },
    {
        "id": "lovequotesmedia",
        "name": "Love Quotes Media",
        "url": "https://www.facebook.com/lovequotesmedia",
        "category": "Inspiration",
        "priority": 3
    }
]

# ============================================================
# SCHEDULING ACCOUNTS (For Posting To)
# ============================================================

SCHEDULE_ACCOUNTS = [
    {
        "id": "facebook_page_1",
        "platform": "facebook",
        "name": "Your Facebook Page",
        "account_id": FACEBOOK_PROFILE_ID
    }
]

# ============================================================
# REDIS KEYS
# ============================================================

REDIS_KEY_POSTS = "social_feed:posts"
REDIS_KEY_HISTORY = "social_feed:history"
REDIS_KEY_SCHEDULED = "social_feed:scheduled"

# Redis TTL (seconds)
REDIS_TTL_POSTS = 86400      # 24 hours
REDIS_TTL_HISTORY = 2592000  # 30 days
REDIS_TTL_SCHEDULED = 2592000  # 30 days

# ============================================================
# SCHEDULING DEFAULTS
# ============================================================

DEFAULT_SLOTS = [
    "09:00",
    "12:00",
    "17:00",
    "20:00"
]

DEFAULT_PLATFORMS = ["facebook"]

# ============================================================
# TIMEZONE SETTINGS
# ============================================================

TIMEZONE = os.environ.get('TIMEZONE', 'Africa/Nairobi')

# ============================================================
# LOGGING
# ============================================================

LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

# ============================================================
# CACHE SETTINGS
# ============================================================

# File cache (fallback for local development)
CACHE_FILE = 'posts_cache.json'
SCHEDULE_CACHE_FILE = 'schedule_cache.json'
CACHE_EXPIRY_HOURS = 24

# ============================================================
# POST FETCHING SETTINGS
# ============================================================

MAX_POSTS_PER_SOURCE = 9
MAX_IMAGES_PER_POST = 5

# ============================================================
# UI SETTINGS
# ============================================================

DASHBOARD_TITLE = "Social Feed Dashboard"
DASHBOARD_THEME = "dark"
AUTO_REFRESH_INTERVAL = 60

# ============================================================
# VALIDATION
# ============================================================

def validate_config():
    """Validate configuration settings"""
    errors = []
    warnings = []
    
    # API Keys
    if not SOCIAL_API_TOKEN or SOCIAL_API_TOKEN == "your-api-token-here":
        errors.append("SOCIAL_API_TOKEN is not set.")
    
    if not ZERNIO_API_KEY or ZERNIO_API_KEY == "your-zernio-api-key-here":
        errors.append("ZERNIO_API_KEY is not set.")
    
    if not SOURCE_ACCOUNTS:
        errors.append("No source accounts configured.")
    
    # Redis (warning only - will fallback to file)
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        warnings.append("UPSTASH_REDIS not configured - will use file storage (not recommended for Vercel)")
    
    if errors:
        print("\n⚠️  Configuration Errors:")
        for error in errors:
            print(f"  ❌ {error}")
        print("\n")
        return False
    
    print("\n✅ Configuration validated successfully!")
    print(f"📡 {len(SOURCE_ACCOUNTS)} source accounts configured")
    print(f"📤 {len(SCHEDULE_ACCOUNTS)} scheduling accounts configured")
    print(f"📘 Facebook Profile ID: {FACEBOOK_PROFILE_ID}")
    
    if warnings:
        print("\n⚠️  Warnings:")
        for warning in warnings:
            print(f"  ⚠️ {warning}")
    
    # Redis status
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        print(f"✅ Redis configured: {UPSTASH_REDIS_URL[:30]}...")
    else:
        print("⚠️ Redis not configured - using file storage")
    
    print(f"🌍 Timezone: {TIMEZONE}")
    print("\n" + "=" * 50)
    return True

# Auto-validate on import
if __name__ != '__main__':
    validate_config()