# adjustement_cache_manager.py
import asyncpg
import logging
import time
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class VocabularyCacheManager:
    """Manages vocabulary and entity caching with TTL"""
    
    def __init__(self, ttl_seconds: int = 300):  # 5 minutes TTL
        self.cache = {}
        self.cache_loaded = False
        self.cache_timestamp = None
        self.ttl_seconds = ttl_seconds
    
    async def ensure_cache_loaded(self, pool: asyncpg.Pool):
        """Ensure cache is loaded and fresh"""
        current_time = time.time()
        
        if (self.cache_loaded and 
            self.cache_timestamp and 
            (current_time - self.cache_timestamp) < self.ttl_seconds):
            return  # Cache is still valid
        
        await self._load_cache(pool)
    
async def _load_cache(self, pool: asyncpg.Pool):
    """Load vocabulary and entities from database"""
    try:
        async with pool.acquire() as conn:
            # CHANGE 1: Add v.expected_notion_id to your existing query
            query = """
                SELECT 
                    v.id, 
                    v.transcription_fr, 
                    v.transcription_en, 
                    v.transcription_adjusted, 
                    v.entity_type_id,
                    v.expected_notion_id,  -- ✅ ADD THIS LINE
                    e.name as entity_name,
                    e.live as entity_live
                FROM brain_vocab v
                LEFT JOIN brain_entity e ON v.entity_type_id = e.id
                WHERE v.live = TRUE
                ORDER BY LENGTH(v.transcription_adjusted) DESC
            """
            
            rows = await conn.fetch(query)
            
            # Your existing cache initialization code stays exactly the same
            self.cache = {
                'all_vocab': [],
                'entitynumber_patterns': [],
                'entities': {},  
                'inactive_entities': {}
            }
            
            for row in rows:
                vocab_entry = {
                    'id': row['id'],
                    'transcription_fr': row['transcription_fr'] or '',
                    'transcription_en': row['transcription_en'] or '',
                    'transcription_adjusted': row['transcription_adjusted'] or '',
                    'entity_type_id': row['entity_type_id'],
                    'expected_notion_id': row['expected_notion_id']  # ✅ ADD THIS LINE
                }
                
                # ALL YOUR EXISTING CODE BELOW STAYS EXACTLY THE SAME
                self.cache['all_vocab'].append(vocab_entry)
                
                if row['entity_type_id'] and row['entity_name']:
                    if row['entity_live']:
                        self.cache['entities'][row['entity_type_id']] = row['entity_name']
                    else:
                        self.cache['inactive_entities'][row['entity_type_id']] = row['entity_name']
                
                if 'entitynumber' in str(row['transcription_fr'] or '').lower():
                    self.cache['entitynumber_patterns'].append(vocab_entry)
            
            # ALL YOUR EXISTING LOGGING CODE STAYS THE SAME
            self.cache_loaded = True
            self.cache_timestamp = time.time()
            
            logger.info(f"Cache refreshed: {len(self.cache['all_vocab'])} vocab entries, "
                      f"{len(self.cache['entities'])} live entities, "
                      f"{len(self.cache['inactive_entities'])} inactive entities, "
                      f"{len(self.cache['entitynumber_patterns'])} number patterns")
            
            if self.cache['inactive_entities']:
                logger.info(f"Inactive entities (will be skipped): {list(self.cache['inactive_entities'].keys())}")
            
    except Exception as e:
        logger.error(f"Cache loading failed: {e}")
        if not self.cache_loaded:
            raise

async def execute_query_for_notion_matcher(self, query: str, *params):
    """Execute database query for notion matching (reuses same connection pattern)"""
    import os
    DATABASE_URL = os.getenv("DATABASE_URL")
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        if query.strip().upper().startswith('SELECT'):
            return await conn.fetchrow(query, *params)  # Single row for interaction queries
        else:
            return await conn.fetch(query, *params)
    finally:
        await conn.close()
    
    def get_all_vocab(self) -> List[Dict[str, Any]]:
        """Get all vocabulary entries"""
        return self.cache.get('all_vocab', [])
    
    def get_entitynumber_patterns(self) -> List[Dict[str, Any]]:
        """Get patterns containing entityNumber"""
        return self.cache.get('entitynumber_patterns', [])
    
    def get_entity_name(self, entity_id: str) -> Optional[str]:
        """Get entity name by ID (only returns live entities)"""
        return self.cache.get('entities', {}).get(entity_id)
    
    def is_entity_live(self, entity_id: str) -> bool:
        """Check if entity is live and available for use"""
        return entity_id in self.cache.get('entities', {})
    
    def get_inactive_entity_name(self, entity_id: str) -> Optional[str]:
        """Get inactive entity name (for debugging purposes only)"""
        return self.cache.get('inactive_entities', {}).get(entity_id)
    
    def get_status(self) -> Dict[str, Any]:
        """Get cache status for monitoring"""
        return {
            "loaded": self.cache_loaded,
            "timestamp": self.cache_timestamp,
            "age_seconds": time.time() - self.cache_timestamp if self.cache_timestamp else None,
            "ttl_seconds": self.ttl_seconds,
            "vocab_count": len(self.cache.get('all_vocab', [])),
            "live_entity_count": len(self.cache.get('entities', {})),
            "inactive_entity_count": len(self.cache.get('inactive_entities', {})),
            "pattern_count": len(self.cache.get('entitynumber_patterns', []))
        }
