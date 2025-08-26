# transcription_service/core/adjuster.py
import asyncpg
import logging
from datetime import datetime
from typing import Dict, Any
from ..api.models import TranscriptionAdjustRequest, AdjustmentResult
from ..data.cache_manager import VocabularyCacheManager
from .phases.pre_adjustment import PreAdjustmentPhase
from .phases.normalization import NormalizationPhase  
from .phases.extraction import ExtractionPhase
from .phases.completion import CompletionPhase
from ..utils.validators import validate_input
from ..utils.performance import PerformanceTracker

logger = logging.getLogger(__name__)

class TranscriptionAdjuster:
    """Main orchestrator for the transcription adjustment process"""
    
    def __init__(self):
        # Initialize cache manager
        self.cache_manager = VocabularyCacheManager()
        
        # Initialize phases
        self.pre_adjustment = PreAdjustmentPhase()
        self.normalization = NormalizationPhase()
        self.extraction = ExtractionPhase()
        self.completion = CompletionPhase()
        
        # Performance tracking
        self.performance = PerformanceTracker()
    
    async def adjust_transcription(self, request: TranscriptionAdjustRequest, pool: asyncpg.Pool) -> AdjustmentResult:
        """Main adjustment function orchestrating all phases"""
        
        # Start performance tracking
        tracker = self.performance.start_tracking()
        
        try:
            # Step 1: Input validation
            validate_input(request.original_transcript)
            tracker.add_checkpoint("validation")
            
            # Step 2: Load cache if needed
            await self.cache_manager.ensure_cache_loaded(pool)
            tracker.add_checkpoint("cache_load")
            
            original = request.original_transcript
            logger.info(f"Starting adjustment for: '{original}'")
            
            # Phase 0: Pre-adjustment (number detection)
            try:
                pre_adjusted, un_une_replaced = await self.pre_adjustment.process(
                    original, self.cache_manager
                )
                tracker.add_checkpoint("pre_adjustment")
            except Exception as e:
                logger.error(f"Pre-adjustment failed: {e}")
                pre_adjusted = original
                un_une_replaced = False
            
            # Phase 1: Normalization  
            try:
                normalized = await self.normalization.process(
                    pre_adjusted, un_une_replaced, self.cache_manager
                )
                tracker.add_checkpoint("normalization")
            except Exception as e:
                logger.error(f"Normalization failed: {e}")
                normalized = pre_adjusted.lower()
            
            # Phase 2: Vocabulary extraction
            try:
                extraction_result = await self.extraction.process(
                    normalized, self.cache_manager
                )
                final_transcript = extraction_result.final_transcript
                vocab_matches = extraction_result.vocabulary_matches
                matched_entries = extraction_result.matched_entries
                tracker.add_checkpoint("extraction")
            except Exception as e:
                logger.error(f"Extraction failed: {e}")
                final_transcript = normalized
                vocab_matches = []
                matched_entries = []
            
            # Phase 3: Entity completion
            try:
                completion_result = await self.completion.process(
                    final_transcript, matched_entries, self.cache_manager
                )
                completed_transcript = completion_result.completed_transcript
                entity_matches = completion_result.entity_matches
                tracker.add_checkpoint("completion")
            except Exception as e:
                logger.error(f"Completion failed: {e}")
                completed_transcript = final_transcript
                entity_matches = []
            
            # Calculate total processing time
            processing_time = tracker.get_total_time_ms()
            
            # Validation: Ensure we don't return worse results than input
            if not final_transcript:
                final_transcript = original.lower()
            if not completed_transcript:
                completed_transcript = final_transcript
            
            logger.info(f"Adjustment completed in {processing_time:.2f}ms")
            logger.info(f"Result: '{original}' → '{completed_transcript}'")
            
            return AdjustmentResult(
                original_transcript=original,
                pre_adjusted_transcript=pre_adjusted,
                adjusted_transcript=final_transcript,
                completed_transcript=completed_transcript,
                list_of_vocabulary=vocab_matches,
                list_of_entities=entity_matches,
                processing_time_ms=processing_time
            )
            
        except Exception as e:
            logger.error(f"Complete transcription adjustment failed: {e}")
            
            # Return minimal valid result for reliability
            processing_time = tracker.get_total_time_ms()
            return AdjustmentResult(
                original_transcript=request.original_transcript,
                pre_adjusted_transcript=request.original_transcript,
                adjusted_transcript=request.original_transcript.lower(),
                completed_transcript=request.original_transcript.lower(),
                list_of_vocabulary=[],
                list_of_entities=[],
                processing_time_ms=processing_time
            )
    
    def get_cache_status(self) -> Dict[str, Any]:
        """Get current cache status for monitoring"""
        return self.cache_manager.get_status()
    
    async def warm_cache(self, pool: asyncpg.Pool):
        """Warm up cache for better performance"""
        await self.cache_manager.ensure_cache_loaded(pool)
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        return self.performance.get_stats()

# transcription_service/data/cache_manager.py
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
    
    def invalidate_cache(self):
        """Force cache invalidation"""
        self.cache_loaded = False
        self.cache_timestamp = None
        self.cache.clear()
