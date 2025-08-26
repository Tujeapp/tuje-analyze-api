# transcription_service/processors/un_une_analyzer.py
"""
SINGLE RESPONSIBILITY: Analyze un/une context to decide number vs article
"""
import logging
from typing import List
from adjustement_cache_manager import VocabularyCacheManager

logger = logging.getLogger(__name__)

class UnUneAnalyzer:
    """Analyzes un/une usage to determine if it should be a number or article"""
    
    def __init__(self, cache_manager: VocabularyCacheManager):
        self.cache_manager = cache_manager
    
    def analyze_and_fix(self, text: str) -> str:
        """Analyze entityNumber positions that came from un/une and fix if needed"""
        logger.info(f"Analyzing un/une usage in: '{text}'")
        
        words = text.split()
        result_words = []
        
        for i, word in enumerate(words):
            if word == 'entityNumber':
                decision = self._analyze_entitynumber_context(words, i)
                
                if decision == 'keep_as_number':
                    result_words.append(word)
                elif decision == 'revert_to_article':
                    result_words.append('un')  # Could be enhanced to choose un vs une
                    logger.debug(f"Reverted entityNumber to 'un' at position {i}")
                else:
                    # Default: keep as is
                    result_words.append(word)
            else:
                result_words.append(word)
        
        result = ' '.join(result_words)
        logger.info(f"Un/une analysis result: '{text}' → '{result}'")
        return result
    
    def _analyze_entitynumber_context(self, words: List[str], position: int) -> str:
        """Analyze context around entityNumber to make decision"""
        context_before = words[position-1] if position > 0 else ''
        context_after = words[position+1] if position < len(words)-1 else ''
        
        # Rule 1: "un peu" is almost always an article
        if context_after.lower() == 'peu':
            logger.debug(f"Found 'entityNumber peu' pattern - treating as article")
            return 'revert_to_article'
        
        # Rule 2: Check vocabulary patterns for number usage
        if self._has_number_pattern_in_vocab(context_before, context_after):
            logger.debug(f"Found number pattern in vocabulary")
            return 'keep_as_number'
        
        # Rule 3: Default to article if uncertain
        logger.debug(f"No clear number pattern found - treating as article")
        return 'revert_to_article'
    
    def _has_number_pattern_in_vocab(self, context_before: str, context_after: str) -> bool:
        """Check if context suggests this should be a number"""
        entitynumber_patterns = self.cache_manager.get_entitynumber_patterns()
        
        # Generate potential phrases to check
        potential_phrases = []
        if context_after:
            potential_phrases.append(f"entitynumber {context_after}")
        if context_before:
            potential_phrases.append(f"{context_before} entitynumber")
        if context_before and context_after:
            potential_phrases.append(f"{context_before} entitynumber {context_after}")
        
        # Check against vocabulary
        for phrase in potential_phrases:
            for pattern_entry in entitynumber_patterns:
                if phrase.lower() in pattern_entry['transcription_fr'].lower():
                    logger.debug(f"Found pattern match: '{phrase}' in vocabulary")
                    return True
        
        return False
