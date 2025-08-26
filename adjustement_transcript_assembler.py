# transcription_service/processors/transcript_assembler.py
"""
SINGLE RESPONSIBILITY: Assemble final transcript from matches
"""
import logging
from typing import List
from adjustement_vocabulary_finder import VocabularyMatchResult

logger = logging.getLogger(__name__)

class TranscriptAssembler:
    """Assembles the final adjusted transcript from vocabulary matches"""
    
    def assemble_transcript(self, normalized_text: str, matches: List[VocabularyMatchResult]) -> str:
        """Assemble final transcript from vocabulary matches"""
        logger.debug(f"Assembling transcript from {len(matches)} matches")
        
        words = normalized_text.split()
        transcript_parts = ['vocabnotfound'] * len(words)
        
        # Process each match
        for match in matches:
            self._apply_match_to_transcript(transcript_parts, match)
        
        # Filter out None values and join
        valid_parts = [part for part in transcript_parts if part is not None]
        result = ' '.join(valid_parts)
        
        logger.debug(f"Assembled transcript: '{result}'")
        return result
    
    def _apply_match_to_transcript(self, transcript_parts: List[str], match: VocabularyMatchResult):
        """Apply a single match to the transcript parts"""
        position = match.position
        vocab_adjusted = match.vocab_entry['transcription_adjusted']
        vocab_words = vocab_adjusted.split()
        
        # Set the first position to the full transcription_adjusted
        # Set subsequent positions to None (they'll be filtered out)
        for i, _ in enumerate(vocab_words):
            pos = position + i
            if pos < len(transcript_parts):
                if i == 0:
                    transcript_parts[pos] = vocab_adjusted
                else:
                    transcript_parts[pos] = None
