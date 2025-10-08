from pydantic import BaseModel, validator
from typing import List, Optional, Dict, Set
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

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
    entityTypeId: Optional[str] = None  # Simple text from lookup column
    airtableRecordId: str
    lastModifiedTimeRef: int
    createdAt: int
    live: bool = True
    
    @validator('entityTypeId')
    def clean_entity_type_id(cls, v):
        # Simple cleanup - just strip whitespace and handle empty strings
        if v is not None:
            v = str(v).strip()
            if len(v) == 0:
                return None
        return v


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


# ============================================================================
# Data Models and Enums
# ============================================================================

class UserState(Enum):
    """User journey state"""
    BRAND_NEW = "brand_new"
    EARLY_USER = "early_user"
    ACTIVE_USER = "active_user"
    RETURNING_USER = "returning_user"


@dataclass
class UserHistory:
    """Historical data about user's app usage"""
    user_id: str
    first_session_date: Optional[datetime]
    last_session_date: Optional[datetime]
    total_sessions: int
    days_since_first_session: int
    days_since_last_session: int
    last_session_level: Optional[int]
    state: UserState
    available_history_days: int
    streak7_days: int
    streak30_days: int


@dataclass
class InteractionCandidate:
    """Interaction with metadata for selection"""
    id: str
    subtopic_id: str
    intent_ids: List[str]
    boredom_rate: float
    is_entry_point: bool
    level_from: int
    combination: Optional[int] = None


class InsufficientInteractionsError(Exception):
    """Raised when cannot find enough interactions"""
    pass
    
