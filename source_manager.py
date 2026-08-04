# ============================================================
# SOURCE MANAGER - Manage Facebook Source Accounts
# ============================================================

import json
import os
from datetime import datetime

class SourceManager:
    """
    SourceManager handles all operations related to Facebook source accounts.
    It can read from config.py, cache sources, and provide summaries.
    """
    
    def __init__(self):
        self.config_file = 'config.py'
        self.sources_cache_file = 'sources_cache.json'
        self._sources = None
    
    def get_sources(self):
        """
        Get all configured sources from config.py.
        Caches the result for performance.
        
        Returns:
            list: List of source account dictionaries
        """
        try:
            # Return cached sources if available
            if self._sources:
                return self._sources
            
            # Import from config
            from config import SOURCE_ACCOUNTS
            self._sources = SOURCE_ACCOUNTS
            return SOURCE_ACCOUNTS
            
        except ImportError:
            print("❌ Could not import SOURCE_ACCOUNTS from config.py")
            return []
        except Exception as e:
            print(f"❌ Error getting sources: {e}")
            return []
    
    def get_source_count(self):
        """
        Get the number of configured sources.
        
        Returns:
            int: Number of sources
        """
        return len(self.get_sources())
    
    def get_sources_by_category(self):
        """
        Get sources grouped by category.
        
        Returns:
            dict: Dictionary with category names as keys and lists of sources as values
        """
        sources = self.get_sources()
        categories = {}
        
        for source in sources:
            category = source.get('category', 'Uncategorized')
            if category not in categories:
                categories[category] = []
            categories[category].append(source)
        
        return categories
    
    def get_sources_summary(self):
        """
        Get a summary of all sources.
        
        Returns:
            dict: Summary containing total, categories, names, and priority order
        """
        sources = self.get_sources()
        
        if not sources:
            return {
                'total': 0,
                'categories': {},
                'source_names': [],
                'priority_order': []
            }
        
        categories = {}
        names = []
        priorities = []
        
        for source in sources:
            category = source.get('category', 'Uncategorized')
            categories[category] = categories.get(category, 0) + 1
            names.append(source.get('name', 'Unknown'))
            priorities.append({
                'priority': source.get('priority', 999),
                'name': source.get('name', 'Unknown'),
                'id': source.get('id', '')
            })
        
        # Sort by priority
        priorities.sort(key=lambda x: x['priority'])
        
        return {
            'total': len(sources),
            'categories': categories,
            'source_names': names,
            'priority_order': priorities
        }
    
    def format_sources_for_display(self):
        """
        Format sources for console/UI display.
        
        Returns:
            str: Formatted string with source details
        """
        sources = self.get_sources()
        
        if not sources:
            return "No sources configured"
        
        result = []
        result.append("📡 Configured Sources")
        result.append("-" * 40)
        
        # Sort by priority
        sorted_sources = sorted(sources, key=lambda x: x.get('priority', 999))
        
        for source in sorted_sources:
            name = source.get('name', 'Unknown')
            priority = source.get('priority', 'N/A')
            category = source.get('category', 'Uncategorized')
            source_id = source.get('id', '')
            result.append(f"  #{priority} {name} ({category})")
            if source_id:
                result.append(f"    ID: {source_id}")
        
        result.append("-" * 40)
        result.append(f"Total: {len(sources)} sources")
        
        return "\n".join(result)
    
    def get_source_stats(self):
        """
        Get statistics about sources.
        
        Returns:
            dict: Statistics including total, categories, priority range
        """
        sources = self.get_sources()
        
        if not sources:
            return {
                'total': 0,
                'categories': {},
                'priority_range': {'min': 0, 'max': 0},
                'names': []
            }
        
        priorities = [s.get('priority', 999) for s in sources]
        categories = {}
        
        for s in sources:
            cat = s.get('category', 'Uncategorized')
            categories[cat] = categories.get(cat, 0) + 1
        
        return {
            'total': len(sources),
            'categories': categories,
            'priority_range': {
                'min': min(priorities) if priorities else 0,
                'max': max(priorities) if priorities else 0
            },
            'names': [s.get('name', 'Unknown') for s in sources]
        }
    
    def find_source_by_name(self, name):
        """
        Find a source by its name.
        
        Args:
            name (str): Source name to search for
            
        Returns:
            dict: Source dictionary or None if not found
        """
        sources = self.get_sources()
        for source in sources:
            if source.get('name', '').lower() == name.lower():
                return source
        return None
    
    def find_source_by_id(self, source_id):
        """
        Find a source by its ID.
        
        Args:
            source_id (str): Source ID to search for
            
        Returns:
            dict: Source dictionary or None if not found
        """
        sources = self.get_sources()
        for source in sources:
            if source.get('id') == source_id:
                return source
        return None
    
    def get_source_urls(self):
        """
        Get all source URLs.
        
        Returns:
            list: List of URLs
        """
        sources = self.get_sources()
        return [s.get('url', '') for s in sources if s.get('url')]
    
    def get_source_names(self):
        """
        Get all source names.
        
        Returns:
            list: List of names
        """
        sources = self.get_sources()
        return [s.get('name', 'Unknown') for s in sources]
    
    def save_to_cache(self):
        """
        Save sources to cache file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        sources = self.get_sources()
        
        try:
            with open(self.sources_cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'sources': sources,
                    'cached_at': datetime.now().isoformat(),
                    'count': len(sources)
                }, f, indent=2, ensure_ascii=False)
            print(f"💾 Cached {len(sources)} sources to {self.sources_cache_file}")
            return True
        except Exception as e:
            print(f"❌ Error saving cache: {e}")
            return False
    
    def load_from_cache(self):
        """
        Load sources from cache file.
        
        Returns:
            list: List of sources or None if cache doesn't exist
        """
        try:
            if os.path.exists(self.sources_cache_file):
                with open(self.sources_cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"📂 Loaded {data.get('count', 0)} sources from cache")
                    return data.get('sources', [])
        except Exception as e:
            print(f"❌ Error loading cache: {e}")
        
        return None
    
    def clear_cache(self):
        """
        Clear the cache file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if os.path.exists(self.sources_cache_file):
                os.remove(self.sources_cache_file)
                print("🗑️ Cache cleared")
            return True
        except Exception as e:
            print(f"❌ Error clearing cache: {e}")
            return False
    
    def add_source_instruction(self, name, url, category="General", priority=None):
        """
        Generate instructions for adding a new source to config.py.
        
        Args:
            name (str): Source name
            url (str): Facebook URL
            category (str): Category (default: General)
            priority (int): Priority (auto-assigned if None)
        """
        if priority is None:
            priority = len(self.get_sources()) + 1
        
        print(f"\n📝 To add '{name}' to config.py, add this to SOURCE_ACCOUNTS:")
        print("=" * 60)
        print(f"""
    {{
        "id": "{name.lower().replace(' ', '_')}",
        "name": "{name}",
        "url": "{url}",
        "category": "{category}",
        "priority": {priority}
    }},""")
        print("=" * 60)


