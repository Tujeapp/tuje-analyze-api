from pydantic import BaseModel, validator
from typing import List, Optional, Dict

# -------------------------------
# Vocabulary & Answer Models
# -------------------------------

class VocabularyEntry(BaseModel):
    phrase: str

class SavedAnswer(BaseModel):
    text: str
    is_correct: bool

class VocabEntry(BaseModel):
    id: str
    transcriptionFr: str
    transcriptionEn: str
    transcriptionAdjusted: str
    entityTypeId: Optional[str] = None  # NEW: Added entity type support
    airtableRecordId: str
    lastModifiedTimeRef: int
    createdAt: int
    live: bool = True
    
    @validator('entityTypeId')
    def validate_entity_type_id(cls, v):
        # Allow None/empty for vocab without entity types
        if v is not None and isinstance(v, str):
            v = v.strip()
            if len(v) == 0:
                return None
        return v
    
    class Config:
        # Allow field name variations
        allow_population_by_field_name = True


# -------------------------------
# Request Payload Models
# -------------------------------

class ScanVocabRequest(BaseModel):
    transcription: str
    vocabulary_phrases: List[str]

class ExtractOrderedRequest(BaseModel):
    transcription: str

class GPTFallbackRequest(BaseModel):
    transcription: str
    intent_options: List[str]
    matched_vocab: Optional[List[str]] = []
    candidate_answers: Optional[List[SavedAnswer]] = []

class IntentResponse(BaseModel):
    intent_topic: str
    confidence_score: Optional[int] = None
    intent_GPT: Optional[str] = None

# -------------------------------
# Response Models
# -------------------------------

class MatchResponse(BaseModel):
    matched_vocab: List[str]
    matched_entities: Dict[str, str]
    matches: List[Dict]
    call_gpt: bool
