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
    normalized_transcript: str
    phase1_result: str  # After number conversion
    adjusted_transcript: str  # Final result
    entities_found: List[EntityMatch]
    processing_time_ms: int

class TwoPhaseTranscriptionAdjuster:
    def __init__(self):
        self.non_number_entities = {}  # Cache for non-number entities
        self.number_patterns = {}      # Cache for number patterns
        self.context_rules = {}        # Rules for phase 2 conversion
        self.cache_loaded = False
    
    async def load_entities_cache(self, pool: asyncpg.Pool):
        """Load entities and number patterns from database"""
        if self.cache_loaded:
            return
            
        try:
            async with pool.acquire() as conn:
                # Load non-number entities (for phase 1)
                rows = await conn.fetch("""
                    SELECT 
                        bv.transcription_fr,
                        bv.transcription_adjusted, 
                        bv.entity_type_id,
                        bet.priority as type_priority,
                        bv.entity_priority
                    FROM brain_vocab bv
                    JOIN brain_entity_type bet ON bv.entity_type_id = bet.id
                    WHERE bv.entity_type_id != 'entityNumber'
                    AND bv.entity_type_id IS NOT NULL
                    ORDER BY 
                        bet.priority DESC, 
                        bv.entity_priority DESC,
                        LENGTH(bv.transcription_fr) DESC
                """)
                
                self.non_number_entities = {'entities': []}
                
                for row in rows:
                    entity_data = {
                        'original_text': row['transcription_fr'],
                        'normalized_text': self._normalize_text(row['transcription_fr']),
                        'entity_type': row['entity_type_id'],
                        'type_priority': row['type_priority'],
                        'entity_priority': row['entity_priority'] or 0
                    }
                    self.non_number_entities['entities'].append(entity_data)
                
                # Load number patterns (for phase 1)
                number_rows = await conn.fetch("""
                    SELECT transcription_fr, transcription_adjusted
                    FROM brain_vocab bv
                    WHERE entity_type_id = 'entityNumber'
                    ORDER BY LENGTH(transcription_fr) DESC
                """)
                
                self.number_patterns = {
                    'written_numbers': [],  # un, deux, trois, etc.
                    'digit_patterns': []    # 1, 2, 3, etc.
                }
                
                for row in number_rows:
                    normalized = self._normalize_text(row['transcription_fr'])
                    self.number_patterns['written_numbers'].append(normalized)
                
                # Add digit patterns
                self.number_patterns['digit_patterns'] = [
                    r'\b\d+\b',  # Any sequence of digits
                    r'\b\d+h\d*\b',  # Time patterns like 14h, 14h30
                    r'\b\d+[.,]\d+\b'  # Decimal numbers
                ]
                
                # Set up context rules for phase 2
                self._setup_context_rules()
                
                self.cache_loaded = True
                logger.info(f"Loaded {len(self.non_number_entities['entities'])} non-number entities")
                logger.info(f"Loaded {len(self.number_patterns['written_numbers'])} written number patterns")
                    
        except Exception as e:
            logger.error(f"Error loading entities cache: {e}")
            raise
    
    def _setup_context_rules(self):
        """Define rules for phase 2 entityNumber → specific entity conversion"""
        self.context_rules = {
            'entityAge': {
                'patterns': [
                    r'entityNumber\s+ans?\b',           # "entityNumber ans"
                    r'\b(age|ages?|vieux|jeune)\b.*entityNumber',  # context words before
                    r'entityNumber.*\b(age|ages?|vieux|jeune)\b',  # context words after
                    r'\b(jai|ai)\s+entityNumber\b'     # "j'ai entityNumber" in age context
                ],
                'context_phrases': [
                    'quel age', 'ton age', 'votre age', 'mon age', 'ans', 'annees',
                    'ne en', 'naissance', 'anniversaire'
                ]
            },
            'entityTime': {
                'patterns': [
                    r'entityNumber\s*h(?:eures?)?\b',              # "entityNumber h"
                    r'\b(a|vers|depuis|jusqu)\s+entityNumber\b',  # "à entityNumber"
                    r'entityNumber\s+(heures?|h\d+)\b'            # "entityNumber heures"
                ],
                'context_phrases': [
                    'quelle heure', 'a quelle heure', 'vers', 'depuis', 'jusqua',
                    'matin', 'soir', 'apres-midi', 'midi', 'minuit'
                ]
            },
            'entityPeriodOfTime': {
                'patterns': [
                    r'entityNumber\s+(ans?|annees?|mois|jours?|semaines?|heures?)\b',  # "entityNumber ans"
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
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text by removing accents, converting to lowercase, handling contractions"""
        if not text:
            return ""
            
        # Remove accents
        text = unicodedata.normalize('NFD', text)
        text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
        
        # Convert to lowercase
        text = text.lower()
        
        # Handle French contractions and articles
        contractions = {
            r"\bj'": "jai ",
            r"\bd'": "de ",
            r"\bl'": "le ",
            r"\bc'": "ce ",
            r"\bqu'": "que ",
            r"\bn'": "ne ",
            r"\bt'": "te ",
            r"\bs'": "se ",
            r"\bm'": "me "
        }
        
        for pattern, replacement in contractions.items():
            text = re.sub(pattern, replacement, text)
        
        # Remove punctuation but keep spaces
        text = re.sub(r'[^\w\s]', ' ', text)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def _phase1_convert_numbers(self, text: str) -> Tuple[str, List[EntityMatch]]:
        """Phase 1: Convert all numbers to entityNumber"""
        phase1_matches = []
        result_text = text
        
        # Process written numbers first (longer matches)
        for written_number in self.number_patterns['written_numbers']:
            pattern = r'\b' + re.escape(written_number) + r'\b'
            matches = list(re.finditer(pattern, result_text))
            
            # Process matches in reverse order to maintain positions
            for match in reversed(matches):
                phase1_matches.append(EntityMatch(
                    original_text=match.group(),
                    entity_replacement='entityNumber',
                    entity_type='entityNumber',
                    start_pos=match.start(),
                    end_pos=match.end(),
                    confidence=0.95,
                    source='written_number',
                    phase=1
                ))
                
                # Replace in text
                result_text = (result_text[:match.start()] + 
                             'entityNumber' + 
                             result_text[match.end():])
        
        # Then process digit patterns
        for digit_pattern in self.number_patterns['digit_patterns']:
            matches = list(re.finditer(digit_pattern, result_text))
            
            # Process matches in reverse order to maintain positions
            for match in reversed(matches):
                # Skip if this position was already replaced
                if 'entityNumber' in result_text[match.start():match.end()]:
                    continue
                    
                phase1_matches.append(EntityMatch(
                    original_text=match.group(),
                    entity_replacement='entityNumber',
                    entity_type='entityNumber',
                    start_pos=match.start(),
                    end_pos=match.end(),
                    confidence=0.95,
                    source='digit_pattern',
                    phase=1
                ))
                
                # Replace in text
                result_text = (result_text[:match.start()] + 
                             'entityNumber' + 
                             result_text[match.end():])
        
        return result_text, phase1_matches
    
    def _phase2_contextualize_numbers(self, text: str, expected_entities: Optional[List[str]] = None) -> Tuple[str, List[EntityMatch]]:
        """Phase 2: Convert entityNumber to specific entities based on context"""
        if 'entityNumber' not in text:
            return text, []
        
        phase2_matches = []
        result_text = text
        
        # Determine which entity types to check
        entity_types_to_check = expected_entities if expected_entities else list(self.context_rules.keys())
        
        # Sort by priority if expected entities are provided
        if expected_entities:
            # Check expected entities first
            priority_order = expected_entities + [et for et in self.context_rules.keys() if et not in expected_entities]
        else:
            priority_order = list(self.context_rules.keys())
        
        # Find entityNumber positions
        entity_number_positions = []
        for match in re.finditer(r'\bentityNumber\b', result_text):
            entity_number_positions.append((match.start(), match.end()))
        
        # Process each entityNumber position
        for start_pos, end_pos in entity_number_positions:
            best_match = None
            best_confidence = 0
            
            # Check each entity type
            for entity_type in priority_order:
                if entity_type not in self.context_rules:
                    continue
                    
                rule = self.context_rules[entity_type]
                confidence = 0
                
                # Check patterns
                for pattern in rule['patterns']:
                    if re.search(pattern, result_text):
                        confidence += 0.4
                        logger.info(f"Pattern matched for {entity_type}: {pattern}")
                
                # Check context phrases in surrounding text (±20 characters)
                context_start = max(0, start_pos - 20)
                context_end = min(len(result_text), end_pos + 20)
                context_text = result_text[context_start:context_end]
                
                for phrase in rule['context_phrases']:
                    if phrase in context_text:
                        confidence += 0.3
                        logger.info(f"Context phrase matched for {entity_type}: {phrase}")
                
                # Boost confidence for expected entities
                if expected_entities and entity_type in expected_entities:
                    confidence += 0.2
                    logger.info(f"Expected entity boost for {entity_type}")
                
                # Track best match
                if confidence > best_confidence and confidence > 0.5:  # Minimum threshold
                    best_confidence = confidence
                    best_match = {
                        'entity_type': entity_type,
                        'confidence': min(confidence, 0.95)  # Cap at 95%
                    }
            
            # Apply best match if found
            if best_match:
                phase2_matches.append(EntityMatch(
                    original_text='entityNumber',
                    entity_replacement=best_match['entity_type'],
                    entity_type=best_match['entity_type'],
                    start_pos=start_pos,
                    end_pos=end_pos,
                    confidence=best_match['confidence'],
                    source='context_analysis',
                    phase=2
                ))
                
                # Replace in text
                result_text = (result_text[:start_pos] + 
                             best_match['entity_type'] + 
                             result_text[end_pos:])
                
                logger.info(f"Phase 2: entityNumber -> {best_match['entity_type']} (confidence: {best_match['confidence']:.2f})")
        
        return result_text, phase2_matches
    
    def _find_non_number_entities(self, text: str, expected_entities: Optional[List[str]] = None) -> List[EntityMatch]:
        """Find non-number entities in the text"""
        matches = []
        
        # Filter entities if expected_entities provided
        entities_to_search = self.non_number_entities['entities']
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
        """Main two-phase adjustment function"""
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
        
        # Normalize the original transcript
        normalized_text = self._normalize_text(request.original_transcript)
        
        # Phase 1: Convert all numbers to entityNumber + find non-number entities
        phase1_text, number_matches = self._phase1_convert_numbers(normalized_text)
        non_number_matches = self._find_non_number_entities(phase1_text, expected_entities)
        
        # Apply non-number entity replacements to phase1 text
        # Sort by position in reverse order to maintain positions
        sorted_non_number = sorted(non_number_matches, key=lambda x: x.start_pos, reverse=True)
        for match in sorted_non_number:
            phase1_text = (phase1_text[:match.start_pos] + 
                          match.entity_replacement + 
                          phase1_text[match.end_pos:])
        
        # Phase 2: Contextualize entityNumber → specific entities
        final_text, context_matches = self._phase2_contextualize_numbers(phase1_text, expected_entities)
        
        # Combine all matches
        all_matches = number_matches + non_number_matches + context_matches
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        logger.info(f"Two-phase adjustment completed in {processing_time:.2f}ms")
        logger.info(f"Original: '{request.original_transcript}'")
        logger.info(f"Normalized: '{normalized_text}'")
        logger.info(f"Phase 1 (numbers): '{phase1_text}'")
        logger.info(f"Final: '{final_text}'")
        logger.info(f"Expected entities: {expected_entities}")
        logger.info(f"Total entities found: {len(all_matches)}")
        
        return AdjustmentResult(
            original_transcript=request.original_transcript,
            normalized_transcript=normalized_text,
            phase1_result=phase1_text,
            adjusted_transcript=final_text,
            entities_found=all_matches,
            processing_time_ms=round(processing_time, 2)
        )

# Global adjuster instance
adjuster = TwoPhaseTranscriptionAdjuster()

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

@router.post("/test-two-phase")
async def test_two_phase():
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
