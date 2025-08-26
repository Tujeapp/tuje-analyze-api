# transcription_service/core/adjuster.py
import asyncpg
import logging
from datetime import datetime
from typing import Dict, Any
from adjustement_models import TranscriptionAdjustRequest, AdjustmentResult
from adjustement_cache_manager import VocabularyCacheManager
from adjustement_validators import validate_input
from adjustement_performance_tracker import PerformanceTracker
from .phases.normalization import NormalizationPhase  
from .phases.extraction import ExtractionPhase
from .phases.completion import CompletionPhase
from ..utils.validators import validate_input
from ..utils.performance import PerformanceTracker

logger = logging.getLogger(__name__)

class TranscriptionAdjuster:
    """Main orchestrator for the transcription adjustment process"""
    
    def __init__(self):
        # Import components
        from adjustement_cache_manager import VocabularyCacheManager
        from adjustement_french_nbr_detector import FrenchNumberDetector
        from adjustement_digit_nbr_detector import DigitNumberDetector
        from adjustement_decimal_nbr_detector import DecimalNumberDetector
        from adjustement_text_cleaner import TextCleaner
        from adjustement_entity_consolidator import EntityConsolidator
        from adjustement_vocabulary_finder import VocabularyFinder
        from adjustement_transcript_assembler import TranscriptAssembler
        from adjustement_entity_mapper import EntityMapper
        from adjustement_un_une_analyzer import UnUneAnalyzer
        
        # Initialize cache manager
        self.cache_manager = VocabularyCacheManager()
        
        # Initialize processors
        self.french_number_detector = FrenchNumberDetector()
        self.digit_detector = DigitNumberDetector()
        self.decimal_detector = DecimalNumberDetector()
        self.text_cleaner = TextCleaner()
        self.consolidator = EntityConsolidator()
        self.vocab_finder = VocabularyFinder()
        self.transcript_assembler = TranscriptAssembler()
        self.entity_mapper = EntityMapper()
        
        # Performance tracking
        from adjustement_performance_tracker import PerformanceTracker
        self.performance = PerformanceTracker()
    
    async def adjust_transcription(self, request, pool):
        """Main adjustment function orchestrating all phases"""
        start_time = datetime.now()
        
        try:
            # Input validation
            from adjustement_validators import validate_input
            validate_input(request.original_transcript)
            
            # Load cache
            await self.cache_manager.ensure_cache_loaded(pool)
            
            original = request.original_transcript
            logger.info(f"Starting adjustment for: '{original}'")
            
            # Phase 0: Number replacement (with error handling)
            try:
                # Replace French numbers
                pre_adjusted, un_une_replaced, _ = self.french_number_detector.replace_french_numbers(original)
                
                # Replace digits  
                pre_adjusted, _ = self.digit_detector.replace_digits(pre_adjusted)
                
                # Replace decimals
                pre_adjusted, _ = self.decimal_detector.replace_decimals(pre_adjusted)
                
                # Handle un/une subprocess
                if un_une_replaced:
                    un_une_analyzer = UnUneAnalyzer(self.cache_manager)
                    pre_adjusted = un_une_analyzer.analyze_and_fix(pre_adjusted)
                    
            except Exception as e:
                logger.error(f"Pre-adjustment failed: {e}")
                pre_adjusted = original
            
            # Phase 1: Normalization
            try:
                # Basic cleaning
                normalized = self.text_cleaner.clean_basic(pre_adjusted)
                normalized = self.text_cleaner.expand_contractions(normalized)
                normalized = self.text_cleaner.remove_punctuation(normalized)
                
                # Consolidate entityNumbers
                normalized = self.consolidator.consolidate(normalized)
                
                # Clean whitespace
                normalized = self.text_cleaner.normalize_whitespace(normalized)
                
            except Exception as e:
                logger.error(f"Normalization failed: {e}")
                normalized = pre_adjusted.lower()
            
            # Phase 2: Vocabulary matching
            try:
                # Find vocabulary matches
                vocab_matches = self.vocab_finder.find_matches(normalized, self.cache_manager)
                
                # Build transcript
                final_transcript = self.transcript_assembler.assemble_transcript(normalized, vocab_matches)
                
                # Extract data for phase 3
                vocabulary_matches = [match.vocab_match for match in vocab_matches]
                matched_entries = [match.vocab_entry for match in vocab_matches]
                
            except Exception as e:
                logger.error(f"Vocabulary matching failed: {e}")
                final_transcript = normalized
                vocabulary_matches = []
                matched_entries = []
            
            # Phase 3: Entity completion (THE KEY FIX!)
            try:
                completed_transcript, entity_matches = self.entity_mapper.map_entities(
                    final_transcript, vocab_matches, self.cache_manager
                )
            except Exception as e:
                logger.error(f"Entity completion failed: {e}")
                completed_transcript = final_transcript
                entity_matches = []
            
            # Calculate processing time
            processing_time = round((datetime.now() - start_time).total_seconds() * 1000, 2)
            
            # Ensure we don't return worse results than input
            if not final_transcript:
                final_transcript = original.lower()
            if not completed_transcript:
                completed_transcript = final_transcript
            
            logger.info(f"Adjustment completed in {processing_time}ms")
            logger.info(f"Result: '{original}' → '{completed_transcript}'")
            
            # Import here to avoid circular import
            from adjustement_models import AdjustmentResult
            
            return AdjustmentResult(
                original_transcript=original,
                pre_adjusted_transcript=pre_adjusted,
                adjusted_transcript=final_transcript,
                completed_transcript=completed_transcript,
                list_of_vocabulary=vocabulary_matches,
                list_of_entities=entity_matches,
                processing_time_ms=processing_time
            )
            
        except Exception as e:
            logger.error(f"Complete transcription adjustment failed: {e}")
            
            # Return minimal valid result
            processing_time = round((datetime.now() - start_time).total_seconds() * 1000, 2)
            from adjustement_models import AdjustmentResult
            
            return AdjustmentResult(
                original_transcript=request.original_transcript,
                pre_adjusted_transcript=request.original_transcript,
                adjusted_transcript=request.original_transcript.lower(),
                completed_transcript=request.original_transcript.lower(),
                list_of_vocabulary=[],
                list_of_entities=[],
                processing_time_ms=processing_time
            )
    
    def get_cache_status(self):
        """Get cache status for monitoring"""
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
