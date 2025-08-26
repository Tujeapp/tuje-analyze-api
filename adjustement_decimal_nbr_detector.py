# adjustement_decimal_nbr_detector.py  
import re
import logging
from typing import Tuple, Dict

logger = logging.getLogger(__name__)

class DecimalNumberDetector:
    """Detects decimal numbers and replaces them with entityNumber,entityNumber"""
    
    def __init__(self):
        self.decimal_pattern = re.compile(r'\b\d+[.,]\d+\b')
    
    def replace_decimals(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Replace decimal numbers with entityNumber,entityNumber"""
        logger.debug(f"Detecting decimals in: '{text}'")
        
        result_text = text
        replacements_made = {}
        
        for decimal_match in self.decimal_pattern.findall(text):
            # Split on comma or period
            parts = re.split(r'[.,]', decimal_match)
            replacement_parts = ['entityNumber' * len(part) for part in parts]
            replacement = ','.join(replacement_parts)
            
            result_text = re.sub(r'\b' + re.escape(decimal_match) + r'\b', replacement, result_text)
            replacements_made[decimal_match] = replacement
        
        logger.debug(f"Decimals replaced: {replacements_made}")
        return result_text, replacements_made
