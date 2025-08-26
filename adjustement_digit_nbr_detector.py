# transcription_service/processors/digit_number_detector.py
"""
SINGLE RESPONSIBILITY: Detect and replace digit numbers only
"""
import re
import logging
from typing import Dict

logger = logging.getLogger(__name__)

class DigitNumberDetector:
    """Detects digit numbers and replaces them with entityNumber"""
    
    def __init__(self):
        self.digit_pattern = re.compile(r'\b\d+\b')
    
    def replace_digits(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Replace digit numbers with entityNumber"""
        logger.debug(f"Detecting digits in: '{text}'")
        
        result_text = text
        replacements_made = {}
        
        for digit_match in self.digit_pattern.findall(text):
            # Each digit becomes one entityNumber
            replacement = 'entityNumber' * len(digit_match)
            result_text = re.sub(r'\b' + re.escape(digit_match) + r'\b', replacement, result_text)
            replacements_made[digit_match] = replacement
        
        logger.debug(f"Digits replaced: {replacements_made}")
        return result_text, replacements_made

# transcription_service/processors/decimal_number_detector.py
"""
SINGLE RESPONSIBILITY: Detect and replace decimal numbers only
"""
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
