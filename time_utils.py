# ============================================================
# TIME UTILITIES
# ============================================================

from datetime import datetime, timedelta
import pytz

def convert_to_kenya_time(dt):
    """
    Convert datetime to Kenya timezone (UTC+3)
    """
    if dt.tzinfo is None:
        # Assume UTC if no timezone
        dt = dt.replace(tzinfo=pytz.UTC)
    
    kenya_tz = pytz.timezone('Africa/Nairobi')
    return dt.astimezone(kenya_tz)

def format_kenya_datetime():
    """
    Get current Kenya time as formatted string
    """
    now = datetime.utcnow()
    kenya_tz = pytz.timezone('Africa/Nairobi')
    kenya_now = now.replace(tzinfo=pytz.UTC).astimezone(kenya_tz)
    return kenya_now.strftime("%d/%m/%Y, %I:%M %p")

def format_kenya_time():
    """
    Get current Kenya time as formatted string (time only)
    """
    now = datetime.utcnow()
    kenya_tz = pytz.timezone('Africa/Nairobi')
    kenya_now = now.replace(tzinfo=pytz.UTC).astimezone(kenya_tz)
    return kenya_now.strftime("%I:%M %p")