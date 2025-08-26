# transcription_service/processors/vocabulary_finder.py
"""
SINGLE RESPONSIBILITY: Find vocabulary matches in text
"""
import logging
from adjustement_types import VocabularyMatch
from adjustement_cache_manager import VocabularyCacheManager
from adjustement_text_cleaner import TextCleaner
from typing import List, Dict, NamedTuple

logger = logging.getLogger(__name__)

class VocabularyMatchResult(NamedTuple):
    position: int
    vocab_entry: Dict
    vocab_match: VocabularyMatch

class VocabularyFinder:
    """Finds vocabulary matches in normalized text"""
    
    def __init__(self):
        self.text_cleaner = TextCleaner()
    
    def find_matches(self, text: str, cache_manager: VocabularyCacheManager) -> List[VocabularyMatchResult]:
        """Find all vocabulary matches in text"""
        logger.debug(f"Finding vocabulary matches in: '{text}'")
        
        # Normalize text for matching
        normalized_text = self._normalize_for_matching(text)
        
        # Get and prepare vocabulary
        vocab_entries = cache_manager.get_all_vocab()
        prepared_vocab = self._prepare_vocab_for_matching(vocab_entries)
        
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
    
    def _prepare_vocab_for_matching(self, vocab_entries: List[Dict]) -> List[Dict]:
        """Prepare vocabulary entries for efficient matching"""
        prepared = []
        
        for entry in vocab_entries:
            if not entry.get('transcription_adjusted'):
                continue
            
            normalized = self._normalize_for_matching(entry['transcription_adjusted'])
            if normalized:
                prepared.append({
                    'original_entry': entry,
                    'normalized': normalized,
                    'word_count': len(normalized.split())
                })
        
        # Sort by word count (longer first), then by length
        return sorted(prepared, 
                     key=lambda x: (x['word_count'], len(x['normalized'])), 
                     reverse=True)
    
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
