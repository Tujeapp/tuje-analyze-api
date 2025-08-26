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
                # Single optimized query with JOIN
                query = """
                    SELECT 
                        v.id, 
                        v.transcription_fr, 
                        v.transcription_en, 
                        v.transcription_adjusted, 
                        v.entity_type_id,
                        e.name as entity_name
                    FROM brain_vocab v
                    LEFT JOIN brain_entity e ON v.entity_type_id = e.id
                    WHERE v.live = TRUE
                    ORDER BY LENGTH(v.transcription_adjusted) DESC
                """
                
                rows = await conn.fetch(query)
                
                # Process results
                self.cache = {
                    'all_vocab': [],
                    'entitynumber_patterns': [],
                    'entities': {}
                }
                
                for row in rows:
                    vocab_entry = {
                        'id': row['id'],
                        'transcription_fr': row['transcription_fr'] or '',
                        'transcription_en': row['transcription_en'] or '',
                        'transcription_adjusted': row['transcription_adjusted'] or '',
                        'entity_type_id': row['entity_type_id']
                    }
                    
                    self.cache['all_vocab'].append(vocab_entry)
                    
                    # Cache entity names
                    if row['entity_type_id'] and row['entity_name']:
                        self.cache['entities'][row['entity_type_id']] = row['entity_name']
                    
                    # EntityNumber patterns for subprocess
                    if 'entitynumber' in str(row['transcription_fr'] or '').lower():
                        self.cache['entitynumber_patterns'].append(vocab_entry)
                
                self.cache_loaded = True
                self.cache_timestamp = time.time()
                
                logger.info(f"Cache refreshed: {len(self.cache['all_vocab'])} vocab entries, "
                          f"{len(self.cache['entities'])} entities, "
                          f"{len(self.cache['entitynumber_patterns'])} number patterns")
                
        except Exception as e:
            logger.error(f"Cache loading failed: {e}")
            if not self.cache_loaded:
                raise  # Only raise if we have no cache at all
    
    def get_all_vocab(self) -> List[Dict[str, Any]]:
        """Get all vocabulary entries"""
        return self.cache.get('all_vocab', [])
    
    def get_entitynumber_patterns(self) -> List[Dict[str, Any]]:
        """Get patterns containing entityNumber"""
        return self.cache.get('entitynumber_patterns', [])
    
    def get_entity_name(self, entity_id: str) -> Optional[str]:
        """Get entity name by ID"""
        return self.cache.get('entities', {}).get(entity_id)
    
    def get_status(self) -> Dict[str, Any]:
        """Get cache status for monitoring"""
        return {
            "loaded": self.cache_loaded,
            "timestamp": self.cache_timestamp,
            "age_seconds": time.time() - self.cache_timestamp if self.cache_timestamp else None,
            "ttl_seconds": self.ttl_seconds,
            "vocab_count": len(self.cache.get('all_vocab', [])),
            "entity_count": len(self.cache.get('entities', {})),
            "pattern_count": len(self.cache.get('entitynumber_patterns', []))
        }
