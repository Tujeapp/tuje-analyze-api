# bubble_integration_router.py - 3 SEPARATE ENDPOINTS
"""
Bubble.io-optimized endpoints for TuJe French learning API
3 independent endpoints for maximum flexibility in Bubble workflows
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator
from typing import Optional, List, Dict, Any
import logging
import time
import asyncpg
import os
from datetime import datetime

# Import your existing services
from adjustement_models import adjust_transcription_endpoint
from matching_answer_router import match_completed_transcript
from gpt_fallback_router import analyze_original_transcript_intent

# Import types
from adjustement_types import TranscriptionAdjustRequest
from matching_answer_types import MatchAnswerRequest
from gpt_fallback_types import GPTFallbackRequest

logger = logging.getLogger(__name__)
router = APIRouter()

# -------------------------
# 1. TRANSCRIPTION ADJUSTMENT ENDPOINT
# -------------------------
class BubbleAdjustmentRequest(BaseModel):
    """Bubble-optimized transcription adjustment request"""
    interaction_id: str
    original_transcript: str
    user_id: Optional[str] = None
    
    @validator('original_transcript')
    def validate_transcript(cls, v):
        if not v or not v.strip():
            raise ValueError("Original transcript cannot be empty")
        if len(v) > 1000:
            raise ValueError("Transcript too long (max 1000 characters)")
        return v.strip()

class BubbleAdjustmentResponse(BaseModel):
    """Bubble-friendly adjustment response"""
    success: bool
    processing_time_ms: float
    timestamp: str
    
    # Input echo
    interaction_id: str
    original_transcript: str
    
    # Adjustment results
    pre_adjusted_transcript: str
    adjusted_transcript: str
    completed_transcript: str
    
    # Vocabulary and entities found
    vocabulary_found: List[Dict]
    entities_found: List[Dict]
    
    # Analysis metrics
    vocabnotfound_count: int
    vocabulary_count: int
    entities_count: int
    
    # Triggers for next steps
    suggest_gpt_fallback: bool = False  # True if many vocabnotfound
    quality_score: str = "good"  # "excellent", "good", "poor"
    
    # Error handling
    error: Optional[str] = None

@router.post("/bubble-adjust-transcript", response_model=BubbleAdjustmentResponse)
async def bubble_transcription_adjustment(request: BubbleAdjustmentRequest):
    """
    🔧 ENDPOINT 1: TRANSCRIPTION ADJUSTMENT
    
    Takes raw user transcript and applies:
    - Number detection and replacement
    - French contractions handling
    - Vocabulary extraction
    - Entity detection
    
    Perfect for: Initial processing of user speech recognition
    """
    start_time = time.time()
    
    try:
        logger.info(f"🔧 Bubble adjustment: {request.interaction_id} - '{request.original_transcript}'")
        
        # Call your existing adjustment service
        adj_request = TranscriptionAdjustRequest(
            original_transcript=request.original_transcript,
            user_id=request.user_id,
            interaction_id=request.interaction_id
        )
        
        adj_result = await adjust_transcription_endpoint(adj_request)
        
        # Process results for Bubble
        vocabulary_found = [v.dict() for v in adj_result.list_of_vocabulary]
        entities_found = [e.dict() for e in adj_result.list_of_entities]
        
        # Count vocabnotfound entries
        vocabnotfound_count = sum(
            1 for vocab in vocabulary_found 
            if vocab.get('transcription_adjusted') == 'vocabnotfound'
        )
        
        # Determine quality and suggestions
        total_words = len(request.original_transcript.split())
        suggest_gpt = vocabnotfound_count >= 3 or (vocabnotfound_count / max(total_words, 1)) > 0.4
        
        if vocabnotfound_count == 0:
            quality_score = "excellent"
        elif vocabnotfound_count <= 2:
            quality_score = "good"
        else:
            quality_score = "poor"
        
        processing_time = round((time.time() - start_time) * 1000, 2)
        
        logger.info(f"✅ Adjustment complete: quality={quality_score}, "
                   f"vocabnotfound={vocabnotfound_count}, suggest_gpt={suggest_gpt}")
        
        return BubbleAdjustmentResponse(
            success=True,
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
            interaction_id=request.interaction_id,
            original_transcript=request.original_transcript,
            pre_adjusted_transcript=adj_result.pre_adjusted_transcript,
            adjusted_transcript=adj_result.adjusted_transcript,
            completed_transcript=adj_result.completed_transcript,
            vocabulary_found=vocabulary_found,
            entities_found=entities_found,
            vocabnotfound_count=vocabnotfound_count,
            vocabulary_count=len(vocabulary_found),
            entities_count=len(entities_found),
            suggest_gpt_fallback=suggest_gpt,
            quality_score=quality_score
        )
        
    except Exception as e:
        processing_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"❌ Bubble adjustment failed: {e}")
        
        return BubbleAdjustmentResponse(
            success=False,
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
            interaction_id=request.interaction_id,
            original_transcript=request.original_transcript,
            pre_adjusted_transcript=request.original_transcript,
            adjusted_transcript=request.original_transcript.lower(),
            completed_transcript=request.original_transcript.lower(),
            vocabulary_found=[],
            entities_found=[],
            vocabnotfound_count=0,
            vocabulary_count=0,
            entities_count=0,
            error=str(e)
        )

# -------------------------
# 2. ANSWER MATCHING ENDPOINT
# -------------------------
class BubbleMatchingRequest(BaseModel):
    """Bubble-optimized answer matching request"""
    interaction_id: str
    completed_transcript: str  # From adjustment endpoint
    threshold: int = 85
    user_id: Optional[str] = None
    
    @validator('completed_transcript')
    def validate_transcript(cls, v):
        if not v or not v.strip():
            raise ValueError("Completed transcript cannot be empty")
        if len(v) > 500:
            raise ValueError("Completed transcript too long (max 500 characters)")
        return v.strip()
    
    @validator('threshold')
    def validate_threshold(cls, v):
        if v < 0 or v > 100:
            raise ValueError("Threshold must be between 0 and 100")
        return v

class BubbleMatchingResponse(BaseModel):
    """Bubble-friendly matching response"""
    success: bool
    processing_time_ms: float
    timestamp: str
    
    # Input echo
    interaction_id: str
    completed_transcript: str
    threshold: int
    
    # Matching results
    match_found: bool
    matched_answer_id: Optional[str] = None
    similarity_score: Optional[float] = None
    expected_answer: Optional[str] = None
    
    # Answer details (if match found)
    answer_french: Optional[str] = None
    answer_english: Optional[str] = None
    
    # Analysis for next steps
    suggest_gpt_fallback: bool = False  # True if no match or low score
    match_quality: str = "none"  # "excellent", "good", "fair", "none"
    
    # Error handling
    reason: Optional[str] = None
    error: Optional[str] = None

@router.post("/bubble-match-answer", response_model=BubbleMatchingResponse)
async def bubble_answer_matching(request: BubbleMatchingRequest):
    """
    🔍 ENDPOINT 2: ANSWER MATCHING
    
    Takes completed transcript (from adjustment) and matches against expected answers:
    - Fuzzy string matching
    - Returns best match above threshold
    - Provides match quality assessment
    
    Perfect for: Checking if user response matches expected answers
    """
    start_time = time.time()
    
    try:
        logger.info(f"🔍 Bubble matching: {request.interaction_id} - '{request.completed_transcript}' (threshold: {request.threshold}%)")
        
        # Call your existing matching service
        match_request = MatchAnswerRequest(
            interaction_id=request.interaction_id,
            completed_transcript=request.completed_transcript,
            threshold=request.threshold,
            user_id=request.user_id
        )
        
        match_result = await match_completed_transcript(match_request)
        
        # Determine match quality and suggestions
        match_quality = "none"
        suggest_gpt = True
        
        if match_result.match_found and match_result.similarity_score:
            score = match_result.similarity_score
            suggest_gpt = False
            
            if score >= 90:
                match_quality = "excellent"
            elif score >= 80:
                match_quality = "good"
            elif score >= request.threshold:
                match_quality = "fair"
                suggest_gpt = True  # Fair matches might need GPT confirmation
        else:
            suggest_gpt = True
        
        processing_time = round((time.time() - start_time) * 1000, 2)
        
        logger.info(f"🎯 Matching result: found={match_result.match_found}, "
                   f"score={match_result.similarity_score}, quality={match_quality}")
        
        return BubbleMatchingResponse(
            success=True,
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
            interaction_id=request.interaction_id,
            completed_transcript=request.completed_transcript,
            threshold=request.threshold,
            match_found=match_result.match_found,
            matched_answer_id=match_result.answer_id,
            similarity_score=match_result.similarity_score,
            expected_answer=match_result.expected_transcript,
            answer_french=match_result.answer_details.transcription_fr if match_result.answer_details else None,
            answer_english=match_result.answer_details.transcription_en if match_result.answer_details else None,
            suggest_gpt_fallback=suggest_gpt,
            match_quality=match_quality,
            reason=match_result.reason
        )
        
    except Exception as e:
        processing_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"❌ Bubble matching failed: {e}")
        
        return BubbleMatchingResponse(
            success=False,
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
            interaction_id=request.interaction_id,
            completed_transcript=request.completed_transcript,
            threshold=request.threshold,
            match_found=False,
            suggest_gpt_fallback=True,
            match_quality="none",
            error=str(e)
        )

# -------------------------
# 3. GPT FALLBACK ENDPOINT
# -------------------------
class BubbleGPTRequest(BaseModel):
    """Bubble-optimized GPT fallback request"""
    interaction_id: str
    original_transcript: str  # Use original, not adjusted, for intent detection
    threshold: int = 70
    user_id: Optional[str] = None
    custom_intent_ids: Optional[List[str]] = None  # Override interaction intents
    
    @validator('original_transcript')
    def validate_transcript(cls, v):
        if not v or not v.strip():
            raise ValueError("Original transcript cannot be empty")
        if len(v) > 1000:
            raise ValueError("Original transcript too long (max 1000 characters)")
        return v.strip()
    
    @validator('threshold')
    def validate_threshold(cls, v):
        if v < 0 or v > 100:
            raise ValueError("Threshold must be between 0 and 100")
        return v

class BubbleGPTResponse(BaseModel):
    """Bubble-friendly GPT response"""
    success: bool
    processing_time_ms: float
    timestamp: str
    cost_estimate_usd: Optional[float] = None
    
    # Input echo
    interaction_id: str
    original_transcript: str
    threshold: int
    
    # GPT results
    intent_found: bool
    intent_id: Optional[str] = None
    intent_name: Optional[str] = None
    confidence: Optional[int] = None
    
    # GPT analysis
    gpt_reasoning: Optional[str] = None
    gpt_interpretation: Optional[str] = None
    candidates_analyzed: int = 0
    
    # Next steps
    recommended_action: str = "continue"  # "continue", "retry", "escalate"
    
    # Error handling
    error: Optional[str] = None

@router.post("/bubble-gpt-fallback", response_model=BubbleGPTResponse)
async def bubble_gpt_fallback(request: BubbleGPTRequest):
    """
    🧠 ENDPOINT 3: GPT INTENT DETECTION
    
    Uses GPT to analyze original transcript for intent when:
    - Adjustment found too many unknown words
    - Answer matching found no good matches
    - Manual trigger for intent detection
    
    Perfect for: Understanding user intent when other methods fail
    """
    start_time = time.time()
    
    try:
        logger.info(f"🧠 Bubble GPT: {request.interaction_id} - '{request.original_transcript}' (threshold: {request.threshold}%)")
        
        # Call your existing GPT service
        gpt_request = GPTFallbackRequest(
            interaction_id=request.interaction_id,
            original_transcript=request.original_transcript,
            threshold=request.threshold,
            user_id=request.user_id,
            custom_intent_ids=request.custom_intent_ids
        )
        
        gpt_result = await analyze_original_transcript_intent(gpt_request)
        
        # Determine recommended action
        recommended_action = "continue"
        if gpt_result.intent_matched:
            recommended_action = "continue"
        elif gpt_result.error:
            recommended_action = "retry"
        else:
            recommended_action = "escalate"  # No intent found, may need human help
        
        processing_time = round((time.time() - start_time) * 1000, 2)
        
        logger.info(f"🧠 GPT result: intent_found={gpt_result.intent_matched}, "
                   f"intent={gpt_result.intent_name}, confidence={gpt_result.similarity_score}")
        
        return BubbleGPTResponse(
            success=True,
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
            cost_estimate_usd=gpt_result.cost_estimate_usd,
            interaction_id=request.interaction_id,
            original_transcript=request.original_transcript,
            threshold=request.threshold,
            intent_found=gpt_result.intent_matched,
            intent_id=gpt_result.intent_id,
            intent_name=gpt_result.intent_name,
            confidence=gpt_result.similarity_score,
            gpt_reasoning=gpt_result.gpt_reasoning,
            gpt_interpretation=gpt_result.gpt_alternative_interpretation,
            candidates_analyzed=gpt_result.candidates_analyzed,
            recommended_action=recommended_action
        )
        
    except Exception as e:
        processing_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"❌ Bubble GPT failed: {e}")
        
        return BubbleGPTResponse(
            success=False,
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
            interaction_id=request.interaction_id,
            original_transcript=request.original_transcript,
            threshold=request.threshold,
            intent_found=False,
            candidates_analyzed=0,
            recommended_action="retry",
            error=str(e)
        )

# -------------------------
# 4. GET INTERACTION DATA ENDPOINT
# -------------------------

class BubbleInteractionResponse(BaseModel):
    """Bubble-friendly interaction data response"""
    success: bool
    processing_time_ms: float
    timestamp: str
    
    # Interaction data
    interaction_id: str
    subtopic_id: Optional[str] = None
    subtopic_name: Optional[str] = None
    
    # Video data (Cloudinary)
    video_url: Optional[str] = None
    video_poster_url: Optional[str] = None
    cloudinary_public_id: Optional[str] = None
    video_duration_seconds: Optional[int] = None
    
    # Interaction details
    interaction_type: Optional[str] = None
    interaction_level_from: Optional[int] = None
    interaction_optimum_level: Optional[int] = None
    
    # Content
    question_text_fr: Optional[str] = None
    question_text_en: Optional[str] = None
    
    # Metadata
    is_entry_point: bool = False
    
    # Error handling
    error: Optional[str] = None


@router.get("/get-interaction/{interaction_id}", response_model=BubbleInteractionResponse)
async def bubble_get_interaction(interaction_id: str):
    """
    🎥 ENDPOINT 4: GET INTERACTION DATA
    
    Returns complete interaction data including:
    - Video URL (Cloudinary optimized)
    - Question text (French + English)
    - Interaction metadata
    - All fields from brain_interaction table
    
    Usage in Bubble:
    1. Call this endpoint with interaction_id
    2. Use response.video_url in your video player
    3. Display response.question_text_fr to user
    4. Use response.interaction_type for UI logic
    
    Example:
        GET /api/bubble/get-interaction/inter_abc123
    """
    start_time = time.time()
    
    try:
        logger.info(f"📥 Fetching interaction: {interaction_id}")
        
        # Get database connection
        import os
        DATABASE_URL = os.getenv("DATABASE_URL")
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            # Query brain_interaction table
            query = """
            SELECT 
                bi.id,
                bi.subtopic_id,
                bs.name as subtopic_name,
                bi.video_url,
                bi.cloudinary_public_id,
                bi.video_duration_seconds,
                bi.interaction_type,
                bi.level_from,
                bi.optimum_level,
                bi.question_text_fr,
                bi.question_text_en,
                bi.is_entry_point
            FROM brain_interaction bi
            LEFT JOIN brain_subtopic bs ON bi.subtopic_id = bs.id
            WHERE bi.id = $1
            """
            
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, interaction_id)
                
                if not row:
                    processing_time = round((time.time() - start_time) * 1000, 2)
                    logger.warning(f"❌ Interaction not found: {interaction_id}")
                    
                    return BubbleInteractionResponse(
                        success=False,
                        processing_time_ms=processing_time,
                        timestamp=datetime.now().isoformat(),
                        interaction_id=interaction_id,
                        error=f"Interaction '{interaction_id}' not found in database"
                    )
                
                # Convert to dict
                data = dict(row)
                
                # Build Cloudinary URLs if needed
                video_url = data.get('video_url')
                video_poster_url = None
                
                # If video_url is empty but we have cloudinary_public_id, build URL
                if not video_url and data.get('cloudinary_public_id'):
                    cloudinary_public_id = data['cloudinary_public_id']
                    # Replace with your actual Cloudinary cloud name
                    CLOUDINARY_CLOUD = "dz2qwevm9"  # TODO: Update this!
                    
                    # Mobile-optimized video URL
                    video_url = (
                        f"https://res.cloudinary.com/{CLOUDINARY_CLOUD}/video/upload/"
                        f"c_limit,w_720,q_auto:eco,f_auto/{cloudinary_public_id}.mp4"
                    )
                    
                    # Poster image (first frame of video)
                    video_poster_url = (
                        f"https://res.cloudinary.com/{CLOUDINARY_CLOUD}/video/upload/"
                        f"so_0,w_720,h_1280,c_fill,q_auto:eco/{cloudinary_public_id}.jpg"
                    )
                
                processing_time = round((time.time() - start_time) * 1000, 2)
                logger.info(f"✅ Interaction fetched: {interaction_id} ({processing_time}ms)")
                
                return BubbleInteractionResponse(
                    success=True,
                    processing_time_ms=processing_time,
                    timestamp=datetime.now().isoformat(),
                    interaction_id=data['id'],
                    subtopic_id=data.get('subtopic_id'),
                    subtopic_name=data.get('subtopic_name'),
                    video_url=video_url,
                    video_poster_url=video_poster_url,
                    cloudinary_public_id=data.get('cloudinary_public_id'),
                    video_duration_seconds=data.get('video_duration_seconds'),
                    interaction_type=data.get('interaction_type'),
                    interaction_level_from=data.get('level_from'),
                    interaction_optimum_level=data.get('optimum_level'),
                    question_text_fr=data.get('question_text_fr'),
                    question_text_en=data.get('question_text_en'),
                    is_entry_point=data.get('is_entry_point', False)
                )
                
        finally:
            await pool.close()
            
    except Exception as e:
        processing_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"❌ Error fetching interaction {interaction_id}: {e}")
        
        return BubbleInteractionResponse(
            success=False,
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
            interaction_id=interaction_id,
            error=f"Database error: {str(e)}"
        )

# -------------------------
# CONFIGURATION AND HEALTH ENDPOINTS
# -------------------------
@router.get("/bubble-config")
async def get_bubble_integration_config():
    """Configuration info for Bubble setup"""
    return {
        "integration_type": "3_separate_endpoints",
        "endpoints": {
            "1_adjustment": {
                "url": "/api/bubble/bubble-adjust-transcript",
                "method": "POST",
                "description": "Process raw transcript - detect entities, vocabulary",
                "input": "original_transcript",
                "output": "completed_transcript + analysis",
                "use_when": "Always first step after speech recognition"
            },
            "2_matching": {
                "url": "/api/bubble/bubble-match-answer",
                "method": "POST", 
                "description": "Match processed transcript against expected answers",
                "input": "completed_transcript (from adjustment)",
                "output": "match_found + similarity_score",
                "use_when": "After adjustment, for correctness checking"
            },
            "3_gpt_fallback": {
                "url": "/api/bubble/bubble-gpt-fallback",
                "method": "POST",
                "description": "GPT intent detection when other methods fail",
                "input": "original_transcript (not adjusted)",
                "output": "detected_intent + confidence",
                "use_when": "Poor adjustment quality OR no answer match found"
            }
        },
        "workflow_patterns": {
            "happy_path": [
                "1. Call bubble-adjust-transcript",
                "2. If quality_score = 'good/excellent', call bubble-match-answer", 
                "3. If match_found = true, show success feedback",
                "4. If match_found = false, optionally call bubble-gpt-fallback"
            ],
            "poor_quality_path": [
                "1. Call bubble-adjust-transcript",
                "2. If suggest_gpt_fallback = true, call bubble-gpt-fallback",
                "3. Handle based on detected intent"
            ]
        },
        "bubble_conditions": {
            "trigger_gpt_when": [
                "adjustment suggest_gpt_fallback = yes",
                "matching suggest_gpt_fallback = yes", 
                "matching match_found = no",
                "manual trigger by user"
            ]
        }
    }

@router.get("/bubble-health")
async def bubble_integration_health():
    """Health check for Bubble integration"""
    return {
        "status": "healthy",
        "service": "bubble_integration_3_endpoints",
        "endpoints": {
            "adjustment": "✅ Ready",
            "matching": "✅ Ready",
            "gpt_fallback": "✅ Ready"
        },
        "integration_pattern": "3 independent API calls",
        "cost_optimization": "✅ GPT only when needed",
        "error_handling": "✅ Graceful fallbacks"
    }
