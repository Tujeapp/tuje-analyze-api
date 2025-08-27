# transcription_service/processors/vocabulary_finder.py
"""
SINGLE RESPONSIBILITY: Find vocabulary matches in text
"""
import logging
from typing import List, Dict, NamedTuple, Optional  # ← ADD Optional here
from adjustement_types import VocabularyMatch
from adjustement_cache_manager import VocabularyCacheManager
from adjustement_text_cleaner import TextCleaner

logger = logging.getLogger(__name__)

class VocabularyMatchResult(NamedTuple):
    position: int
    vocab_entry: Dict
    vocab_match: VocabularyMatch

class VocabularyFinder:
    """Finds vocabulary matches in normalized text"""
    
    def __init__(self):
        self.text_cleaner = TextCleaner()
    
    def find_matches(self, text: str, cache_manager: VocabularyCacheManager, 
                    expected_entities_ids: Optional[List[str]] = None) -> List[VocabularyMatchResult]:
        """Find all vocabulary matches in text with entity context filtering"""
        logger.debug(f"Finding vocabulary matches in: '{text}'")
        if expected_entities_ids:
            logger.info(f"Using expected entities context: {expected_entities_ids}")
        
        # Normalize text for matching
        normalized_text = self._normalize_for_matching(text)
        
        # Get and prepare vocabulary
        vocab_entries = cache_manager.get_all_vocab()
        prepared_vocab = self._prepare_vocab_for_matching(vocab_entries, expected_entities_ids)
        
        # Find matches
        matches = self._match_vocabulary(normalized_text, prepared_vocab)
        
        logger.debug(f"Found {len(matches)} vocabulary matches")
        return matches
    
    def _normalize_for_matching(self, text: str) -> str:
        """Normalize text for vocabulary matching"""
        result = text
        result = self.text_cleaner.clean_basic(result)
        result = self.text_cleaner.remove_punctuation(result)
        result = self.text_cleaner.normalize_whitespace(result)
        return result
    
    def _prepare_vocab_for_matching(self, vocab_entries: List[Dict], 
                                   expected_entities_ids: Optional[List[str]] = None) -> List[Dict]:
        """Prepare vocabulary entries for efficient matching with entity context"""
        prepared = []
        
        # Group vocabulary entries by transcription_adjusted
        vocab_groups = {}
        for entry in vocab_entries:
            if not entry.get('transcription_adjusted'):
                continue
            
            adjusted = entry['transcription_adjusted']
            if adjusted not in vocab_groups:
                vocab_groups[adjusted] = []
            vocab_groups[adjusted].append(entry)
        
        # Process each group and select best entry based on context
        for adjusted_text, group_entries in vocab_groups.items():
            selected_entry = self._select_best_vocab_entry(group_entries, expected_entities_ids)
            
            if selected_entry:
                normalized = self._normalize_for_matching(adjusted_text)
                if normalized:
                    prepared.append({
                        'original_entry': selected_entry,
                        'normalized': normalized,
                        'word_count': len(normalized.split()),
                        'selection_reason': getattr(selected_entry, '_selection_reason', 'default')
                    })
        
        # Sort by word count (longer first), then by length
        return sorted(prepared, 
                     key=lambda x: (x['word_count'], len(x['normalized'])), 
                     reverse=True)
    
    def _select_best_vocab_entry(self, entries: List[Dict], 
                                expected_entities_ids: Optional[List[str]] = None) -> Optional[Dict]:
        """
        Select the best vocabulary entry from multiple entries with same transcription_adjusted
        Priority: expected entities > live entities > any entry
        """
        if len(entries) == 1:
            entries[0]['_selection_reason'] = 'only_option'
            return entries[0]
        
        if not expected_entities_ids:
            # No context provided, return first entry with entity or first entry
            for entry in entries:
                if entry.get('entity_type_id'):
                    entry['_selection_reason'] = 'first_with_entity'
                    return entry
            entries[0]['_selection_reason'] = 'first_available'
            return entries[0]
        
        # PRIORITY 1: Entries with entity_type_id in expected_entities_ids
        for entry in entries:
            entity_id = entry.get('entity_type_id')
            if entity_id and entity_id in expected_entities_ids:
                entry['_selection_reason'] = f'matches_expected_entity_{entity_id}'
                logger.info(f"✅ Selected vocab '{entry['transcription_adjusted']}' "
                           f"with expected entity {entity_id}")
                return entry
        
        # PRIORITY 2: Entries with any entity_type_id (fallback)
        for entry in entries:
            if entry.get('entity_type_id'):
                entry['_selection_reason'] = f'fallback_entity_{entry["entity_type_id"]}'
                logger.info(f"⚠️ Selected vocab '{entry['transcription_adjusted']}' "
                           f"with non-expected entity {entry['entity_type_id']} as fallback")
                return entry
        
        # PRIORITY 3: Any entry (last resort)
        entries[0]['_selection_reason'] = 'last_resort'
        logger.warning(f"⚠️ Selected vocab '{entries[0]['transcription_adjusted']}' "
                      f"without entity as last resort")
        return entries[0]
    
    def _match_vocabulary(self, normalized_text: str, prepared_vocab: List[Dict]) -> List[VocabularyMatchResult]:
        """Core matching algorithm"""
        words = normalized_text.split()
        matched_positions = [False] * len(words)
        matches = []
        
        for vocab_data in prepared_vocab:
            entry = vocab_data['original_entry']
            normalized = vocab_data['normalized']
            vocab_words = normalized.split()
            
            # Find positions where this vocab could match
            for i in range(len(words) - len(vocab_words) + 1):
                span = list(range(i, i + len(vocab_words)))
                
                # Skip if any position already matched
                if any(matched_positions[pos] for pos in span):
                    continue
                
                # Check for exact match
                text_segment = words[i:i+len(vocab_words)]
                if text_segment == vocab_words:
                    # Mark positions as matched
                    for pos in span:
                        matched_positions[pos] = True
                    
                    # Create match result
                    matches.append(VocabularyMatchResult(
                        position=i,
                        vocab_entry=entry,
                        vocab_match=VocabularyMatch(
                            id=entry['id'],
                            transcription_fr=entry['transcription_fr'],
                            transcription_adjusted=entry['transcription_adjusted']
                        )
                    ))
                    break
        
        return sorted(matches, key=lambda x: x.position)
