# ============================================================
# FACEBOOK POST FETCHER - NO DEDUPLICATION
# ============================================================

import requests
import json
import re
from datetime import datetime
from config import SOCIAL_API_TOKEN, SOURCE_ACCOUNTS
from time_utils import convert_to_kenya_time, format_kenya_datetime

def fetch_facebook_posts(limit=9):
    """
    Fetch posts from ALL sources.
    Returns up to limit × number of sources.
    NO DEDUPLICATION - fetches fresh every time.
    """
    all_posts = []
    per_source_limit = limit
    
    # Sort sources by priority
    sorted_sources = sorted(SOURCE_ACCOUNTS, key=lambda x: x.get('priority', 999))
    
    print(f"  📡 Fetching {per_source_limit} posts from EACH of {len(sorted_sources)} sources...")
    
    # Fetch from ALL sources
    for source in sorted_sources:
        source_name = source.get('name')
        source_url = source.get('url')
        source_priority = source.get('priority', 999)
        
        print(f"    📋 {source_name} (Priority {source_priority})...")
        
        # Fetch posts from this source
        posts = fetch_from_source(source_url, per_source_limit)
        
        if not posts:
            print(f"      📭 No posts from {source_name}")
            continue
        
        # Add source info to each post
        for post in posts:
            post['source_id'] = source.get('id')
            post['source_name'] = source_name
            post['source_url'] = source_url
            post['source_priority'] = source_priority
        
        print(f"      ✅ Found {len(posts)} posts from {source_name}")
        all_posts.extend(posts)
    
    # Sort by time (newest first)
    all_posts.sort(key=lambda x: x.get('time_original', ''), reverse=True)
    
    print(f"  📊 Total: {len(all_posts)} posts collected from all sources")
    
    return all_posts

