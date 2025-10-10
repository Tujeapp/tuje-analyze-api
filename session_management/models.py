# session_management/models.py
"""
Pydantic models for session management
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class SessionType(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    ARCHIVED = "archived"


class CycleStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"


class InteractionStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"


# Request Models
class CreateSessionRequest(BaseModel):
    user_id: str
    session_type: SessionType  # short, medium, long


class StartCycleRequest(BaseModel):
    session_id: str
    subtopic_id: str
    cycle_goal: str = "story"


class StartInteractionRequest(BaseModel):
    cycle_id: str
    brain_interaction_id: str


class SubmitAnswerRequest(BaseModel):
    interaction_id: str
    user_id: str
    original_transcript: str


# Response Models
class SessionResponse(BaseModel):
    id: str
    user_id: str
    session_type: str
    status: str
    expected_cycles: int
    completed_cycles: int
    total_score: int
    started_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class CycleResponse(BaseModel):
    id: str
    session_id: str
    cycle_number: int
    subtopic_id: Optional[str]
    status: str
    completed_interactions: int
    cycle_score: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class InteractionResponse(BaseModel):
    id: str
    cycle_id: str
    brain_interaction_id: str
    interaction_number: int
    status: str
    interaction_score: Optional[int]
    attempts_count: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class AnswerResponse(BaseModel):
    id: str
    interaction_id: str
    attempt_number: int
    original_transcript: str
    similarity_score: Optional[float]
    interaction_score: Optional[int]
    is_final_answer: bool
    processing_method: Optional[str]
    feedback: str
    
    class Config:
        from_attributes = True
