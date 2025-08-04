from pydantic import BaseModel
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
    airtableRecordId: str
    lastModifiedTimeRef: int


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
