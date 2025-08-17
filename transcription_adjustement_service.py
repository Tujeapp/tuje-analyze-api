from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional, Tuple
import asyncpg
import re
import unicodedata
import asyncio
import logging
from datetime import datetime

from config import DATABASE_URL

router = APIRouter()
logger = logging.getLogger(__name__)

class TranscriptionAdjustRequest(BaseModel):
    original_transcript: str
    user_id: Optional[str] = None
    interaction_id: Optional[str] = None
    expected_entities: Optional[List[str]] = None

class EntityMatch(BaseModel):
    original_text: str
    entity_replacement: str
    entity_type: str
    start_pos: int
    end_pos: int
    confidence: float
    source: str
    phase: int  # 1 or 2

class AdjustmentResult(BaseModel):
    original_transcript: str
    phase0_result: str       # After preprocessing
    normalized_transcript: str
    phase1_result: str       # After number conversion
    adjusted_transcript: str # Final result
    entities_found: List[EntityMatch]
    processing_time_ms: int

class ThreePhaseTranscriptionAdjuster:
    def __init__(self):
        self.regular_entities = {}     # Cache for regular entities (no entityNumber)
        self.pattern_entities = {}     # Cache for pattern entities (with entityNumber)
        self.number_patterns = {}      # Cache for number patterns
        self.cache_loaded = False
    
    async def load_entities_cache(self, pool: asyncpg.Pool):
        """Load entities and number patterns from database"""
        if self.cache_loaded:
            return
            
        try:
            async with pool.acquire() as conn:
                # Load pattern-based entities (contain 'entityNumber' in transcription_fr)
                pattern_rows = await conn.fetch("""
                    SELECT 
                        bv.transcription_fr,
                        bv.transcription_adjusted, 
                        bv.entity_type_id,
                        bet.priority as type_priority,
                        bv.entity_priority
                    FROM brain_vocab bv
                    JOIN brain_entity_type bet ON bv.entity_type_id = bet.id
                    WHERE bv.transcription_fr LIKE '%entityNumber%'
                    AND bv.entity_type_id != 'entityNumber'
                    ORDER BY 
                        bet.priority DESC, 
                        bv.entity_priority DESC,
                        LENGTH(bv.transcription_fr) DESC
                """)
                
                # Load regular entities (no 'entityNumber' placeholder)
                entity_rows = await conn.fetch("""
                    SELECT 
                        bv.transcription_fr,
                        bv.transcription_adjusted, 
                        bv.entity_type_id,
                        bet.priority as type_priority,
                        bv.entity_priority
                    FROM brain_vocab bv
                    JOIN brain_entity_type bet ON bv.entity_type_id = bet.id
                    WHERE bv.transcription_fr NOT LIKE '%entityNumber%'
                    AND bv.entity_type_id != 'entityNumber'
                    AND bv.entity_type_id IS NOT NULL
                    ORDER BY 
                        bet.priority DESC, 
                        bv.entity_priority DESC,
                        LENGTH(bv.transcription_fr) DESC
                """)
                
                # Load basic numbers for phase 1
                number_rows = await conn.fetch("""
                    SELECT transcription_fr, transcription_adjusted
                    FROM brain_vocab bv
                    WHERE entity_type_id = 'entityNumber'
                    ORDER BY LENGTH(transcription_fr) DESC
                """)
                
                # Organize data
                self.pattern_entities = {'entities': []}
                self.regular_entities = {'entities': []}
                self.number_patterns = {
                    'written_numbers': [],
                    'digit_patterns': [r'\b\d+\b', r'\b\d+h\d*\b', r'\b\d+[.,]\d+\b']
                }
                
                # Process pattern entities
                for row in pattern_rows:
                    entity_data = {
                        'original_text': row['transcription_fr'],
                        'normalized_text': self._normalize_for_matching(row['transcription_fr']),
                        'entity_type': row['entity_type_id'],
                        'type_priority': row['type_priority'],
                        'entity_priority': row['entity_priority'] or 0
                    }
                    self.pattern_entities['entities'].append(entity_data)
                
                # Process regular entities
                for row in entity_rows:
                    entity_data = {
                        'original_text': row['transcription_fr'],
                        'normalized_text': self._normalize_for_matching(row['transcription_fr']),
                        'entity_type': row['entity_type_id'],
                        'type_priority': row['type_priority'],
                        'entity_priority': row['entity_priority'] or 0
                    }
                    self.regular_entities['entities'].append(entity_data)
                
                # Process number patterns
                for row in number_rows:
                    normalized = self._normalize_for_matching(row['transcription_fr'])
                    self.number_patterns['written_numbers'].append(normalized)
                
                self.cache_loaded = True
                logger.info(f"Loaded {len(self.pattern_entities['entities'])} pattern entities")
                logger.info(f"Loaded {len(self.regular_entities['entities'])} regular entities")
                logger.info(f"Loaded {len(self.number_patterns['written_numbers'])} written number patterns")
                    
        except Exception as e:
            logger.error(f"Error loading entities cache: {e}")
            raise
    
    def _normalize_for_matching(self, text: str) -> str:
        """Normalize text for entity matching (used for database patterns)"""
        # This is a lighter normalization for matching against database entries
        if not text:
            return ""
        
        # Remove accents
        text = unicodedata.normalize('NFD', text)
        text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
        
        # Convert to lowercase
        text = text.lower()
        
        # Basic contraction handling for matching
        text = re.sub(r"\bj'", "jai ", text)
        text = re.sub(r"\bd'", "de ", text)
        text = re.sub(r"\bl'", "le ", text)
        
        return text.strip()entityNumber\s+(ans?|annees?|mois|jours?|semaines?|heures?)\b',  # "entityNumber ans"
                    r'\b(depuis|pendant|durant|en)\s+entityNumber\b',                 # "depuis entityNumber"
                    r'entityNumber\s+(de|d)\s+(temps|duree)\b'                        # "entityNumber de temps"
                ],
                'context_phrases': [
                    'depuis', 'pendant', 'durant', 'combien de temps', 'duree',
                    'longtemps', 'en', 'dans'
                ]
            },
            'entityPrice': {
                'patterns': [
                    r'entityNumber\s+(euros?|dollars?|centimes?|francs?)\b',  # "entityNumber euros"
                    r'\b(coute|prix|paye|achete)\b.*entityNumber',           # "coûte ... entityNumber"
                    r'entityNumber\s+(€|\$|EUR|USD)\b'                       # "entityNumber €"
                ],
                'context_phrases': [
                    'coute', 'prix', 'cher', 'gratuit', 'payer', 'acheter',
                    'vendre', 'euros', 'dollars', 'argent', 'budget'
                ]
            },
            'entityFrequency': {
                'patterns': [
                    r'entityNumber\s+fois\b',                               # "entityNumber fois"
                    r'entityNumber\s+fois\s+(par|de|du)\b',                 # "entityNumber fois par"
                    r'\b(souvent|parfois|jamais)\b.*entityNumber'          # frequency words
                ],
                'context_phrases': [
                    'fois', 'souvent', 'parfois', 'jamais', 'toujours',
                    'frequence', 'regulierement', 'par semaine', 'par jour'
                ]
            },
            'entityDate': {
                'patterns': [
                    r'entityNumber\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)\b',
                    r'\b(en|le|du)\s+entityNumber\b',                       # "en entityNumber"
                    r'entityNumber\s+(annee|an)\b'                          # "entityNumber année"
                ],
                'context_phrases': [
                    'date', 'annee', 'en', 'le', 'du', 'quand', 'janvier', 'fevrier',
                    'mars', 'avril', 'mai', 'juin', 'juillet', 'aout', 'septembre',
                    'octobre', 'novembre', 'decembre'
                ]
            }
        }
    
    def _phase0_preprocessing(self, text: str) -> str:
        """Phase 0: Clean and standardize the input text"""
        if not text:
            return ""
        
        logger.info(f"Phase 0 input: '{text}'")
        
        # Step 1: Remove accents but preserve structure
        text = unicodedata.normalize('NFD', text)
        text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
        
        # Step 2: Convert to lowercase
        text = text.lower()
        
        # Step 3: Handle French contractions (preserve word boundaries)
        contractions = {
            r"\bj'": "jai ",
            r"\bd'": "de ",
            r"\bl'": "le ",
            r"\bc'": "ce ",
            r"\bqu'": "que ",
            r"\bn'": "ne ",
            r"\bt'": "te ",
            r"\bs'": "se ",
            r"\bm'": "me ",
            r"\bv'": "ve "
        }
        
        for pattern, replacement in contractions.items():
            text = re.sub(pattern, replacement, text)
        
        # Step 4: PRESERVE DECIMAL COMMAS - Handle decimal numbers carefully
        # First, identify and temporarily mark decimal patterns
        # French uses comma as decimal separator: 1,50 euros, 2,75
        decimal_placeholder_map = {}
        decimal_counter = 0
        
        # Find decimal patterns with comma (digit,digit format)
        decimal_pattern = r'(\d+),(\d{1,2})\b'  # 1,50 or 12,99 (1-2 digits after comma)
        
        def replace_decimal(match):
            nonlocal decimal_counter
            decimal_counter += 1
            full_match = match.group(0)
            placeholder = f"DECIMAL_PLACEHOLDER_{decimal_counter}"
            # Convert comma to period for internal processing: 1,50 -> 1.50
            decimal_value = f"{match.group(1)}.{match.group(2)}"
            decimal_placeholder_map[placeholder] = decimal_value
            logger.info(f"Preserving decimal: '{full_match}' -> '{decimal_value}' (placeholder: {placeholder})")
            return placeholder
        
        text = re.sub(decimal_pattern, replace_decimal, text)
        
        # Step 5: Remove most punctuation but preserve important separators
        # Now safe to remove commas since decimals are protected
        text = re.sub(r'[^\w\s\.]', ' ', text)
        
        # Step 6: Handle space normalization
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        # Step 7: Handle specific French number words that might have been split
        french_compound_numbers = {
            'vingt et un': 'vingtetun',
            'vingt deux': 'vingtdeux', 
            'vingt trois': 'vingttrois',
            'vingt quatre': 'vingtquatre',
            'vingt cinq': 'vingtcinq',
            'vingt six': 'vingtsix',
            'vingt sept': 'vingtsept',
            'vingt huit': 'vingthuit',
            'vingt neuf': 'vingtneuf',
            'trente et un': 'trenteun',
            'trente deux': 'trentedeux',
            'trente trois': 'trentetrois',
            'trente quatre': 'trentequatre',
            'trente cinq': 'trentecinq',
            'quarante cinq': 'quarantecinq',
            'cinquante trois': 'cinquantetrois',
            'soixante dix': 'soixantedix',
            'quatre vingt': 'quatrevingt',
            'quatre vingt dix': 'quatrevingdix'
        }
        
        for compound, replacement in french_compound_numbers.items():
            text = text.replace(compound, replacement)
        
        # Step 8: Restore decimal numbers with periods
        for placeholder, decimal_value in decimal_placeholder_map.items():
            text = text.replace(placeholder, decimal_value)
            logger.info(f"Restored decimal: {placeholder} -> {decimal_value}")
        
        logger.info(f"Phase 0 output: '{text}'")
        return text
    
    def _phase1_convert_numbers_digit_by_digit(self, text: str) -> Tuple[str, List[EntityMatch]]:
        """Phase 1: Convert numbers digit-by-digit to entityNumber patterns"""
        phase1_matches = []
        result_text = text
        
        # First, handle written numbers (convert to digits for consistency)
        for written_number in self.number_patterns['written_numbers']:
            pattern = r'\b' + re.escape(written_number) + r'\b'
            matches = list(re.finditer(pattern, result_text))
            
            for match in reversed(matches):
                # Convert written number to its digit equivalent
                digit_equivalent = self._written_to_digit(written_number)
                if digit_equivalent:
                    # Replace with digit equivalent, will be processed in next step
                    result_text = (result_text[:match.start()] + 
                                 str(digit_equivalent) + 
                                 result_text[match.end():])
                    
                    phase1_matches.append(EntityMatch(
                        original_text=match.group(),
                        entity_replacement=str(digit_equivalent),
                        entity_type='entityNumber',
                        start_pos=match.start(),
                        end_pos=match.end(),
                        confidence=0.95,
                        source='written_to_digit',
                        phase=1
                    ))
        
        # Enhanced digit patterns including decimals and multi-digit numbers
        digit_patterns = [
            r'\b\d+\.\d+\b',    # Decimal numbers like 1.50, 2.75 (handle first - longer pattern)
            r'\b\d{4}\b',       # 4-digit numbers like 2025, 1990 (years)
            r'\b\d{3}\b',       # 3-digit numbers like 150, 250
            r'\b\d{2}\b',       # 2-digit numbers like 35, 99
            r'\b\d{1}\b',       # 1-digit numbers like 5, 9
            r'\b\d+h\d*\b'      # Time patterns like 14h, 14h30
        ]
        
        for digit_pattern in digit_patterns:
            matches = list(re.finditer(digit_pattern, result_text))
            
            for match in reversed(matches):
                # Skip if already converted
                if 'entityNumber' in result_text[match.start():match.end()]:
                    continue
                
                number_str = match.group()
                
                # Convert digit-by-digit for numbers 
                if '.' in number_str:
                    # Handle decimals specially - keep as single entityNumber
                    entity_replacement = 'entityNumber'
                elif 'h' in number_str:
                    # Handle time patterns specially
                    entity_replacement = 'entityNumber'
                else:
                    # Convert each digit to entityNumber
                    entity_replacement = self._convert_number_to_entity_pattern(number_str)
                
                phase1_matches.append(EntityMatch(
                    original_text=number_str,
                    entity_replacement=entity_replacement,
                    entity_type='entityNumber',
                    start_pos=match.start(),
                    end_pos=match.end(),
                    confidence=0.95,
                    source='digit_pattern',
                    phase=1
                ))
                
                # Replace in text
                result_text = (result_text[:match.start()] + 
                             entity_replacement + 
                             result_text[match.end():])
        
        logger.info(f"Phase 1 digit-by-digit: '{text}' -> '{result_text}'")
        return result_text, phase1_matches
    
    def _written_to_digit(self, written_number: str) -> int:
        """Convert written French numbers to digits"""
        number_map = {
            'zero': 0, 'un': 1, 'deux': 2, 'trois': 3, 'quatre': 4, 'cinq': 5,
            'six': 6, 'sept': 7, 'huit': 8, 'neuf': 9, 'dix': 10,
            'onze': 11, 'douze': 12, 'treize': 13, 'quatorze': 14, 'quinze': 15,
            'seize': 16, 'dix-sept': 17, 'dix-huit': 18, 'dix-neuf': 19,
            'vingt': 20, 'trente': 30, 'quarante': 40, 'cinquante': 50,
            'soixante': 60, 'soixante-dix': 70, 'quatre-vingt': 80, 'quatre-vingt-dix': 90,
            'cent': 100,
            # Compound numbers from preprocessing
            'vingtetun': 21, 'vingtdeux': 22, 'vingttrois': 23, 'vingtquatre': 24,
            'vingtcinq': 25, 'vingtsix': 26, 'vingtsept': 27, 'vingthuit': 28, 'vingtneuf': 29,
            'trenteun': 31, 'trentedeux': 32, 'trentetrois': 33, 'trentequatre': 34,
            'trentecinq': 35, 'quarantecinq': 45, 'cinquantetrois': 53,
            'soixantedix': 70, 'quatrevingt': 80, 'quatrevingdix': 90
        }
        return number_map.get(written_number.lower())
    
    def _convert_number_to_entity_pattern(self, number_str: str) -> str:
        """Convert a number string to entityNumber pattern digit-by-digit"""
        # For each digit, create entityNumber
        entity_parts = []
        for char in number_str:
            if char.isdigit():
                entity_parts.append('entityNumber')
            # Skip non-digit characters for now
        
        return ''.join(entity_parts)
    
    def _phase1_convert_numbers(self, text: str) -> Tuple[str, List[EntityMatch]]:
        """Phase 1: Use the new digit-by-digit approach"""
        return self._phase1_convert_numbers_digit_by_digit(text)
    
    def _phase2_database_pattern_matching(self, text: str, expected_entities: Optional[List[str]] = None) -> Tuple[str, List[EntityMatch]]:
        """Phase 2: Use database patterns to convert entityNumber to specific entities"""
        if 'entityNumber' not in text:
            return text, []
        
        phase2_matches = []
        result_text = text
        
        # Filter pattern entities by expected types if provided
        patterns_to_check = self.pattern_entities['entities']
        if expected_entities:
            patterns_to_check = [
                pattern for pattern in patterns_to_check
                if pattern['entity_type'] in expected_entities
            ]
            logger.info(f"Filtering to {len(patterns_to_check)} patterns from expected types: {expected_entities}")
        
        # Sort patterns by priority and length (longest first for greedy matching)
        sorted_patterns = sorted(patterns_to_check, key=lambda x: (
            -x['type_priority'], 
            -x['entity_priority'], 
            -len(x['normalized_text'])
        ))
        
        # Track replaced positions to avoid overlaps
        replaced_positions = set()
        
        for pattern in sorted_patterns:
            pattern_text = pattern['normalized_text']
            
            # Create regex pattern for matching
            pattern_regex = r'\b' + re.escape(pattern_text) + r'\b'
            
            for match in re.finditer(pattern_regex, result_text):
                start_pos = match.start()
                end_pos = match.end()
                
                # Check if this position overlaps with already replaced text
                if any(pos in replaced_positions for pos in range(start_pos, end_pos)):
                    continue
                
                # Calculate confidence
                confidence = 0.90  # High confidence for database patterns
                if expected_entities and pattern['entity_type'] in expected_entities:
                    confidence = 0.95  # Even higher for expected entities
                
                phase2_matches.append(EntityMatch(
                    original_text=match.group(),
                    entity_replacement=pattern['entity_type'],
                    entity_type=pattern['entity_type'],
                    start_pos=start_pos,
                    end_pos=end_pos,
                    confidence=confidence,
                    source='database_pattern',
                    phase=2
                ))
                
                # Replace in text
                result_text = (result_text[:start_pos] + 
                             pattern['entity_type'] + 
                             result_text[end_pos:])
                
                # Mark positions as replaced
                replaced_positions.update(range(start_pos, start_pos + len(pattern['entity_type'])))
                
                logger.info(f"Phase 2 DB pattern: '{match.group()}' -> {pattern['entity_type']} (confidence: {confidence})")
                
                # Break to avoid multiple replacements of the same pattern
                break
        
        return result_text, phase2_matches
    
    def _find_regular_entities(self, text: str, expected_entities: Optional[List[str]] = None) -> List[EntityMatch]:
        """Find regular entities in the text (no entityNumber placeholder)"""
        matches = []
        
        # Filter entities if expected_entities provided
        entities_to_search = self.regular_entities['entities']
        if expected_entities:
            entities_to_search = [
                entity for entity in entities_to_search
                if entity['entity_type'] in expected_entities
            ]
        
        for entity in entities_to_search:
            pattern = r'\b' + re.escape(entity['normalized_text']) + r'\b'
            
            for match in re.finditer(pattern, text):
                confidence = 0.95
                if expected_entities and entity['entity_type'] in expected_entities:
                    confidence = 0.98
                
                matches.append(EntityMatch(
                    original_text=entity['original_text'],
                    entity_replacement=entity['entity_type'],
                    entity_type=entity['entity_type'],
                    start_pos=match.start(),
                    end_pos=match.end(),
                    confidence=confidence,
                    source='static',
                    phase=1
                ))
        
        return matches
    
    async def adjust_transcription(self, request: TranscriptionAdjustRequest, pool: asyncpg.Pool) -> AdjustmentResult:
        """Main three-phase adjustment function"""
        start_time = datetime.now()
        
        # Load cache if needed
        await self.load_entities_cache(pool)
        
        # Get expected entities from database if not provided
        expected_entities = request.expected_entities
        if request.interaction_id and not expected_entities:
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        SELECT expected_entities 
                        FROM brain_interaction 
                        WHERE id = $1
                    """, request.interaction_id)
                    if row and row['expected_entities']:
                        expected_entities = row['expected_entities']
                        logger.info(f"Retrieved expected entities from DB: {expected_entities}")
            except Exception as e:
                logger.warning(f"Could not fetch expected entities: {e}")
        
        # Phase 0: Preprocessing - clean and standardize input
        phase0_result = self._phase0_preprocessing(request.original_transcript)
        
        # Legacy normalization for backward compatibility in logs
        normalized_text = phase0_result  # Same as phase0 for now
        
        # Phase 1: Convert all numbers to entityNumber + find regular entities
        phase1_text, number_matches = self._phase1_convert_numbers(phase0_result)
        regular_matches = self._find_regular_entities(phase1_text, expected_entities)
        
        # Apply regular entity replacements to phase1 text
        # Sort by position in reverse order to maintain positions
        sorted_regular = sorted(regular_matches, key=lambda x: x.start_pos, reverse=True)
        for match in sorted_regular:
            phase1_text = (phase1_text[:match.start_pos] + 
                          match.entity_replacement + 
                          phase1_text[match.end_pos:])
        
        # Phase 2: Use database patterns to contextualize entityNumber → specific entities
        final_text, pattern_matches = self._phase2_database_pattern_matching(phase1_text, expected_entities)
        
        # Combine all matches
        all_matches = number_matches + regular_matches + pattern_matches
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        logger.info(f"Three-phase adjustment completed in {processing_time:.2f}ms")
        logger.info(f"Original: '{request.original_transcript}'")
        logger.info(f"Phase 0 (preprocessing): '{phase0_result}'")
        logger.info(f"Phase 1 (numbers): '{phase1_text}'")
        logger.info(f"Final: '{final_text}'")
        logger.info(f"Expected entities: {expected_entities}")
        logger.info(f"Total entities found: {len(all_matches)}")
        
        return AdjustmentResult(
            original_transcript=request.original_transcript,
            phase0_result=phase0_result,
            normalized_transcript=normalized_text,
            phase1_result=phase1_text,
            adjusted_transcript=final_text,
            entities_found=all_matches,
            processing_time_ms=round(processing_time, 2)
        )

# Global adjuster instance
adjuster = ThreePhaseTranscriptionAdjuster()

@router.post("/adjust-transcription", response_model=AdjustmentResult)
async def adjust_transcription_endpoint(request: TranscriptionAdjustRequest):
    """API endpoint for two-phase transcription adjustment"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        
        try:
            result = await adjuster.adjust_transcription(request, pool)
            return result
        finally:
            await pool.close()
        
    except Exception as e:
        logger.error(f"Transcription adjustment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/test-digit-by-digit")