# ============================================================
# STANDALONE FUNCTIONS FOR EASY IMPORT
# ============================================================

def get_configured_sources():
    """Quick function to get sources"""
    manager = SourceManager()
    return manager.get_sources()

def get_source_count():
    """Quick function to get source count"""
    manager = SourceManager()
    return manager.get_source_count()

def get_sources_summary():
    """Quick function to get sources summary"""
    manager = SourceManager()
    return manager.get_sources_summary()

def print_sources():
    """Print sources to console"""
    manager = SourceManager()
    print(manager.format_sources_for_display())

def get_source_stats():
    """Quick function to get source stats"""
    manager = SourceManager()
    return manager.get_source_stats()


# ============================================================
# MAIN - Run as script for testing
# ============================================================

if __name__ == '__main__':
    print("=" * 60)
    print("📡 SOURCE MANAGER")
    print("=" * 60)
    
    manager = SourceManager()
    sources = manager.get_sources()
    
    if sources:
        print(f"\n✅ Found {len(sources)} configured sources:")
        print(manager.format_sources_for_display())
        
        # Show stats
        stats = manager.get_source_stats()
        print(f"\n📊 Statistics:")
        print(f"  Total: {stats['total']}")
        print(f"  Priority Range: {stats['priority_range']['min']} - {stats['priority_range']['max']}")
        print(f"  Categories: {', '.join(f'{k}: {v}' for k, v in stats['categories'].items())}")
        
        # Show summary
        summary = manager.get_sources_summary()
        print(f"\n📋 Summary:")
        print(f"  Source Names: {', '.join(summary['source_names'])}")
        
        # Save to cache
        manager.save_to_cache()
        print(f"\n💾 Cached sources to {manager.sources_cache_file}")
    else:
        print("❌ No sources found in config.py")
        print("\n💡 Make sure SOURCE_ACCOUNTS is defined in config.py")