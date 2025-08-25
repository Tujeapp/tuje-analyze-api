from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional, Tuple
import asyncpg
import re
import unicodedata
import logging
from datetime import datetime
import os

# Use the same pattern as your other files
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")

router = APIRouter()
logger = logging.getLogger(__name__)

class TranscriptionAdjustRequest(BaseModel):
    original_transcript: str
    user_id: Optional[str] = None
    interaction_id: Optional[str] = None

class VocabularyMatch(BaseModel):
    id: str
    transcription_fr: str
    transcription_adjusted: str

class EntityMatch(BaseModel):
    id: str
    name: str
    value: str

class AdjustmentResult(BaseModel):
    original_transcript: str
    pre_adjusted_transcript: str
    adjusted_transcript: str
    completed_transcript: str  # NEW: Phase 3 result
    list_of_vocabulary: List[VocabularyMatch]
    list_of_entities: List[EntityMatch]
    processing_time_ms: float

class TranscriptionAdjuster:
    def __init__(self):
        self.vocab_cache = {}
        self.cache_loaded = False
        
        # HARDCODED French numbers for pre-adjustment
        self.french_numbers = [
            # Basic numbers
            "zéro", "un", "une", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
            "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize", 
            "dix-sept", "dix-huit", "dix-neuf",
            # Tens
            "vingt", "trente", "quarante", "cinquante", "soixante", 
            "soixante-dix", "quatre-vingts", "quatre-vingt-dix",
            # Common compound numbers (examples)
            "vingt-et-un", "vingt-deux", "vingt-trois", "vingt-quatre", "vingt-cinq",
            "vingt-six", "vingt-sept", "vingt-huit", "vingt-neuf",
            "trente-et-un", "trente-deux", "trente-trois", "trente-quatre", "trente-cinq",
            "quarante-et-un", "quarante-deux", "quarante-trois", "quarante-quatre", "quarante-cinq",
            "cinquante-et-un", "cinquante-deux", "cinquante-trois", "cinquante-quatre", "cinquante-cinq",
            "soixante-et-un", "soixante-deux", "soixante-trois", "soixante-quatre", "soixante-cinq",
            "soixante-et-onze", "soixante-douze", "soixante-treize", "soixante-quatorze", "soixante-quinze",
            "quatre-vingt-un", "quatre-vingt-deux", "quatre-vingt-trois", "quatre-vingt-quatre", "quatre-vingt-cinq"
        ]
        
        # Sort by length (longest first) to handle compound numbers before simple ones
        self.french_numbers = sorted(self.french_numbers, key=len, reverse=True)
    
    async def load_vocab_cache(self, pool: asyncpg.Pool):
        """Load vocabulary from database for Phase 2"""
        if self.cache_loaded:
            return
            
        try:
            async with pool.acquire() as conn:
                # Load all vocabulary for Phase 2 matching
                rows = await conn.fetch("""
                    SELECT id, transcription_fr, transcription_en, transcription_adjusted, entity_type_id
                    FROM brain_vocab
                    WHERE live = TRUE
                    ORDER BY LENGTH(transcription_adjusted) DESC
                """)
                
                # Load all entities for Phase 3
                entity_rows = await conn.fetch("""
                    SELECT id, name
                    FROM brain_entity
                    WHERE live = TRUE
                """)
                
                self.vocab_cache = {
                    'all_vocab': [],
                    'entitynumber_patterns': [],  # For subprocess
                    'entities': {}  # NEW: Entity ID → name mapping
                }
                
                # Process vocabulary
                for row in rows:
                    vocab_entry = {
                        'id': row['id'],
                        'transcription_fr': row['transcription_fr'] or '',
                        'transcription_adjusted': row['transcription_adjusted'] or '',
                        'entity_type_id': row['entity_type_id']
                    }
                    self.vocab_cache['all_vocab'].append(vocab_entry)
                    
                    # Find patterns containing "entitynumber" for subprocess
                    if 'entitynumber' in str(row['transcription_fr'] or '').lower():
                        self.vocab_cache['entitynumber_patterns'].append(vocab_entry)
                
                # Process entities
                for entity_row in entity_rows:
                    self.vocab_cache['entities'][entity_row['id']] = entity_row['name']
                
                self.cache_loaded = True
                logger.info(f"Loaded {len(self.vocab_cache['all_vocab'])} vocabulary entries")
                logger.info(f"Loaded {len(self.vocab_cache['entities'])} entity definitions")
                logger.info(f"Found {len(self.vocab_cache['entitynumber_patterns'])} entitynumber patterns for subprocess")
                    
        except Exception as e:
            logger.error(f"Error loading vocabulary cache: {e}")
            raise
    
    def _normalize_basic(self, text: str) -> str:
        """Basic normalization: lowercase, remove accents"""
        if not text:
            return ""
        
        # Remove accents
        text = unicodedata.normalize('NFD', text)
        text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
        
        # Convert to lowercase
        text = text.lower()
        
        # Handle French contractions - FIXED: Don't add extra spaces
        contractions = {
            r"\bj'ai\b": "jai",      # FIXED: j'ai → jai (no space)
            r"\bj'": "jai ",         # j'aime → jai aime
            r"\bd'": "de ",          # d'accord → de accord  
            r"\bl'": "le ",          # l'école → le ecole
            r"\bc'est\b": "cest",    # c'est → cest (no space)
            r"\bc'": "ce ",          # c'était → ce etait
            r"\bqu'": "que ",        # qu'est → que est
            r"\bn'": "ne ",          # n'est → ne est
            r"\bt'": "te ",          # t'aime → te aime
            r"\bs'": "se ",          # s'appelle → se appelle
            r"\bm'": "me "           # m'appelle → me appelle
        }
        
        for pattern, replacement in contractions.items():
            text = re.sub(pattern, replacement, text)
        
        return text
    
    def _pre_adjustment_process(self, text: str) -> Tuple[str, bool]:
        """Pre-adjustment: Replace ALL numbers with entityNumber using hardcoded detection"""
        original_text = text
        result_text = text
        un_une_replaced = False
        
        # Step 1: Replace written French numbers (longest first)
        for french_number in self.french_numbers:
            pattern = r'\b' + re.escape(french_number) + r'\b'
            
            # Check if this number exists in the text
            matches = re.findall(pattern, result_text, re.IGNORECASE)
            if matches:
                # Track if we're replacing un/une
                if french_number.lower() in ['un', 'une']:
                    un_une_replaced = True
                
                # Count hyphens to determine how many entityNumbers to create
                hyphen_count = french_number.count('-')
                replacement = 'entityNumber' * (hyphen_count + 1)
                
                # Replace the number
                result_text = re.sub(pattern, replacement, result_text, flags=re.IGNORECASE)
                logger.info(f"Replaced '{french_number}' with '{replacement}'")
        
        # Step 2: Replace individual digits (each digit becomes entityNumber)
        digit_pattern = r'\b\d+\b'
        digit_matches = re.findall(digit_pattern, result_text)
        
        for digit_match in digit_matches:
            # Each digit becomes one entityNumber
            replacement = 'entityNumber' * len(digit_match)
            result_text = re.sub(r'\b' + re.escape(digit_match) + r'\b', replacement, result_text)
            logger.info(f"Replaced digit '{digit_match}' with '{replacement}'")
        
        # Step 3: Handle decimal numbers (like 1,50 or 1.50)
        decimal_pattern = r'\b\d+[.,]\d+\b'
        decimal_matches = re.findall(decimal_pattern, result_text)
        
        for decimal_match in decimal_matches:
            # Split on comma or period and convert each part
            parts = re.split(r'[.,]', decimal_match)
            replacement_parts = []
            for part in parts:
                replacement_parts.append('entityNumber' * len(part))
            replacement = ','.join(replacement_parts)
            
            result_text = re.sub(r'\b' + re.escape(decimal_match) + r'\b', replacement, result_text)
            logger.info(f"Replaced decimal '{decimal_match}' with '{replacement}'")
        
        logger.info(f"Pre-adjustment: '{original_text}' → '{result_text}'")
        logger.info(f"Un/une replaced: {un_une_replaced}")
        
        return result_text, un_une_replaced
    
    def _handle_un_une_subprocess(self, text: str, un_une_was_replaced: bool) -> str:
        """Subprocess: Decide if entityNumber from un/une should stay or revert"""
        if not un_une_was_replaced:
            return text
        
        logger.info("Triggering subprocess to handle un/une")
        
        words = text.split()
        result_words = []
        
        for i, word in enumerate(words):
            if word == 'entityNumber':
                # Get context around this entityNumber
                context_before = ' '.join(words[max(0, i-1):i]) if i > 0 else ''
                context_after = ' '.join(words[i+1:min(len(words), i+2)]) if i < len(words)-1 else ''
                
                # Create potential phrases to check in vocabulary
                potential_phrases = []
                if context_after:
                    potential_phrases.append(f"entityNumber {context_after}")
                if context_before:
                    potential_phrases.append(f"{context_before} entityNumber")
                if context_before and context_after:
                    potential_phrases.append(f"{context_before} entityNumber {context_after}")
                
                # Check if any of these phrases exist in entitynumber patterns
                found_in_vocab = False
                for phrase in potential_phrases:
                    for pattern_entry in self.vocab_cache.get('entitynumber_patterns', []):
                        if phrase.lower() in pattern_entry['transcription_fr'].lower():
                            found_in_vocab = True
                            logger.info(f"Found '{phrase}' in vocabulary, keeping as entityNumber")
                            break
                    if found_in_vocab:
                        break
                
                # Special case: "un peu" should almost always be an article
                if context_after.lower() == 'peu':
                    logger.info("Found 'entityNumber peu', reverting to 'un peu'")
                    result_words.append('un')
                elif found_in_vocab:
                    # Keep as entityNumber - it's likely a number
                    result_words.append(word)
                else:
                    # No vocabulary match found, likely an article
                    logger.info(f"No vocabulary match for entityNumber in context, reverting to 'un'")
                    result_words.append('un')
            else:
                result_words.append(word)
        
        result = ' '.join(result_words)
        logger.info(f"Subprocess result: '{text}' → '{result}'")
        return result
    
    def _phase1_normalization(self, text: str) -> str:
        """Phase 1: Normalization and entityNumber consolidation"""
        # Step 1: Normalize text
        normalized = self._normalize_basic(text)
        
        # Remove punctuation except commas in decimals
        normalized = re.sub(r'[^\w\s,]', ' ', normalized)
        
        # Step 2: Consolidate multiple consecutive entityNumbers
        # Handle decimal pattern first: entityNumber,entityNumber → entitynumber
        normalized = re.sub(r'entitynumber\s*,\s*entitynumber', 'entitynumber', normalized, flags=re.IGNORECASE)
        
        # Handle multiple consecutive entityNumbers: entityNumberentityNumber → entitynumber
        normalized = re.sub(r'(entitynumber)+', 'entitynumber', normalized, flags=re.IGNORECASE)
        
        # Normalize whitespace
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        logger.info(f"Phase 1 normalization: '{text}' → '{normalized}'")
        return normalized
    
    def _phase2_entity_extraction(self, text: str) -> Tuple[str, List[VocabularyMatch], List[EntityMatch]]:
        """Phase 2: Extract vocabulary and build final transcript"""
        vocabulary_matches = []
        entity_matches = []
        
        logger.info(f"Phase 2 input: '{text}'")
        
        # Step 1: Normalize the input text (lowercase, remove accents/symbols)
        normalized_text = self._normalize_basic(text)
        # Remove punctuation except spaces
        normalized_text = re.sub(r'[^\w\s]', ' ', normalized_text)
        # Normalize whitespace
        normalized_text = re.sub(r'\s+', ' ', normalized_text).strip()
        
        logger.info(f"Phase 2 normalized input: '{normalized_text}'")
        
        # Step 2: Get all vocabulary entries and normalize their transcription_adjusted
        all_vocab = self.vocab_cache.get('all_vocab', [])
        normalized_vocab = []
        
        for vocab_entry in all_vocab:
            if not vocab_entry.get('transcription_adjusted'):
                continue
                
            # Normalize the transcription_adjusted for comparison
            normalized_adjusted = self._normalize_basic(vocab_entry['transcription_adjusted'])
            normalized_adjusted = re.sub(r'[^\w\s]', ' ', normalized_adjusted)
            normalized_adjusted = re.sub(r'\s+', ' ', normalized_adjusted).strip()
            
            if normalized_adjusted:  # Only keep non-empty entries
                normalized_vocab.append({
                    'original_entry': vocab_entry,
                    'normalized_adjusted': normalized_adjusted,
                    'word_count': len(normalized_adjusted.split())
                })
        
        # Step 3: Sort by word count (longer phrases first), then by length of text
        sorted_vocab = sorted(normalized_vocab, 
                             key=lambda x: (x['word_count'], len(x['normalized_adjusted'])), 
                             reverse=True)
        
        logger.info(f"Sorted vocabulary by priority - entries containing 'jai' or 'ai':")
        for entry in sorted_vocab:
            if 'jai' in entry['normalized_adjusted'] or 'ai' in entry['normalized_adjusted']:
                logger.info(f"  - '{entry['normalized_adjusted']}' ({entry['word_count']} words) ID: {entry['original_entry']['id']}")
        
        # Step 4: Track which parts of the text have been matched
        input_words = normalized_text.split()
        matched_positions = [False] * len(input_words)
        final_transcript_parts = ['vocabnotfound'] * len(input_words)
        
        logger.info(f"Input words to match: {input_words}")
        logger.info(f"Initial matched positions: {matched_positions}")
        
        # Step 5: Find matches using word boundaries to prevent partial matches
        matches_with_positions = []  # Store matches with their positions
        
        for vocab_data in sorted_vocab:
            vocab_entry = vocab_data['original_entry']
            normalized_adjusted = vocab_data['normalized_adjusted']
            vocab_words = normalized_adjusted.split()
            
            # DEBUG: Log attempts for jai/ai entries
            if 'jai' in normalized_adjusted or 'ai' in normalized_adjusted:
                logger.info(f"TRYING TO MATCH: '{normalized_adjusted}' (words: {vocab_words})")
            
            # Look for this vocabulary sequence in the normalized text
            for i in range(len(input_words) - len(vocab_words) + 1):
                # CRITICAL: Check if ANY part of this span is already matched
                span_positions = list(range(i, i + len(vocab_words)))
                if any(matched_positions[pos] for pos in span_positions):
                    if 'jai' in normalized_adjusted or 'ai' in normalized_adjusted:
                        logger.info(f"  SKIPPED: positions {span_positions} already matched")
                    continue  # Skip this position - overlap detected
                
                # Check if words match exactly (word-by-word comparison)
                text_segment_words = input_words[i:i+len(vocab_words)]
                
                # DEBUG: Log comparison for jai/ai entries
                if 'jai' in normalized_adjusted or 'ai' in normalized_adjusted:
                    logger.info(f"  COMPARING: {text_segment_words} vs {vocab_words}")
                
                # Must match exactly word for word
                if text_segment_words == vocab_words:
                    text_segment = ' '.join(text_segment_words)
                    logger.info(f"MATCH FOUND: '{text_segment}' matches vocab '{normalized_adjusted}' at positions {span_positions}")
                    
                    # Mark ALL positions in this span as matched
                    for j in span_positions:
                        matched_positions[j] = True
                        # Use the original transcription_adjusted for the final transcript
                        final_transcript_parts[j] = vocab_entry['transcription_adjusted'] if j == i else None
                    
                    logger.info(f"Updated matched positions: {matched_positions}")
                    logger.info(f"Updated final parts: {final_transcript_parts}")
                    
                    # Store match with position for later sorting
                    matches_with_positions.append({
                        'position': i,
                        'vocab_match': VocabularyMatch(
                            id=vocab_entry['id'],
                            transcription_fr=vocab_entry['transcription_fr'],
                            transcription_adjusted=vocab_entry['transcription_adjusted']
                        ),
                        'entity_match': EntityMatch(
                            id=f"ENTI{vocab_entry['id'][4:]}",  # Convert VOCAB to ENTI
                            name=vocab_entry['entity_type_id'],
                            value=vocab_entry['transcription_adjusted']
                        ) if vocab_entry.get('entity_type_id') else None
                    })
                    
                    # IMPORTANT: Break after first match to avoid multiple matches of the same phrase
                    break
        
        # Step 6: Sort matches by position in transcript (left to right)
        matches_with_positions.sort(key=lambda x: x['position'])
        
        # Step 7: Extract sorted vocabulary and entity matches
        vocabulary_matches = [match['vocab_match'] for match in matches_with_positions]
        entity_matches = [match['entity_match'] for match in matches_with_positions if match['entity_match']]
        
        # Step 8: Build final transcript
        final_parts = [part for part in final_transcript_parts if part is not None]
        final_transcript = ' '.join(final_parts)
        
        # Step 9: Phase 3 - Build completed transcript with entity replacements
        completed_transcript, entity_list = self._phase3_entity_replacement(
            final_transcript, matches_with_positions, original
        )
        
        logger.info(f"Phase 2 matching summary:")
        logger.info(f"  Input words: {input_words}")
        logger.info(f"  Final matched positions: {matched_positions}")
        logger.info(f"  Final parts before joining: {final_parts}")
        logger.info(f"  Final transcript: '{final_transcript}'")
        logger.info(f"  Completed transcript: '{completed_transcript}'")
        logger.info(f"  Vocabulary matches: {len(vocabulary_matches)}")
        logger.info(f"  Entity matches: {len(entity_list)}")
        
        return final_transcript, vocabulary_matches, entity_list, completed_transcript
    
    def _phase3_entity_replacement(self, adjusted_transcript: str, matches_with_positions: List[Dict], pre_adjusted_transcript: str) -> Tuple[str, List[EntityMatch]]:
        """Phase 3: Replace vocabulary entries with entity names to create completed transcript"""
        logger.info(f"Phase 3 input: '{adjusted_transcript}'")
        logger.info(f"Original transcript reference: '{pre_adjusted_transcript}'")
        
        # Start with the adjusted transcript
        completed_transcript = adjusted_transcript
        entity_matches = []
        
        # Process matches in reverse order to maintain string positions when replacing
        sorted_matches = sorted(matches_with_positions, key=lambda x: x['position'], reverse=True)
        
        for match_data in sorted_matches:
            vocab_match = match_data['vocab_match']
            position = match_data['position']
            
            # Check if this vocabulary entry has an entity_type_id
            vocab_entry = None
            for entry in self.vocab_cache.get('all_vocab', []):
                if entry['id'] == vocab_match.id:
                    vocab_entry = entry
                    break
            
            if vocab_entry and vocab_entry.get('entity_type_id'):
                entity_type_id = vocab_entry['entity_type_id']
                logger.info(f"Found entity_type_id for vocab '{vocab_match.transcription_adjusted}': {entity_type_id}")
                
                # Get the actual entity name from cached entities using the entity_type_id
                entity_name = self.vocab_cache.get('entities', {}).get(entity_type_id)
                if entity_name:
                    entity_name_lower = entity_name.lower()
                    logger.info(f"Found entity name: {entity_name}")
                else:
                    # Fallback to entity_type_id if entity name not found in cache
                    entity_name_lower = entity_type_id.lower()
                    entity_name = entity_type_id
                    logger.warning(f"Entity name not found for {entity_type_id}, using fallback")
                
                # Find and replace the exact vocabulary text in the completed transcript
                old_text = vocab_match.transcription_adjusted
                completed_transcript = completed_transcript.replace(old_text, entity_name_lower, 1)
                
                # FIXED: Get the original text from pre-adjusted transcript
                original_value = self._get_original_value_for_entity(
                    vocab_match, pre_adjusted_transcript, old_text
                )
                
                # Use the actual entity_type_id as the entity ID
                entity_matches.append(EntityMatch(
                    id=entity_type_id,  # Use entity_type_id directly (e.g., "ENTI202408081621")
                    name=entity_name,   # Actual entity name from brain_entity table
                    value=original_value  # FIXED: Original text from pre-adjusted transcript
                ))
                
                logger.info(f"Replaced '{old_text}' with '{entity_name_lower}' in completed transcript")
                logger.info(f"Created entity match: ID={entity_type_id}, name={entity_name}, value='{original_value}'")
            else:
                logger.info(f"No entity found for vocab '{vocab_match.transcription_adjusted}' - keeping as is")
        
        # Sort entities by their appearance order (based on original position)
        if entity_matches:
            # Create a mapping of entity_type_id to position for sorting
            entity_id_to_position = {}
            for match_data in matches_with_positions:
                vocab_entry = None
                for entry in self.vocab_cache.get('all_vocab', []):
                    if entry['id'] == match_data['vocab_match'].id:
                        vocab_entry = entry
                        break
                if vocab_entry and vocab_entry.get('entity_type_id'):
                    entity_id_to_position[vocab_entry['entity_type_id']] = match_data['position']
            
            entity_matches.sort(key=lambda x: entity_id_to_position.get(x.id, 999))
        
        logger.info(f"Phase 3 result: '{adjusted_transcript}' → '{completed_transcript}'")
        logger.info(f"Entities found: {[(e.id, e.name, e.value) for e in entity_matches]}")
        
        return completed_transcript, entity_matches
    
    def _get_original_value_for_entity(self, vocab_match: VocabularyMatch, original_transcript: str, adjusted_value: str) -> str:
        """Extract the original text from original transcript for entity value"""
        
        # If the vocabulary transcription_fr contains "entityNumber", 
        # we need to find the original number words in the original transcript
        if "entityNumber" in vocab_match.transcription_fr:
            # This is a pattern like "entityNumber ans" 
            # We need to find what the original words were before any processing
            
            # Get the pattern parts (e.g., "entityNumber ans" → ["entityNumber", "ans"])
            pattern_parts = vocab_match.transcription_fr.split()
            
            if len(pattern_parts) >= 2 and pattern_parts[0] == "entityNumber":
                # Look for the pattern in original transcript
                # e.g., find "vingt ans" where "ans" matches the second part
                
                # Normalize the original transcript for searching
                normalized_original = self._normalize_basic(original_transcript)
                normalized_original = re.sub(r'[^\w\s]', ' ', normalized_original)
                normalized_original = re.sub(r'\s+', ' ', normalized_original).strip()
                
                words = normalized_original.split()
                remaining_pattern = [part.lower() for part in pattern_parts[1:]]  # ["ans"]
                
                # Find segments that end with the pattern
                for i in range(len(words) - len(remaining_pattern)):
                    # Check if this segment ends with our pattern
                    segment_end = words[i + 1:i + 1 + len(remaining_pattern)]
                    if [word.lower() for word in segment_end] == remaining_pattern:
                        # Found a match! The number word should be at position i
                        number_word = words[i]
                        full_segment = [number_word] + segment_end
                        original_segment = " ".join(full_segment)
                        logger.info(f"Found original value: '{original_segment}' for pattern '{vocab_match.transcription_fr}'")
                        return original_segment
            
            # If pattern matching fails, try to extract just the number part
            logger.warning(f"Could not find original pattern for '{vocab_match.transcription_fr}', using fallback")
            return vocab_match.transcription_fr.replace("entityNumber", "[number]")
        
        else:
            # For non-entityNumber vocabulary, return the original transcription_fr
            return vocab_match.transcription_fr
    
    async def adjust_transcription(self, request: TranscriptionAdjustRequest, pool: asyncpg.Pool) -> AdjustmentResult:
        """Main adjustment function following the 4-phase process"""
        start_time = datetime.now()
        
        # Load cache if needed
        await self.load_vocab_cache(pool)
        
        original = request.original_transcript
        logger.info(f"Starting adjustment for: '{original}'")
        
        # Phase 1: Pre-adjustment process (hardcoded number detection)
        pre_adjusted, un_une_replaced = self._pre_adjustment_process(original)
        
        # Subprocess: Handle un/une (only if un/une was replaced)
        pre_adjusted = self._handle_un_une_subprocess(pre_adjusted, un_une_replaced)
        
        # Phase 1: Normalization
        normalized = self._phase1_normalization(pre_adjusted)
        
        # Phase 2: Entity extraction
        final_transcript, vocab_matches, entity_matches, completed_transcript = self._phase2_entity_extraction(normalized)
        
        # Calculate processing time
        processing_time = round((datetime.now() - start_time).total_seconds() * 1000, 2)
        
        logger.info(f"Adjustment completed in {processing_time}ms")
        logger.info(f"Final result: '{original}' → '{final_transcript}'")
        
        return AdjustmentResult(
            original_transcript=original,
            pre_adjusted_transcript=pre_adjusted,
            adjusted_transcript=final_transcript,
            completed_transcript=completed_transcript,  # NEW: Phase 3 result
            list_of_vocabulary=vocab_matches,
            list_of_entities=entity_matches,
            processing_time_ms=processing_time
        )