async def test_digit_by_digit():
    """Test the digit-by-digit number composition approach"""
    test_cases = [
        {
            "scenario": "Year - 4 digits",
            "input": "On est en 2025",
            "expected_entities": ["entityDate"],
            "phase1_expected": "on est en entityNumberentityNumberentityNumberentityNumber",
            "final_expected": "on est en entityYear",
            "explanation": "2025 becomes 4 entityNumbers, matches year pattern"
        },
        {
            "scenario": "Price - 3 digits",
            "input": "Ça coûte 150 euros",
            "expected_entities": ["entityPrice"],
            "phase1_expected": "ca coute entityNumberentityNumberentityNumber euros",
            "final_expected": "ca coute entityPrice",
            "explanation": "150 becomes 3 entityNumbers, matches price pattern"
        },
        {
            "scenario": "Price - 2 digits", 
            "input": "Ça coûte 75 euros",
            "expected_entities": ["entityPrice"],
            "phase1_expected": "ca coute entityNumberentityNumber euros",
            "final_expected": "ca coute entityPrice",
            "explanation": "75 becomes 2 entityNumbers, matches price pattern"
        },
        {
            "scenario": "Age - 2 digits",
            "input": "J'ai 35 ans",
            "expected_entities": ["entityAge"],
            "phase1_expected": "jai entityNumberentityNumber ans",
            "final_expected": "jai entityAge",
            "explanation": "35 becomes 2 entityNumbers, matches age pattern"
        },
        {
            "scenario": "Time - 2 digits",
            "input": "À 14h",
            "expected_entities": ["entityTime"],
            "phase1_expected": "a entityNumberentityNumber h",
            "final_expected": "a entityTime",
            "explanation": "14 becomes 2 entityNumbers, matches time pattern"
        },
        {
            "scenario": "Written number conversion",
            "input": "J'ai trente-cinq ans",
            "expected_entities": ["entityAge"],
            "phase1_expected": "jai entityNumberentityNumber ans",
            "final_expected": "jai entityAge", 
            "explanation": "trente-cinq -> trentecinq -> 35 -> entityNumberentityNumber"
        },
        {
            "scenario": "Decimal price (special case)",
            "input": "Ça coûte 12,50 euros",
            "expected_entities": ["entityPrice"],
            "phase1_expected": "ca coute entityNumber euros",
            "final_expected": "ca coute entityPrice",
            "explanation": "12.50 stays as single entityNumber (decimal)"
        },
        {
            "scenario": "Mixed numbers",
            "input": "J'ai 25 ans depuis 2020",
            "expected_entities": ["entityAge", "entityYear"],
            "phase1_expected": "jai entityNumberentityNumber ans depuis entityNumberentityNumberentityNumberentityNumber",
            "final_expected": "jai entityAge depuis entityYear",
            "explanation": "25 (2 digits) and 2020 (4 digits) get different patterns"
        },
        {
            "scenario": "Single digit",
            "input": "J'ai 5 ans",
            "expected_entities": ["entityAge"],
            "phase1_expected": "jai entityNumber ans",
            "final_expected": "jai entityAge",
            "explanation": "5 becomes single entityNumber, matches 1-digit age pattern"
        }
    ]
    
    results = []
    for case in test_cases:
        try:
            request = TranscriptionAdjustRequest(
                original_transcript=case["input"],
                expected_entities=case["expected_entities"]
            )
            result = await adjust_transcription_endpoint(request)
            
            results.append({
                "scenario": case["scenario"],
                "input": case["input"],
                "expected_entities": case["expected_entities"],
                "phase0_result": result.phase0_result,
                "phase1_result": result.phase1_result,
                "phase1_expected": case["phase1_expected"],
                "phase1_matches": result.phase1_result == case["phase1_expected"],
                "final_result": result.adjusted_transcript,
                "final_expected": case["final_expected"],
                "final_matches": result.adjusted_transcript == case["final_expected"],
                "explanation": case["explanation"],
                "entities_found": [
                    {
                        "original": e.original_text,
                        "replacement": e.entity_replacement,
                        "type": e.entity_type,
                        "phase": e.phase,
                        "source": e.source
                    } for e in result.entities_found
                ],
                "processing_time": result.processing_time_ms
            })
        except Exception as e:
            results.append({
                "scenario": case["scenario"],
                "error": str(e)
            })
    
    return {
        "digit_by_digit_tests": results,
        "summary": {
            "total_tests": len(test_cases),
            "phase1_successful": len([r for r in results if r.get("phase1_matches", False)]),
            "final_successful": len([r for r in results if r.get("final_matches", False)]),
            "approach_benefits": [
                "Only need 0-99 numbers in database (100 entries vs 1000s)",
                "Handles any number composition automatically",
                "More flexible pattern matching",
                "Easier to maintain and extend"
            ],
            "pattern_examples": {
                "1_digit": "entityNumber (5, 8, 9)",
                "2_digit": "entityNumberentityNumber (35, 75, 99)",
                "3_digit": "entityNumberentityNumberentityNumber (150, 250, 999)",
                "4_digit": "entityNumberentityNumberentityNumberentityNumber (2025, 1990)"
            }
        }
    }
