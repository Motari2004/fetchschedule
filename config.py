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
SOCIAL_API_TOKEN = "d4233569ef8db1ff6d9659f2b37efa4a58e38578b505df84fb2f6ef8f1a6f70b"

# Zernio API Key for scheduling
# Get yours from: https://zernio.com/dashboard
ZERNIO_API_KEY = "sk_9d50208c1fc5ee719a7c50e639270ced37049c39b517b06cc8fce3fc6f5da6de"

# Facebook Profile ID in Zernio (this is Zernio's ID for your Facebook account)
FACEBOOK_PROFILE_ID = "6a6a3443df17280d93d5d359"

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
        "account_id": FACEBOOK_PROFILE_ID  # Using your Zernio Profile ID
    }
]

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

TIMEZONE = 'Africa/Nairobi'

# ============================================================
# LOGGING
# ============================================================

LOG_LEVEL = 'INFO'

# ============================================================
# CACHE SETTINGS
# ============================================================

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
    
    if not SOCIAL_API_TOKEN or SOCIAL_API_TOKEN == "your-api-token-here":
        errors.append("SOCIAL_API_TOKEN is not set.")
    
    if not ZERNIO_API_KEY or ZERNIO_API_KEY == "your-zernio-api-key-here":
        errors.append("ZERNIO_API_KEY is not set.")
    
    if not SOURCE_ACCOUNTS:
        errors.append("No source accounts configured.")
    
    if errors:
        print("\n⚠️  Configuration Warnings:")
        for error in errors:
            print(f"  • {error}")
        print("\n")
        return False
    
    print("✅ Configuration validated successfully!")
    print(f"📡 {len(SOURCE_ACCOUNTS)} source accounts configured")
    print(f"📤 {len(SCHEDULE_ACCOUNTS)} scheduling accounts configured")
    print(f"📘 Facebook Profile ID: {FACEBOOK_PROFILE_ID}")
    return True

# Auto-validate on import
if __name__ != '__main__':
    validate_config()