# Global adjuster instance
adjuster = TranscriptionAdjuster()

@router.post("/adjust-transcription", response_model=AdjustmentResult)
async def adjust_transcription_endpoint(request: TranscriptionAdjustRequest):
    """API endpoint for transcription adjustment"""
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

@router.post("/test-adjustment-cases")
async def test_adjustment_cases():
    """Test the complete adjustment process with sample cases"""
    test_cases = [
        {
            "name": "Simple number word",
            "input": "J'ai vingt ans",
        },
        {
            "name": "Compound number",
            "input": "J'ai vingt-cinq ans",
        },
        {
            "name": "Un peu case (should revert)",
            "input": "J'aime un peu de café",
        },
        {
            "name": "Mixed numbers",
            "input": "Un café coûte 2 euros",
        },
        {
            "name": "Decimal numbers",
            "input": "Ça coûte 1,50 euros",
        }
    ]
    
    results = []
    for case in test_cases:
        try:
            request = TranscriptionAdjustRequest(original_transcript=case["input"])
            result = await adjust_transcription_endpoint(request)
            
            results.append({
                "test_name": case["name"],
                "input": case["input"],
                "pre_adjusted_result": result.pre_adjusted_transcript,
                "final_result": result.adjusted_transcript,
                "vocabulary_count": len(result.list_of_vocabulary),
                "entity_count": len(result.list_of_entities),
                "processing_time": result.processing_time_ms
            })
        except Exception as e:
            results.append({
                "test_name": case["name"],
                "error": str(e)
            })
    
    return {"test_results": results}
