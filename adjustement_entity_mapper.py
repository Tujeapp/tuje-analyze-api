# adjustement_entity_mapper.py
"""
SINGLE RESPONSIBILITY: Map vocabulary to entities and replace in transcript
UPDATED: Only use entities with live=TRUE
"""
import re
import logging
from typing import List, Tuple
from adjustement_types import EntityMatch
from adjustement_cache_manager import VocabularyCacheManager
from adjustement_vocabulary_finder import VocabularyMatchResult

logger = logging.getLogger(__name__)

class EntityMapper:
    """Maps vocabulary entries to their entities and replaces them in transcript"""
    
    def map_entities(self, transcript: str, matches: List[VocabularyMatchResult], 
                    cache_manager: VocabularyCacheManager) -> Tuple[str, List[EntityMatch]]:
        """Map vocabulary to entities and create completed transcript (live entities only)"""
        logger.info(f"Mapping entities for {len(matches)} vocabulary matches")
        
        completed_transcript = transcript
        entity_matches = []
        skipped_inactive_entities = []
        
        # Process each vocabulary match for entity mapping
        for match in matches:
            entity_match, skipped_reason = self._create_entity_match(match, cache_manager)
            
            if entity_match:
                # Replace vocabulary with entity in transcript
                completed_transcript = self._replace_vocabulary_with_entity(
                    completed_transcript,
                    match.vocab_entry['transcription_adjusted'],
                    entity_match.name.lower()
                )
                entity_matches.append(entity_match)
            elif skipped_reason:
                skipped_inactive_entities.append({
                    'vocab_id': match.vocab_entry['id'],
                    'vocab_text': match.vocab_entry['transcription_adjusted'],
                    'reason': skipped_reason
                })
        
        # UPDATED: Enhanced logging for live entity filtering
        logger.info(f"Entity mapping complete: {len(entity_matches)} live entities found, "
                   f"{len(skipped_inactive_entities)} inactive entities skipped")
        
        if skipped_inactive_entities:
            logger.info("Skipped inactive entities:")
            for skipped in skipped_inactive_entities:
                logger.info(f"  - '{skipped['vocab_text']}' (vocab_id: {skipped['vocab_id']}) - {skipped['reason']}")
        
        logger.info(f"Final transcript: '{transcript}' → '{completed_transcript}'")
        
        return completed_transcript, entity_matches
    
    def _create_entity_match(self, match: VocabularyMatchResult, 
                            cache_manager: VocabularyCacheManager) -> Tuple[EntityMatch, str]:
        """
        Create an entity match from a vocabulary match (live entities only)
        Returns: (EntityMatch or None, skip_reason or None)
        """
        vocab_entry = match.vocab_entry
        
        if not vocab_entry.get('entity_type_id'):
            logger.debug(f"No entity type for vocab '{vocab_entry['transcription_adjusted']}'")
            return None, None
        
        entity_type_id = vocab_entry['entity_type_id']
        
        # UPDATED: Check if entity is live before proceeding
        if not cache_manager.is_entity_live(entity_type_id):
            inactive_name = cache_manager.get_inactive_entity_name(entity_type_id)
            skip_reason = f"Entity {entity_type_id} ({inactive_name or 'unknown'}) is not live"
            logger.debug(f"Skipping inactive entity: {skip_reason}")
            return None, skip_reason
        
        # Get live entity name
        entity_name = cache_manager.get_entity_name(entity_type_id)
        
        if not entity_name:
            skip_reason = f"Entity name not found for live entity {entity_type_id}"
            logger.warning(skip_reason)
            return None, skip_reason
        
        logger.debug(f"Created entity match: {entity_type_id} → {entity_name} (live)")
        
        return EntityMatch(
            id=entity_type_id,
            name=entity_name,
            value=vocab_entry['transcription_adjusted']
        ), None
    
    def _replace_vocabulary_with_entity(self, transcript: str, vocab_text: str, entity_name: str) -> str:
        """Replace vocabulary text with entity name in transcript"""
        # Use word boundaries to avoid partial replacements
        pattern = r'\b' + re.escape(vocab_text) + r'\b'
        
        if re.search(pattern, transcript, re.IGNORECASE):
            result = re.sub(pattern, entity_name, transcript, count=1, flags=re.IGNORECASE)
            logger.debug(f"✅ Replaced '{vocab_text}' with '{entity_name}' (live entity)")
            return result
        else:
            logger.warning(f"❌ Could not find '{vocab_text}' in '{transcript}' for replacement")
            return transcript
