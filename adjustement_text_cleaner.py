# transcription_service/processors/text_cleaner.py
"""
SINGLE RESPONSIBILITY: Clean and normalize text only
"""
import re
import unicodedata
import logging
from adjustement_french_contractions import CONTRACTION_PATTERNS

logger = logging.getLogger(__name__)

class TextCleaner:
    """Handles basic text cleaning operations"""
    
    def __init__(self):
        # Use the imported patterns
        self.contractions = CONTRACTION_PATTERNS
        
        # Precompile for performance
        self.whitespace_pattern = re.compile(r'\s+')
    
    def clean_basic(self, text: str) -> str:
        """Basic cleaning: lowercase, remove accents"""
        if not text:
            return ""
        
        # Remove accents
        text = unicodedata.normalize('NFD', text)
        text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
        
        # Convert to lowercase
        return text.lower()
    
    def expand_contractions(self, text: str) -> str:
        """Expand French contractions"""
        result = text
        for pattern, replacement in self.contractions.items():
            result = re.sub(pattern, replacement, result)
        return result
    
    def remove_punctuation(self, text: str, keep_decimal_commas: bool = True) -> str:
    """Remove punctuation, keeping commas ONLY between numbers/entityNumber"""
    if keep_decimal_commas:
        # Step 1: Protect decimal commas (between digits or entityNumber)
        protected = re.sub(
            r'((?:entitynumber|\d)),(?=(?:entitynumber|\d))',
            r'\1DECIMAL_COMMA_PLACEHOLDER',
            text,
            flags=re.IGNORECASE
        )
        # Step 2: Remove ALL punctuation (including regular commas)
        cleaned = re.sub(r'[^\w\s]', ' ', protected)
        # Step 3: Restore decimal commas
        return cleaned.replace('DECIMAL_COMMA_PLACEHOLDER', ',')
    else:
        return re.sub(r'[^\w\s]', ' ', text)
    
    def normalize_whitespace(self, text: str) -> str:
        """Normalize all whitespace to single spaces"""
        return self.whitespace_pattern.sub(' ', text).strip()