def fetch_from_source(page_url, limit=9):
    """
    Fetch posts from a single source URL.
    Returns up to 'limit' posts (default 9).
    """
    url = "https://api.socialapis.io/facebook/pages/posts"
    headers = {"x-api-token": SOCIAL_API_TOKEN}
    params = {
        "link": page_url,
        "limit": limit
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            posts_data = result.get("data", {})
            posts = posts_data.get("posts", [])
            
            if not posts:
                return []
            
            formatted_posts = []
            for post in posts:
                details = post.get("details", {})
                values = post.get("values", {})
                reactions = post.get("reactions", {})
                
                # Get text
                text = values.get("text")
                if text is None:
                    text = ""
                elif not isinstance(text, str):
                    text = str(text)
                
                # Clean text
                text = clean_text_strong(text)
                
                # Get time and convert to Kenya time
                publish_time = values.get("publish_time")
                kenya_time_str = format_time_to_kenya(publish_time)
                
                # Extract images
                image_urls = extract_image_urls(post)
                
                formatted_post = {
                    "id": details.get("post_id", "N/A"),
                    "text": text,
                    "time": kenya_time_str,
                    "time_original": publish_time,
                    "images": image_urls if image_urls else [],
                    "reactions": reactions.get("total_reaction_count", 0),
                    "comments": details.get("comments_count", 0),
                    "shares": details.get("share_count", 0),
                    "post_link": details.get("post_link", ""),
                    "fetched_at": format_kenya_datetime()
                }
                
                # Only add if it has text OR images
                if text or image_urls:
                    formatted_posts.append(formatted_post)
            
            return formatted_posts
            
        else:
            print(f"      ❌ API Error {response.status_code}")
            print(f"      Response: {response.text[:200]}")
            return []
            
    except Exception as e:
        print(f"      ❌ Error fetching: {e}")
        return []

# ============================================================
# TIME FORMATTING FUNCTION
# ============================================================

def format_time_to_kenya(time_str):
    """Convert API time string to Kenya time format"""
    if not time_str or time_str == "N/A":
        return "N/A"
    
    try:
        if 'T' in str(time_str):
            clean_time = str(time_str).replace('Z', '+00:00')
            dt = datetime.fromisoformat(clean_time)
            kenya_dt = convert_to_kenya_time(dt)
            return kenya_dt.strftime("%d/%m/%Y, %I:%M %p")
        else:
            return str(time_str)
    except Exception as e:
        return str(time_str)

# ============================================================
# TEXT CLEANING FUNCTION
# ============================================================

def clean_text_strong(text):
    """Clean text by removing quotes and fixing encoding"""
    if not text:
        return text
    
    # Remove quotes
    quote_chars = ['"', "'", '“', '”', '‘', '’', '`', '´']
    while text and text[0] in quote_chars:
        text = text[1:]
    while text and text[-1] in quote_chars:
        text = text[:-1]
    
    # Fix Unicode escapes
    try:
        if '\\u' in text:
            text = text.encode('utf-8').decode('unicode-escape')
    except:
        pass
    
    # Fix common emojis
    replacements = {
        '\\u2764\\ufe0f': '❤️',
        '\\u2764': '❤️',
        '\\ufe0f': '',
        '\\u1f60d': '😍',
        '\\u1f60a': '😊',
        '\\u1f602': '😂',
        '\\u1f64f': '🙏',
        '\\u1f31f': '🌟',
        '\\u1f44d': '👍',
        '\\u1f44f': '👏',
        '\\u1f4a5': '💥',
        '\\u1f4af': '💯',
        '\\u1f499': '💙',
        '\\u1f49a': '💚',
        '\\u1f49b': '💛',
        '\\u1f49c': '💜',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    text = text.replace('"', '').replace("'", '')
    text = ' '.join(text.split())
    
    return text.strip()

# ============================================================
# IMAGE EXTRACTION - Simplified
# ============================================================

def extract_image_urls(post):
    """Extract image URLs from a post"""
    all_image_urls = []
    
    def add_url(url):
        if url and isinstance(url, str):
            if url.startswith('{"uri":"'):
                try:
                    parsed = json.loads(url)
                    url = parsed.get('uri', url)
                except:
                    pass
            if url.startswith('http'):
                if url not in all_image_urls:
                    all_image_urls.append(url)
    
    # Check values.photo_image
    values = post.get("values", {})
    photo_image = values.get("photo_image")
    if photo_image:
        add_url(photo_image)
    
    # Check details.media
    details = post.get("details", {})
    media = details.get("media", [])
    if media and isinstance(media, list):
        for item in media:
            if isinstance(item, dict):
                for field in ['uri', 'image', 'url', 'src', 'thumbnail']:
                    if field in item and item[field]:
                        add_url(item[field])
    
    # Check details.images
    images_field = details.get("images", [])
    if images_field and isinstance(images_field, list):
        for img in images_field:
            if isinstance(img, str):
                add_url(img)
            elif isinstance(img, dict):
                for key in ['uri', 'url', 'src']:
                    if key in img and img[key]:
                        add_url(img[key])
    
    # If no images found, try regex on the raw post
    if not all_image_urls:
        post_str = json.dumps(post)
        patterns = [
            r'https://[^"]*\.fbcdn\.net[^"]*ctp=s1080x1350[^"]*',
            r'https://[^"]*\.fbcdn\.net[^"]*ctp=s640x640[^"]*',
            r'https://[^"]*\.fbcdn\.net[^"]*ctp=s960x960[^"]*',
            r'https://[^"]*\.fbcdn\.net[^"]*_nc_sid=127cfc[^"]*',
            r'https://[^"]*\.fbcdn\.net[^"]*[^"]*\.(jpg|jpeg|png|gif|webp)[^"]*',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, post_str, re.IGNORECASE)
            for url in matches:
                add_url(url)
    
    # Filter for high-quality images
    filtered_images = []
    for url in all_image_urls:
        if 's1080x1350' in url or 's640x640' in url or 's960x960' in url:
            filtered_images.append(url)
        elif 'fbcdn.net' in url and ('.jpg' in url or '.png' in url):
            filtered_images.append(url)
    
    # If no high-quality found, take the first valid image
    if not filtered_images and all_image_urls:
        filtered_images = [all_image_urls[0]]
    
    return filtered_images[:5]  # Limit to 5 images per post