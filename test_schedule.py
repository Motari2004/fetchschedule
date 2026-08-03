# schedule_post.py - Schedule ONE post to Facebook
import os
from datetime import datetime, timedelta
import pytz
from zernio import Zernio

# ============================================================
# CONFIGURATION
# ============================================================

ZERNIO_API_KEY = "sk_9d50208c1fc5ee719a7c50e639270ced37049c39b517b06cc8fce3fc6f5da6de"
FACEBOOK_PROFILE_ID = "6a6a3443df17280d93d5d359"
TIMEZONE = "Africa/Nairobi"  # GMT+3

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def clean_status(status):
    """Clean up status string from enum"""
    if not status:
        return "unknown"
    
    status_str = str(status)
    # Remove enum prefixes
    if 'Status11.' in status_str:
        status_str = status_str.replace('Status11.', '')
    if 'status11.' in status_str:
        status_str = status_str.replace('status11.', '')
    
    return status_str.lower()

def schedule_post(content, minutes_ahead=10, image_url=None):
    """
    Schedule a post to Facebook
    
    Args:
        content: Post text content
        minutes_ahead: Minutes from now to schedule (default: 10)
        image_url: Optional image URL
    """
    
    print("=" * 60)
    print("📅 SCHEDULE POST TO FACEBOOK")
    print("=" * 60)
    
    try:
        # Initialize Zernio client
        client = Zernio(api_key=ZERNIO_API_KEY)
        print("✅ Zernio client initialized")
        
        # Get current time in GMT+3
        local_tz = pytz.timezone(TIMEZONE)
        now_local = datetime.now(local_tz)
        
        # Schedule time
        scheduled_time = now_local + timedelta(minutes=minutes_ahead)
        scheduled_local_str = scheduled_time.strftime("%Y-%m-%dT%H:%M:%S")
        
        print(f"\n📝 Post Content:")
        print(f"  {content}")
        print(f"\n🕐 Current Time: {now_local.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🕐 Scheduled Time: {scheduled_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🕐 UTC Time: {scheduled_time.astimezone(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"🌍 Timezone: {TIMEZONE}")
        print(f"📘 Facebook Profile ID: {FACEBOOK_PROFILE_ID}")
        if image_url:
            print(f"🖼️ Image: {image_url}")
        
        print("\n🔄 Scheduling post...")
        
        # Handle image if provided
        media_items = None
        if image_url:
            # Download and upload image
            import requests
            from io import BytesIO
            
            print("📥 Downloading image...")
            response = requests.get(image_url, timeout=30)
            if response.status_code == 200:
                print("📤 Uploading image to Zernio...")
                media_result = client.media.upload_bytes(
                    BytesIO(response.content).getvalue(),
                    "image.jpg",
                    mime_type=response.headers.get('content-type', 'image/jpeg')
                )
                
                if hasattr(media_result, 'files') and len(media_result.files) > 0:
                    media_url = str(media_result.files[0].url)
                    media_items = [{"url": media_url, "type": "image"}]
                    print(f"✅ Image uploaded: {media_url[:50]}...")
        
        # Create the scheduled post
        post_data = {
            "content": content,
            "platforms": [
                {"platform": "facebook", "accountId": FACEBOOK_PROFILE_ID}
            ],
            "scheduled_for": scheduled_local_str,
            "timezone": TIMEZONE
        }
        
        if media_items:
            post_data["media_items"] = media_items
        
        post = client.posts.create(**post_data)
        
        # Extract post details
        post_id = None
        status = None
        scheduled_for = None
        
        if hasattr(post, 'post'):
            post_obj = post.post
            if hasattr(post_obj, 'field_id'):
                post_id = post_obj.field_id
            if hasattr(post_obj, 'status'):
                status = clean_status(post_obj.status)
            if hasattr(post_obj, 'scheduled_for'):
                scheduled_for = str(post_obj.scheduled_for)
        
        print(f"\n📦 Response:")
        print(f"  ✅ Post ID: {post_id}")
        print(f"  📊 Status: {status}")
        print(f"  📅 Scheduled For: {scheduled_for}")
        
        if status == 'scheduled':
            print(f"\n✅ SUCCESS! Post has been SCHEDULED!")
            print(f"📌 It will be published at {scheduled_time.strftime('%Y-%m-%d %H:%M:%S')} ({TIMEZONE})")
            print(f"🔗 Post ID: {post_id}")
        else:
            print(f"\n⚠️ Post status: {status}")
            print(f"   Expected 'scheduled' but got '{status}'")
        
        print("\n" + "=" * 60)
        return True, {
            'post_id': post_id,
            'status': status,
            'scheduled_time': scheduled_time,
            'scheduled_for': scheduled_for
        }
        
    except Exception as e:
        print(f"\n❌ Failed to schedule post: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Response: {e.response.text[:500]}")
        return False, None

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    # ============================================================
    # OPTION 1: Schedule text-only post
    # ============================================================
    content = "🌟 This is a scheduled post from my Social Feed Dashboard! \n\nStay tre update 🚀"
    
    success, result = schedule_post(
        content=content,
        minutes_ahead=5  # Schedule 10 minutes from now
    )
    
    # ============================================================
    # OPTION 2: Schedule with image (uncomment to use)
    # ============================================================
    # success, result = schedule_post(
    #     content="🌟 Beautiful sunset! 🌅",
    #     minutes_ahead=15,
    #     image_url="https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=800"
    # )
    
    # ============================================================
    # OPTION 3: Schedule for a specific time (uncomment to use)
    # ============================================================
    # def schedule_at_specific_time(content, hour, minute):
    #     local_tz = pytz.timezone(TIMEZONE)
    #     now = datetime.now(local_tz)
    #     scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    #     if scheduled < now:
    #         scheduled += timedelta(days=1)  # Schedule for tomorrow if time passed
    #     minutes_ahead = int((scheduled - now).total_seconds() / 60)
    #     return schedule_post(content, minutes_ahead)
    # 
    # success, result = schedule_at_specific_time(
    #     content="Good morning! ☀️ Today is going to be great!",
    #     hour=9,
    #     minute=0
    # )
    
    if success:
        print("\n✅ Post scheduled successfully! ✅")
        print(f"📌 Post ID: {result['post_id']}")
        print(f"📌 Scheduled for: {result['scheduled_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📌 Check your Facebook page at that time!")
    else:
        print("\n❌ Failed to schedule post. Check the error above.")