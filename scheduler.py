# ============================================================
# ZERNIO SCHEDULING INTEGRATION - FIXED
# ============================================================

import os
import json
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

from config import ZERNIO_API_KEY, SCHEDULE_ACCOUNTS, DEFAULT_SLOTS

class SocialScheduler:
    """Main scheduling class using Zernio API"""
    
    def __init__(self):
        self.accounts = SCHEDULE_ACCOUNTS
        self.schedule_file = 'schedule_cache.json'
        self.api_key = ZERNIO_API_KEY
        self.base_url = "https://zernio.com/api/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Check if API key is valid
        self._test_connection()
    
    def _test_connection(self):
        """Test if the API key is valid"""
        try:
            response = requests.get(
                f"{self.base_url}/accounts",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                logger.info("✅ Zernio API connection successful")
                self.connected = True
            else:
                logger.warning(f"⚠️ Zernio API connection failed: {response.status_code}")
                self.connected = False
        except Exception as e:
            logger.warning(f"⚠️ Zernio API connection error: {e}")
            self.connected = False
    
    def is_available(self):
        """Check if Zernio is available for scheduling"""
        return self.connected
    
    def get_connected_accounts(self):
        """Get all connected social accounts"""
        if not self.is_available():
            return self.accounts
        
        try:
            response = requests.get(
                f"{self.base_url}/accounts",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('accounts', self.accounts)
            return self.accounts
        except Exception as e:
            logger.error(f"Error fetching accounts: {e}")
            return self.accounts
    
    def schedule_post(self, content: str, platforms: List[Dict], scheduled_time: Optional[str] = None, media_urls: List[str] = None):
        """
        Schedule a post to multiple platforms
        
        Args:
            content: Post text content
            platforms: List of platform dicts with 'platform' and 'account_id'
            scheduled_time: ISO format datetime (e.g., "2025-02-01T10:00:00Z")
            media_urls: List of image/video URLs
        
        Returns:
            Scheduled post object
        """
        # If Zernio is not available, save to local cache only
        if not self.is_available():
            logger.warning("📝 Zernio not available - saving to local cache only")
            post = {
                "id": f"local_{int(datetime.now().timestamp())}",
                "content": content,
                "platforms": platforms,
                "scheduled_for": scheduled_time,
                "media_urls": media_urls or [],
                "status": "scheduled_local",
                "created_at": datetime.now().isoformat()
            }
            self._save_to_cache(post)
            return post
        
        try:
            # Prepare the post data
            post_data = {
                "content": content,
                "platforms": []
            }
            
            # Format platforms
            for p in platforms:
                post_data["platforms"].append({
                    "platform": p.get("platform"),
                    "account_id": p.get("account_id")
                })
            
            if media_urls:
                post_data["media_urls"] = media_urls
            
            if scheduled_time:
                post_data["scheduled_for"] = scheduled_time
            else:
                post_data["publish_now"] = True
            
            # Make the API request
            response = requests.post(
                f"{self.base_url}/posts",
                headers=self.headers,
                json=post_data,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                post = response.json()
                self._save_to_cache(post)
                logger.info(f"✅ Post scheduled successfully: {post.get('id')}")
                return post
            else:
                error_msg = response.json().get('message', 'Unknown error')
                logger.error(f"❌ Failed to schedule: {response.status_code} - {error_msg}")
                
                # Fallback to local cache
                post = {
                    "id": f"local_{int(datetime.now().timestamp())}",
                    "content": content,
                    "platforms": platforms,
                    "scheduled_for": scheduled_time,
                    "media_urls": media_urls or [],
                    "status": "scheduled_local",
                    "error": error_msg,
                    "created_at": datetime.now().isoformat()
                }
                self._save_to_cache(post)
                return post
            
        except Exception as e:
            logger.error(f"Error scheduling post: {e}")
            # Fallback to local cache
            post = {
                "id": f"local_{int(datetime.now().timestamp())}",
                "content": content,
                "platforms": platforms,
                "scheduled_for": scheduled_time,
                "media_urls": media_urls or [],
                "status": "scheduled_local",
                "error": str(e),
                "created_at": datetime.now().isoformat()
            }
            self._save_to_cache(post)
            return post
    
    def schedule_bulk(self, posts_batch: List[Dict]):
        """
        Schedule multiple posts at once (bulk upload)
        
        Args:
            posts_batch: List of post dicts with content, platforms, scheduled_time
        """
        results = []
        for post_data in posts_batch:
            result = self.schedule_post(
                content=post_data.get('content'),
                platforms=post_data.get('platforms', []),
                scheduled_time=post_data.get('scheduled_time'),
                media_urls=post_data.get('media_urls', [])
            )
            results.append(result)
        
        logger.info(f"📦 Bulk scheduled {len(results)} posts")
        return results
    
    def get_queue(self, limit: int = 50):
        """Get upcoming scheduled posts"""
        # First try to get from Zernio
        if self.is_available():
            try:
                response = requests.get(
                    f"{self.base_url}/posts",
                    headers=self.headers,
                    params={"status": "scheduled", "limit": limit},
                    timeout=10
                )
                if response.status_code == 200:
                    data = response.json()
                    posts = data.get('posts', [])
                    if posts:
                        return posts
                else:
                    logger.warning(f"Failed to fetch queue: {response.status_code}")
            except Exception as e:
                logger.error(f"Error fetching queue: {e}")
        
        # Fallback to local cache
        return self._load_from_cache()
    
    def get_published_posts(self, limit: int = 50):
        """Get published posts history"""
        if self.is_available():
            try:
                response = requests.get(
                    f"{self.base_url}/posts",
                    headers=self.headers,
                    params={"status": "published", "limit": limit},
                    timeout=10
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get('posts', [])
            except Exception as e:
                logger.error(f"Error fetching published posts: {e}")
        return []
    
    def cancel_post(self, post_id: str):
        """Cancel a scheduled post"""
        if self.is_available():
            try:
                response = requests.delete(
                    f"{self.base_url}/posts/{post_id}",
                    headers=self.headers,
                    timeout=10
                )
                if response.status_code in [200, 204]:
                    logger.info(f"❌ Post cancelled: {post_id}")
                    return {"success": True, "post_id": post_id}
            except Exception as e:
                logger.error(f"Error cancelling post: {e}")
        
        # Remove from local cache
        cache = self._load_from_cache()
        cache = [p for p in cache if p.get('id') != post_id]
        self._save_cache(cache)
        return {"success": True, "post_id": post_id, "from_cache": True}
    
    def get_analytics(self, post_id: str):
        """Get analytics for a published post"""
        if self.is_available():
            try:
                response = requests.get(
                    f"{self.base_url}/posts/{post_id}/analytics",
                    headers=self.headers,
                    timeout=10
                )
                if response.status_code == 200:
                    return response.json()
            except Exception as e:
                logger.error(f"Error fetching analytics: {e}")
        return None
    
    def get_slots(self, date: Optional[str] = None):
        """
        Get available scheduling slots for the day
        
        Args:
            date: Date string (YYYY-MM-DD), defaults to today
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        if self.is_available():
            try:
                response = requests.get(
                    f"{self.base_url}/queue/slots",
                    headers=self.headers,
                    params={"date": date},
                    timeout=10
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get('slots', DEFAULT_SLOTS)
            except Exception as e:
                logger.error(f"Error fetching slots: {e}")
        
        # Return default slots
        return [
            {
                'time': slot,
                'available': True
            }
            for slot in DEFAULT_SLOTS
        ]
    
    def _save_to_cache(self, post):
        """Save scheduled post to local cache"""
        try:
            cache = self._load_from_cache()
            # Check if post already exists
            existing = [p for p in cache if p.get('id') == post.get('id')]
            if not existing:
                cache.append({
                    'post': post,
                    'scheduled_at': post.get('scheduled_for'),
                    'created_at': datetime.now().isoformat()
                })
            self._save_cache(cache)
        except Exception as e:
            logger.error(f"Error saving to cache: {e}")
    
    def _save_cache(self, cache):
        """Save cache to file"""
        try:
            with open(self.schedule_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving cache: {e}")
    
    def _load_from_cache(self):
        """Load scheduled posts from cache"""
        try:
            if os.path.exists(self.schedule_file):
                with open(self.schedule_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Extract posts from cache entries
                    return [item.get('post') for item in data if item.get('post')]
        except Exception as e:
            logger.error(f"Error loading from cache: {e}")
        return []

# ============================================================
# HELPER FUNCTIONS FOR EASY ACCESS
# ============================================================

scheduler = SocialScheduler()

def get_schedule_accounts():
    """Get connected accounts for scheduling"""
    return scheduler.get_connected_accounts()

def schedule_post(content, platforms, scheduled_time=None, media_urls=None):
    """Quick schedule function"""
    return scheduler.schedule_post(content, platforms, scheduled_time, media_urls)

def get_queue(limit=50):
    """Get scheduled queue"""
    return scheduler.get_queue(limit)

def cancel_post(post_id):
    """Cancel a scheduled post"""
    return scheduler.cancel_post(post_id)

def get_analytics(post_id):
    """Get post analytics"""
    return scheduler.get_analytics(post_id)