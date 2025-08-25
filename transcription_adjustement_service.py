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
                
                self.vocab_cache = {
                    'all_vocab': [],
                    'entitynumber_patterns': []  # For subprocess
                }
                
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
                
                self.cache_loaded = True
                logger.info(f"Loaded {len(self.vocab_cache['all_vocab'])} vocabulary entries")
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
        
        # Handle French contractions
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
        
        logger.info(f"Sorted vocabulary by priority - top 10 entries:")
        for i, entry in enumerate(sorted_vocab[:10]):
            logger.info(f"  {i+1}. '{entry['normalized_adjusted']}' ({entry['word_count']} words)")
        
        # Step 4: Track which parts of the text have been matched
        input_words = normalized_text.split()
        matched_positions = [False] * len(input_words)
        final_transcript_parts = ['vocabnotfound'] * len(input_words)
        
        # Step 5: Find matches using word boundaries to prevent partial matches
        for vocab_data in sorted_vocab:
            vocab_entry = vocab_data['original_entry']
            normalized_adjusted = vocab_data['normalized_adjusted']
            vocab_words = normalized_adjusted.split()
            
            # Look for this vocabulary sequence in the normalized text
            for i in range(len(input_words) - len(vocab_words) + 1):
                # CRITICAL: Check if ANY part of this span is already matched
                span_positions = list(range(i, i + len(vocab_words)))
                if any(matched_positions[pos] for pos in span_positions):
                    continue  # Skip this position - overlap detected
                
                # Check if words match exactly (word-by-word comparison)
                text_segment_words = input_words[i:i+len(vocab_words)]
                
                # Must match exactly word for word
                if text_segment_words == vocab_words:
                    text_segment = ' '.join(text_segment_words)
                    logger.info(f"MATCH FOUND: '{text_segment}' matches vocab '{normalized_adjusted}' at positions {span_positions}")
                    
                    # Mark ALL positions in this span as matched
                    for j in span_positions:
                        matched_positions[j] = True
                        # Use the original transcription_adjusted for the final transcript
                        final_transcript_parts[j] = vocab_entry['transcription_adjusted'] if j == i else None
                    
                    vocabulary_matches.append(VocabularyMatch(
                        id=vocab_entry['id'],
                        transcription_fr=vocab_entry['transcription_fr'],
                        transcription_adjusted=vocab_entry['transcription_adjusted']
                    ))
                    
                    # Add entity if it has one
                    if vocab_entry.get('entity_type_id'):
                        entity_matches.append(EntityMatch(
                            id=f"ENTI{vocab_entry['id'][4:]}",  # Convert VOCAB to ENTI
                            name=vocab_entry['entity_type_id'],
                            value=vocab_entry['transcription_adjusted']
                        ))
                    
                    # IMPORTANT: Break after first match to avoid multiple matches of the same phrase
                    break
        
        # Step 6: Build final transcript
        final_parts = [part for part in final_transcript_parts if part is not None]
        final_transcript = ' '.join(final_parts)
        
        logger.info(f"Phase 2 matching summary:")
        logger.info(f"  Input words: {input_words}")
        logger.info(f"  Matched positions: {matched_positions}")
        logger.info(f"  Final parts: {final_parts}")
        logger.info(f"  Final transcript: '{final_transcript}'")
        logger.info(f"  Vocabulary matches: {len(vocabulary_matches)}")
        
        return final_transcript, vocabulary_matches, entity_matches
    
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
        final_transcript, vocab_matches, entity_matches = self._phase2_entity_extraction(normalized)
        
        # Calculate processing time
        processing_time = round((datetime.now() - start_time).total_seconds() * 1000, 2)
        
        logger.info(f"Adjustment completed in {processing_time}ms")
        logger.info(f"Final result: '{original}' → '{final_transcript}'")
        
        return AdjustmentResult(
            original_transcript=original,
            pre_adjusted_transcript=pre_adjusted,
            adjusted_transcript=final_transcript,
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