async def test_whisper_scenarios():
    """Test common Whisper transcription scenarios including decimal handling"""
    whisper_test_cases = [
        {
            "scenario": "Decimal price - French comma format",
            "whisper_output": "Un café coûte 1,50 euros à Paris",
            "expected_entities": ["entityPrice", "entityCity"],
            "expected_result": "un cafe coute entityPrice a entityCity",
            "key_test": "Preserves 1,50 as 1.50 in entityNumber conversion"
        },
        {
            "scenario": "Complex decimal price",
            "whisper_output": "Le repas coûte 12,75 euros",
            "expected_entities": ["entityPrice"],
            "expected_result": "le repas coute entityPrice",
            "key_test": "Handles 12,75 -> 12.75"
        },
        {
            "scenario": "Age - digit form (common Whisper output)",
            "whisper_output": "J'ai 35 ans",
            "expected_entities": ["entityAge"],
            "expected_result": "jai entityAge"
        },
        {
            "scenario": "Age - written compound number",
            "whisper_output": "J'ai trente-cinq ans", 
            "expected_entities": ["entityAge"],
            "expected_result": "jai entityAge",
            "key_test": "Handles trente-cinq -> trentecinq -> entityNumber"
        },
        {
            "scenario": "Time with contractions",
            "whisper_output": "À 14h du matin",
            "expected_entities": ["entityTime"],
            "expected_result": "a entityTime"
        },
        {
            "scenario": "Mixed punctuation and decimals",
            "whisper_output": "Ça coûte 2,99 euros, vraiment!",
            "expected_entities": ["entityPrice"],
            "expected_result": "ca coute entityPrice vraiment",
            "key_test": "Removes punctuation but preserves decimal 2,99 -> 2.99"
        },
        {
            "scenario": "Multiple decimals in sentence",
            "whisper_output": "J'ai acheté 1,5 kg de pommes pour 3,75 euros",
            "expected_entities": ["entityPrice"],
            "expected_result": "jai achete entityNumber kg de pommes pour entityPrice",
            "key_test": "Handles multiple decimals: 1,5 and 3,75"
        },
        {
            "scenario": "Decimal without price context",
            "whisper_output": "Il mesure 1,80 mètres",
            "expected_entities": [],
            "expected_result": "il mesure entityNumber metres",
            "key_test": "Preserves 1,80 as entityNumber when no price context"
        }
    ]
    
    results = []
    for case in whisper_test_cases:
        try:
            request = TranscriptionAdjustRequest(
                original_transcript=case["whisper_output"],
                expected_entities=case["expected_entities"] if case["expected_entities"] else None
            )
            result = await adjust_transcription_endpoint(request)
            
            results.append({
                "scenario": case["scenario"],
                "whisper_input": case["whisper_output"],
                "expected_entities": case["expected_entities"],
                "expected_result": case["expected_result"],
                "actual_result": result.adjusted_transcript,
                "phase0_result": result.phase0_result,
                "phase1_result": result.phase1_result,
                "matches_expected": result.adjusted_transcript == case["expected_result"],
                "key_test": case.get("key_test", ""),
                "entities_found": [
                    {
                        "text": e.original_text,
                        "entity": e.entity_replacement,
                        "phase": e.phase,
                        "source": e.source,
                        "confidence": e.confidence
                    } for e in result.entities_found
                ],
                "processing_time": result.processing_time_ms
            })
        except Exception as e:
            results.append({
                "scenario": case["scenario"],
                "error": str(e)
            })
    
    return {
        "decimal_preservation_tests": results,
        "summary": {
            "total_tests": len(whisper_test_cases),
            "successful": len([r for r in results if r.get("matches_expected", False)]),
            "failed": len([r for r in results if not r.get("matches_expected", False) and "error" not in r]),
            "phase_breakdown": {
                "phase0": "Preprocessing - handles accents, contractions, decimal preservation",
                "phase1": "Number conversion - all numbers become entityNumber", 
                "phase2": "Context matching - entityNumber becomes specific entities based on patterns"
            },
            "decimal_handling": {
                "input_format": "French comma decimals (1,50 euros)",
                "internal_format": "Period decimals (1.50)",
                "preservation": "Decimal structure maintained through all phases"
            }
        }
    }
    """Test the two-phase system with various scenarios"""
    test_cases = [
        {
            "scenario": "Complete age answer",
            "input": "J'ai 35 ans",
            "expected": ["entityAge"],
            "should_get": "jai entityAge"
        },
        {
            "scenario": "Incomplete age answer",
            "input": "J'ai 35", 
            "expected": ["entityAge"],
            "should_get": "jai entityNumber"  # No context to convert
        },
        {
            "scenario": "Age context question",
            "input": "35 ans",
            "expected": ["entityAge"],
            "should_get": "entityAge"
        },
        {
            "scenario": "Time with context",
            "input": "À 14h",
            "expected": ["entityTime"],
            "should_get": "a entityTime"
        },
        {
            "scenario": "Time without context",
            "input": "14",
            "expected": ["entityTime"],
            "should_get": "entityNumber"  # No clear time context
        },
        {
            "scenario": "Duration with context",
            "input": "Depuis 3 ans",
            "expected": ["entityPeriodOfTime"],
            "should_get": "depuis entityPeriodOfTime"
        },
        {
            "scenario": "Price with currency",
            "input": "15 euros",
            "expected": ["entityPrice"],
            "should_get": "entityPrice"
        },
        {
            "scenario": "Mixed entities",
            "input": "J'ai 25 ans et je travaille depuis 3 ans à Paris",
            "expected": ["entityAge", "entityPeriodOfTime", "entityCity"],
            "should_get": "jai entityAge et je travaille depuis entityPeriodOfTime a entityCity"
        }
    ]
    
    results = []
    for case in test_cases:
        try:
            request = TranscriptionAdjustRequest(
                original_transcript=case["input"],
                expected_entities=case["expected"]
            )
            result = await adjust_transcription_endpoint(request)
            
            results.append({
                "scenario": case["scenario"],
                "input": case["input"],
                "expected_entities": case["expected"],
                "phase1_result": result.phase1_result,
                "final_result": result.adjusted_transcript,
                "should_get": case["should_get"],
                "matches_expected": result.adjusted_transcript == case["should_get"],
                "entities_found": len(result.entities_found),
                "processing_time": result.processing_time_ms
            })
        except Exception as e:
            results.append({
                "scenario": case["scenario"],
                "error": str(e)
            })
    
    return {
        "test_results": results,
        "summary": {
            "total_tests": len(test_cases),
            "successful": len([r for r in results if r.get("matches_expected", False)]),
            "failed": len([r for r in results if not r.get("matches_expected", False) and "error" not in r])
        }
    }
