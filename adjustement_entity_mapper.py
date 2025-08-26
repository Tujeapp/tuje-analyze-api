# transcription_service/processors/entity_mapper.py
"""
SINGLE RESPONSIBILITY: Map vocabulary to entities and replace in transcript
"""
import re
import logging
from typing import List, Tuple
from adjustement_models import EntityMatch
from adjustement_cache_manager import VocabularyCacheManager
from adjustement_vocabulary_finder import VocabularyMatchResult

logger = logging.getLogger(__name__)

class EntityMapper:
    """Maps vocabulary entries to their entities and replaces them in transcript"""
    
    def map_entities(self, transcript: str, matches: List[VocabularyMatchResult], 
                    cache_manager: VocabularyCacheManager) -> Tuple[str, List[EntityMatch]]:
        """Map vocabulary to entities and create completed transcript"""
        logger.info(f"Mapping entities for {len(matches)} vocabulary matches")
        
        completed_transcript = transcript
        entity_matches = []
        
        # Process each vocabulary match for entity mapping
        for match in matches:
            entity_match = self._create_entity_match(match, cache_manager)
            
            if entity_match:
                # Replace vocabulary with entity in transcript
                completed_transcript = self._replace_vocabulary_with_entity(
                    completed_transcript,
                    match.vocab_entry['transcription_adjusted'],
                    entity_match.name.lower()
                )
                entity_matches.append(entity_match)
        
        logger.info(f"Entity mapping complete: {len(entity_matches)} entities found")
        logger.info(f"Final transcript: '{transcript}' → '{completed_transcript}'")
        
        return completed_transcript, entity_matches
    
    def _create_entity_match(self, match: VocabularyMatchResult, 
                            cache_manager: VocabularyCacheManager) -> EntityMatch:
        """Create an entity match from a vocabulary match"""
        vocab_entry = match.vocab_entry
        
        if not vocab_entry.get('entity_type_id'):
            logger.debug(f"No entity for vocab '{vocab_entry['transcription_adjusted']}'")
            return None
        
        entity_type_id = vocab_entry['entity_type_id']
        entity_name = cache_manager.get_entity_name(entity_type_id)
        
        if not entity_name:
            entity_name = entity_type_id  # Fallback
            logger.warning(f"Entity name not found for {entity_type_id}, using fallback")
        
        logger.debug(f"Created entity match: {entity_type_id} → {entity_name}")
        
        return EntityMatch(
            id=entity_type_id,
            name=entity_name,
            value=vocab_entry['transcription_adjusted']
        )
    
    def _replace_vocabulary_with_entity(self, transcript: str, vocab_text: str, entity_name: str) -> str:
        """Replace vocabulary text with entity name in transcript"""
        # Use word boundaries to avoid partial replacements
        pattern = r'\b' + re.escape(vocab_text) + r'\b'
        
        if re.search(pattern, transcript, re.IGNORECASE):
            result = re.sub(pattern, entity_name, transcript, count=1, flags=re.IGNORECASE)
            logger.debug(f"✅ Replaced '{vocab_text}' with '{entity_name}'")
            return result
        else:
            logger.warning(f"❌ Could not find '{vocab_text}' in '{transcript}' for replacement")
            return transcript
