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
    processing_time_ms: int

class TranscriptionAdjuster:
    def __init__(self):
        self.vocab_cache = {}
        self.cache_loaded = False
    
    async def load_vocab_cache(self, pool: asyncpg.Pool):
        """Load vocabulary from database"""
        if self.cache_loaded:
            return
            
        try:
            async with pool.acquire() as conn:
                # Load all vocabulary
                rows = await conn.fetch("""
                    SELECT id, transcription_fr, transcription_en, transcription_adjusted, entity_type_id
                    FROM brain_vocab
                    WHERE live = TRUE
                    ORDER BY LENGTH(transcription_adjusted) DESC
                """)
                
                self.vocab_cache = {
                    'all_vocab': [],
                    'number_words': [],
                    'number_digits': []
                }
                
                for row in rows:
                    vocab_entry = {
                        'id': row['id'],
                        'transcription_fr': row['transcription_fr'] or '',
                        'transcription_adjusted': row['transcription_adjusted'] or '',
                        'entity_type_id': row['entity_type_id']
                    }
                    self.vocab_cache['all_vocab'].append(vocab_entry)
                    
                    # Separate number-related entries
                    if row['entity_type_id'] == 'entityNumber':
                        if re.match(r'^\d+$', str(row['transcription_fr'])):
                            self.vocab_cache['number_digits'].append(vocab_entry)
                        else:
                            self.vocab_cache['number_words'].append(vocab_entry)
                
                self.cache_loaded = True
                logger.info(f"Loaded {len(self.vocab_cache['all_vocab'])} vocabulary entries")
                    
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
        """Phase 1: Pre-adjustment - Replace numbers with entityNumber"""
        original_text = text
        result_text = text
        
        # Check if we should trigger pre-adjustment
        has_numbers = bool(re.search(r'\d', text))
        has_un_une = bool(re.search(r'\b(un|une)\b', text, re.IGNORECASE))
        
        if not has_numbers and not has_un_une:
            return text, False
        
        # Replace written numbers first (from vocabulary - longer patterns)
        for vocab_entry in self.vocab_cache.get('number_words', []):
            if vocab_entry['transcription_fr']:
                pattern = r'\b' + re.escape(vocab_entry['transcription_fr']) + r'\b'
                result_text = re.sub(pattern, 'entityNumber', result_text, flags=re.IGNORECASE)
        
        # Replace digit numbers (from vocabulary)
        for vocab_entry in self.vocab_cache.get('number_digits', []):
            if vocab_entry['transcription_fr']:
                pattern = r'\b' + re.escape(vocab_entry['transcription_fr']) + r'\b'
                result_text = re.sub(pattern, 'entityNumber', result_text)
        
        # Replace standalone digits and decimal patterns (not in vocabulary)
        result_text = re.sub(r'\b\d+\b', 'entityNumber', result_text)
        result_text = re.sub(r'\b\d+[.,]\d+\b', 'entityNumber,entityNumber', result_text)
        
        # Replace un/une with entityNumber
        result_text = re.sub(r'\b(un|une)\b', 'entityNumber', result_text, flags=re.IGNORECASE)
        
        return result_text, result_text != original_text
    
    def _handle_un_une_subprocess(self, text: str, pre_adjustment_happened: bool) -> str:
        """Subprocess to handle 'un/une' - determine if it should be number or article"""
        if not pre_adjustment_happened:
            return text
        
        # Simple implementation: check if entityNumber patterns exist in vocabulary
        words = text.split()
        result_words = []
        
        for i, word in enumerate(words):
            if word.lower() == 'entitynumber':
                # Get context around this position
                context_after = ' '.join(words[i+1:min(len(words), i+2)])
                
                # Simple rule: if followed by "peu", it's likely "un peu" (article)
                if 'peu' in context_after.lower():
                    result_words.append('un')
                else:
                    result_words.append(word)
            else:
                result_words.append(word)
        
        return ' '.join(result_words)
    
    def _phase1_normalization(self, text: str) -> str:
        """Phase 1: Normalization and entityNumber consolidation"""
        # Step 1: Normalize text
        normalized = self._normalize_basic(text)
        
        # Remove punctuation except commas in decimals
        normalized = re.sub(r'[^\w\s,]', ' ', normalized)
        
        # Step 2: Consolidate multiple entityNumbers
        # Handle decimal pattern first
        normalized = re.sub(r'entitynumber\s*,\s*entitynumber', 'entitynumber', normalized, flags=re.IGNORECASE)
        
        # Handle multiple consecutive entityNumbers
        normalized = re.sub(r'(entitynumber\s*)+', 'entitynumber ', normalized, flags=re.IGNORECASE)
        
        # Normalize whitespace
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized
    
    def _phase2_entity_extraction(self, text: str) -> Tuple[str, List[VocabularyMatch], List[EntityMatch]]:
        """Phase 2: Extract vocabulary and build final transcript"""
        vocabulary_matches = []
        entity_matches = []
        
        # Get all vocabulary entries, sorted by length (longest first)
        all_vocab = self.vocab_cache.get('all_vocab', [])
        sorted_vocab = sorted(all_vocab, 
                            key=lambda x: len(x['transcription_adjusted'].split()) if x['transcription_adjusted'] else 0, 
                            reverse=True)
        
        # Track which parts of the text have been matched
        words = text.split()
        matched_positions = [False] * len(words)
        final_transcript_parts = ['vocabnotfound'] * len(words)
        
        # Find matches, prioritizing longer phrases
        for vocab_entry in sorted_vocab:
            if not vocab_entry.get('transcription_adjusted'):
                continue
                
            vocab_text = vocab_entry['transcription_adjusted'].strip()
            if not vocab_text:
                continue
                
            vocab_words = vocab_text.split()
            
            # Look for this vocabulary sequence in the text
            for i in range(len(words) - len(vocab_words) + 1):
                # Check if this span is already matched
                if any(matched_positions[i:i+len(vocab_words)]):
                    continue
                
                # Check if words match
                text_segment = ' '.join(words[i:i+len(vocab_words)])
                if text_segment.lower() == vocab_text.lower():
                    # Mark positions as matched
                    for j in range(i, i + len(vocab_words)):
                        matched_positions[j] = True
                        final_transcript_parts[j] = vocab_text if j == i else None
                    
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
                    
                    break
        
        # Build final transcript
        final_parts = [part for part in final_transcript_parts if part is not None]
        final_transcript = ' '.join(final_parts)
        
        return final_transcript, vocabulary_matches, entity_matches
    
    async def adjust_transcription(self, request: TranscriptionAdjustRequest, pool: asyncpg.Pool) -> AdjustmentResult:
        """Main adjustment function following the 4-phase process"""
        start_time = datetime.now()
        
        # Load cache if needed
        await self.load_vocab_cache(pool)
        
        original = request.original_transcript
        
        # Phase 1: Pre-adjustment process
        pre_adjusted, pre_adjustment_happened = self._pre_adjustment_process(original)
        
        # Subprocess: Handle un/une
        pre_adjusted = self._handle_un_une_subprocess(pre_adjusted, pre_adjustment_happened)
        
        # Phase 1: Normalization
        normalized = self._phase1_normalization(pre_adjusted)
        
        # Phase 2: Entity extraction
        final_transcript, vocab_matches, entity_matches = self._phase2_entity_extraction(normalized)
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        logger.info(f"Adjustment completed in {processing_time:.2f}ms")
        logger.info(f"Original: '{original}'")
        logger.info(f"Pre-adjusted: '{pre_adjusted}'")
        logger.info(f"Final: '{final_transcript}'")
        logger.info(f"Vocabulary matches: {len(vocab_matches)}")
        logger.info(f"Entity matches: {len(entity_matches)}")
        
        return AdjustmentResult(
            original_transcript=original,
            pre_adjusted_transcript=pre_adjusted,
            adjusted_transcript=final_transcript,
            list_of_vocabulary=vocab_matches,
            list_of_entities=entity_matches,
            processing_time_ms=round(processing_time, 2)
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
            "name": "Simple case without numbers",
            "input": "J'aime boire du café à Paris",
            "expected_pre": "J'aime boire du café à Paris",
            "expected_final": "jaime boire entitybeverage entitycity"
        },
        {
            "name": "Numbers with un/une",
            "input": "Un café coûte deux euros à Paris",
            "expected_pre": "entityNumber café coûte entityNumber euros à Paris",
            "expected_final": "entitybeverage coute entityprice entitycity"
        },
        {
            "name": "Un peu case (article, not number)",
            "input": "J'aime boire un peu de café à Paris",
            "expected_pre": "J'aime boire un peu de café à Paris",
            "expected_final": "jaime boire un peu de entitybeverage entitycity"
        },
        {
            "name": "Decimal numbers",
            "input": "Ça coûte 1,50 euros",
            "expected_pre": "Ça coûte entityNumber,entityNumber euros",
            "expected_final": "ca coute entityprice"
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
                "expected_pre": case["expected_pre"],
                "expected_final": case["expected_final"],
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
