# transcription_service/processors/french_number_detector.py
"""
SINGLE RESPONSIBILITY: Detect and replace French number words only
"""
import re
import logging
from typing import Tuple, Dict
from adjustement_french_numbers import FRENCH_NUMBERS_SORTED

logger = logging.getLogger(__name__)

class FrenchNumberDetector:
    """Detects French number words and replaces them with entityNumber"""
    
    def __init__(self):
        # Import from constants - keep this class focused
        from ..constants.french_numbers import FRENCH_NUMBERS_SORTED
        self.french_numbers = FRENCH_NUMBERS_SORTED
    
    def replace_french_numbers(self, text: str) -> Tuple[str, bool, Dict[str, str]]:
        """
        Replace French number words with entityNumber
        Returns: (modified_text, un_une_was_replaced, replacements_made)
        """
        logger.debug(f"Detecting French numbers in: '{text}'")
        
        result_text = text
        un_une_replaced = False
        replacements_made = {}
        
        for french_number in self.french_numbers:
            pattern = r'\b' + re.escape(french_number) + r'\b'
            matches = re.findall(pattern, result_text, re.IGNORECASE)
            
            if matches:
                # Track un/une specifically
                if french_number.lower() in ['un', 'une']:
                    un_une_replaced = True
                
                # Calculate replacement based on hyphens
                hyphen_count = french_number.count('-')
                replacement = 'entityNumber' * (hyphen_count + 1)
                
                # Replace
                result_text = re.sub(pattern, replacement, result_text, flags=re.IGNORECASE)
                replacements_made[french_number] = replacement
        
        logger.debug(f"French numbers replaced: {replacements_made}")
        return result_text, un_une_replaced, replacements_made
