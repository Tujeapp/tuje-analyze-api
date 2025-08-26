# transcription_service/processors/entity_consolidator.py
"""
SINGLE RESPONSIBILITY: Consolidate multiple entityNumbers into single ones
"""
import re
import logging

logger = logging.getLogger(__name__)

class EntityConsolidator:
    """Consolidates multiple entityNumbers into single entitynumber"""
    
    def __init__(self):
        # Precompile patterns
        self.decimal_pattern = re.compile(r'entitynumber\s*,\s*entitynumber', re.IGNORECASE)
        self.multiple_pattern = re.compile(r'(entitynumber)+', re.IGNORECASE)
    
    def consolidate(self, text: str) -> str:
        """Consolidate entityNumbers into single entitynumber tokens"""
        logger.debug(f"Consolidating entityNumbers in: '{text}'")
        
        # Step 1: Handle decimal patterns first
        result = self.decimal_pattern.sub('entitynumber', text)
        
        # Step 2: Handle multiple consecutive patterns  
        result = self.multiple_pattern.sub('entitynumber', result)
        
        logger.debug(f"Consolidation result: '{text}' → '{result}'")
        return result
