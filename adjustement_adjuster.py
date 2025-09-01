# adjustement_adjuster.py - FIXED INDENTATION AND IMPORTS
import asyncpg
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

# All absolute imports - no dots!
from adjustement_cache_manager import VocabularyCacheManager
from adjustement_validators import validate_input
from adjustement_performance_tracker import PerformanceTracker
from adjustement_french_nbr_detector import FrenchNumberDetector
from adjustement_digit_nbr_detector import DigitNumberDetector
from adjustement_decimal_nbr_detector import DecimalNumberDetector
from adjustement_text_cleaner import TextCleaner
from adjustement_entity_consolidator import EntityConsolidator
from adjustement_vocabulary_finder import VocabularyFinder
from adjustement_transcript_assembler import TranscriptAssembler
from adjustement_entity_mapper import EntityMapper
from adjustement_un_une_analyzer import UnUneAnalyzer

logger = logging.getLogger(__name__)

class TranscriptionAdjuster:
    """Main orchestrator for the transcription adjustment process"""
    
    def __init__(self):
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
        self.performance = PerformanceTracker()
    
    async def adjust_transcription(self, request, pool: asyncpg.Pool):
        """Main adjustment function orchestrating all phases"""
        # Import here to avoid circular import
        from adjustement_types import AdjustmentResult, VocabularyMatch
        
        start_time = datetime.now()
        
        try:
            # Step 1: Input validation
            validate_input(request.original_transcript)
            
            # Step 2: Load cache if needed
            await self.cache_manager.ensure_cache_loaded(pool)
            
            original = request.original_transcript
            logger.info(f"Starting adjustment for: '{original}'")
            
            # Phase 0: Pre-adjustment (number detection)
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
            
            # Phase 2: Vocabulary extraction (ENHANCED WITH NOTION DEBUG INFO)
            try:
                # Find vocabulary matches with entity context
                vocab_matches = self.vocab_finder.find_matches(
                    normalized, 
                    self.cache_manager, 
                    expected_entities_ids=request.expected_entities_ids  # Pass context
                )
                
                # Build transcript
                final_transcript = self.transcript_assembler.assemble_transcript(normalized, vocab_matches)
                
                # Extract data for next phase (RESTORE ORIGINAL LOGIC + ADD NOTION DEBUG)
                vocabulary_matches = []
                for match in vocab_matches:
                    # Get notion info for this vocabulary entry for debugging
                    vocab_entry = match.vocab_entry
                    expected_notion_ids = vocab_entry.get('expected_notion_id', [])
                    
                    # Handle different formats of expected_notion_id
                    notion_ids = []
                    if expected_notion_ids:
                        if isinstance(expected_notion_ids, list):
                            notion_ids = [str(nid).strip() for nid in expected_notion_ids if nid and str(nid).strip()]
                        elif isinstance(expected_notion_ids, str):
                            notion_ids = [nid.strip() for nid in expected_notion_ids.split(',') if nid.strip()]
                    
                    # Create enhanced VocabularyMatch with notion debug info
                    vocabulary_matches.append(VocabularyMatch(
                        id=match.vocab_match.id,
                        transcription_fr=match.vocab_match.transcription_fr,
                        transcription_adjusted=match.vocab_match.transcription_adjusted,
                        expected_notion_ids=notion_ids  # NEW: Debug info
                    ))
                
                # IMPORTANT: Keep the original vocab_matches for entity mapping
                matched_entries = [match.vocab_entry for match in vocab_matches]
                
            except Exception as e:
                logger.error(f"Extraction failed: {e}")
                final_transcript = normalized
                vocabulary_matches = []
                matched_entries = []
                vocab_matches = []  # Make sure this is also empty
            
            # Phase 3: Entity completion
            try:
                completed_transcript, entity_matches = self.entity_mapper.map_entities(
                    final_transcript, vocab_matches, self.cache_manager
                )
            except Exception as e:
                logger.error(f"Completion failed: {e}")
                completed_transcript = final_transcript
                entity_matches = []
            
            # NEW: Phase 4: Notion Matching (SAFE INTEGRATION)
            notion_matched_ids = []
            debug_interaction_id = None
            debug_interaction_expected_notions = []
            debug_notion_matching_attempted = False
            
            try:
                if hasattr(request, 'interaction_id') and request.interaction_id:
                    debug_interaction_id = request.interaction_id
                    debug_notion_matching_attempted = True
                    
                    logger.info(f"🎯 Starting Phase 4: Notion matching for interaction {request.interaction_id}")
                    
                    # Import here to avoid any import issues
                    from adjustement_notion_matcher import NotionMatcher
                    
                    notion_matcher = NotionMatcher()
                    
                    # First get interaction expected notions for debugging
                    try:
                        result = await self.cache_manager.execute_query_for_notion_matcher("""
                            SELECT expected_notion_id
                            FROM brain_interaction
                            WHERE id = $1 AND live = TRUE
                        """, request.interaction_id)
                        
                        if result and result['expected_notion_id']:
                            notion_ids = result['expected_notion_id']
                            if isinstance(notion_ids, list):
                                debug_interaction_expected_notions = [str(nid).strip() for nid in notion_ids if nid and str(nid).strip()]
                            elif isinstance(notion_ids, str):
                                debug_interaction_expected_notions = [nid.strip() for nid in notion_ids.split(',') if nid.strip()]
                        
                        logger.info(f"🎯 Debug: Interaction {request.interaction_id} expects notions: {debug_interaction_expected_notions}")
                        
                    except Exception as e:
                        logger.error(f"Failed to get interaction notions for debug: {e}")
                    
                    # Now do the actual notion matching
                    notion_matched_ids = await notion_matcher.find_notion_matches(
                        interaction_id=request.interaction_id,
                        vocabulary_matches=[match.vocab_match for match in vocab_matches],  # Use original vocab_matches
                        cache_manager=self.cache_manager
                    )
                    logger.info(f"✅ Phase 4 complete: Found {len(notion_matched_ids)} notion matches: {notion_matched_ids}")
                else:
                    logger.debug("⚠️ No interaction_id provided, skipping Phase 4 (notion matching)")
            except Exception as e:
                logger.error(f"❌ Phase 4 (notion matching) failed - continuing with empty list: {e}")
                notion_matched_ids = []  # Safe fallback - doesn't break the adjustment
            
            # Calculate total processing time (KEEP THE SAME)
            processing_time = round((datetime.now() - start_time).total_seconds() * 1000, 2)
            
            # Validation: Ensure we don't return worse results than input (KEEP THE SAME)
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
                list_of_vocabulary=vocabulary_matches,
                list_of_entities=entity_matches,
                list_of_notion_matches=notion_matched_ids,
                processing_time_ms=processing_time,
                # NEW: Debug information
                debug_interaction_id=debug_interaction_id,
                debug_interaction_expected_notions=debug_interaction_expected_notions,
                debug_notion_matching_attempted=debug_notion_matching_attempted
            )
            
        except Exception as e:
            logger.error(f"Complete transcription adjustment failed: {e}")
            
            # Return minimal valid result for reliability
            processing_time = round((datetime.now() - start_time).total_seconds() * 1000, 2)
            return AdjustmentResult(
                original_transcript=request.original_transcript,
                pre_adjusted_transcript=request.original_transcript,
                adjusted_transcript=request.original_transcript.lower(),
                completed_transcript=request.original_transcript.lower(),
                list_of_vocabulary=[],
                list_of_entities=[],
                list_of_notion_matches=[],
                processing_time_ms=processing_time,
                # NEW: Debug information (empty in error case)
                debug_interaction_id=getattr(request, 'interaction_id', None),
                debug_interaction_expected_notions=[],
                debug_notion_matching_attempted=False
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
