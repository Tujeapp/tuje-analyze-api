# transcription_service/constants/french_numbers.py
"""
SINGLE RESPONSIBILITY: French number constants only
"""

# Complete French numbers list (hardcoded for reliability)
FRENCH_NUMBERS_BASE = [
    # Basic numbers
    "zéro", "un", "une", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
    "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize", 
    "dix-sept", "dix-huit", "dix-neuf",
    
    # Tens
    "vingt", "trente", "quarante", "cinquante", "soixante", 
    "soixante-dix", "quatre-vingts", "quatre-vingt-dix",
    
    # Common compound numbers
    "vingt-et-un", "vingt-deux", "vingt-trois", "vingt-quatre", "vingt-cinq",
    "vingt-six", "vingt-sept", "vingt-huit", "vingt-neuf",
    "trente-et-un", "trente-deux", "quarante-et-un", "cinquante-et-un",
    "soixante-et-un", "soixante-et-onze", "quatre-vingt-un"
]

# Sort by length (longest first) for proper matching
FRENCH_NUMBERS_SORTED = sorted(FRENCH_NUMBERS_BASE, key=len, reverse=True)

# transcription_service/constants/french_contractions.py  
"""
SINGLE RESPONSIBILITY: French contraction patterns only
"""

CONTRACTION_PATTERNS = {
    r"\bj'ai\b": "jai",
    r"\bj'": "j ",
    r"\bd'": "de ",
    r"\bl'": "le ",
    r"\bc'est\b": "cest",
    r"\bc'": "ce ",
    r"\bqu'": "que ",
    r"\bn'": "ne ",
    r"\bt'": "te ",
    r"\bs'": "se ",
    r"\bm'": "me "
}

# transcription_service/constants/__init__.py
"""Constants for the transcription service"""
