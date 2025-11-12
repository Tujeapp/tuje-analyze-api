# bubble_integration_router.py - COMPLETE FILE WITH ALL ENDPOINTS
"""
Bubble.io-optimized endpoints for TuJe French learning API
✅ Fixed GET interaction endpoint to match actual PostgreSQL schema
✅ All other endpoints remain unchanged
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

# Environment variables
DATABASE_URL = os.getenv("DATABASE_URL")
CLOUDINARY_CLOUD = os.getenv("CLOUDINARY_CLOUD_NAME", "dz2qwevm9")

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
    suggest_gpt_fallback: bool = False
    quality_score: str = "good"
    
    # Error handling
    error: Optional[str] = None

@router.post("/bubble-adjust-transcript", response_model=BubbleAdjustmentResponse)
async def bubble_transcription_adjustment(request: BubbleAdjustmentRequest):
    """
    🔧 ENDPOINT 1: TRANSCRIPTION ADJUSTMENT
    """
    start_time = time.time()
    
    try:
        logger.info(f"🔧 Bubble adjustment: {request.interaction_id} - '{request.original_transcript}'")
        
        adj_request = TranscriptionAdjustRequest(
            original_transcript=request.original_transcript,
            user_id=request.user_id,
            interaction_id=request.interaction_id
        )
        
        adj_result = await adjust_transcription_endpoint(adj_request)
        
        vocabulary_found = [v.dict() for v in adj_result.list_of_vocabulary]
        entities_found = [e.dict() for e in adj_result.list_of_entities]
        
        vocabnotfound_count = sum(
            1 for vocab in vocabulary_found 
            if vocab.get('transcription_adjusted') == 'vocabnotfound'
        )
        
        total_words = len(request.original_transcript.split())
        suggest_gpt = vocabnotfound_count >= 3 or (vocabnotfound_count / max(total_words, 1)) > 0.4
        
        if vocabnotfound_count == 0:
            quality_score = "excellent"
        elif vocabnotfound_count <= 2:
            quality_score = "good"
        else:
            quality_score = "poor"
        
        processing_time = round((time.time() - start_time) * 1000, 2)
        
        logger.info(f"✅ Adjustment complete: quality={quality_score}")
        
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
    completed_transcript: str
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
    
    interaction_id: str
    completed_transcript: str
    threshold: int
    
    match_found: bool
    matched_answer_id: Optional[str] = None
    similarity_score: Optional[float] = None
    expected_answer: Optional[str] = None
    
    answer_french: Optional[str] = None
    answer_english: Optional[str] = None
    
    suggest_gpt_fallback: bool = False
    match_quality: str = "none"
    
    reason: Optional[str] = None
    error: Optional[str] = None

@router.post("/bubble-match-answer", response_model=BubbleMatchingResponse)
async def bubble_answer_matching(request: BubbleMatchingRequest):
    """
    🔍 ENDPOINT 2: ANSWER MATCHING
    """
    start_time = time.time()
    
    try:
        logger.info(f"🔍 Bubble matching: {request.interaction_id}")
        
        match_request = MatchAnswerRequest(
            interaction_id=request.interaction_id,
            completed_transcript=request.completed_transcript,
            threshold=request.threshold,
            user_id=request.user_id
        )
        
        match_result = await match_completed_transcript(match_request)
        
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
                suggest_gpt = True
        else:
            suggest_gpt = True
        
        processing_time = round((time.time() - start_time) * 1000, 2)
        
        logger.info(f"🎯 Matching result: found={match_result.match_found}")
        
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
    original_transcript: str
    threshold: int = 70
    user_id: Optional[str] = None
    custom_intent_ids: Optional[List[str]] = None
    
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
    
    interaction_id: str
    original_transcript: str
    threshold: int
    
    intent_found: bool
    intent_id: Optional[str] = None
    intent_name: Optional[str] = None
    confidence: Optional[int] = None
    
    gpt_reasoning: Optional[str] = None
    gpt_interpretation: Optional[str] = None
    candidates_analyzed: int = 0
    
    recommended_action: str = "continue"
    
    error: Optional[str] = None

@router.post("/bubble-gpt-fallback", response_model=BubbleGPTResponse)
async def bubble_gpt_fallback(request: BubbleGPTRequest):
    """
    🧠 ENDPOINT 3: GPT INTENT DETECTION
    """
    start_time = time.time()
    
    try:
        logger.info(f"🧠 Bubble GPT: {request.interaction_id}")
        
        gpt_request = GPTFallbackRequest(
            interaction_id=request.interaction_id,
            original_transcript=request.original_transcript,
            threshold=request.threshold,
            user_id=request.user_id,
            custom_intent_ids=request.custom_intent_ids
        )
        
        gpt_result = await analyze_original_transcript_intent(gpt_request)
        
        recommended_action = "continue"
        if gpt_result.intent_matched:
            recommended_action = "continue"
        elif gpt_result.error:
            recommended_action = "retry"
        else:
            recommended_action = "escalate"
        
        processing_time = round((time.time() - start_time) * 1000, 2)
        
        logger.info(f"🧠 GPT result: intent_found={gpt_result.intent_matched}")
        
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
# 4. GET INTERACTION DATA ENDPOINT - ✅ FIXED TO MATCH YOUR DATABASE
# -------------------------

class BubbleInteractionResponse(BaseModel):
    """Response model that perfectly matches your brain_interaction table structure"""
    success: bool
    processing_time_ms: float
    timestamp: str
    
    # Core identification
    interaction_id: str
    
    # Subtopic information (from JOIN)
    subtopic_id: Optional[str] = None
    subtopic_name: Optional[str] = None
    
    # Video URLs (these exist in your database!)
    video_url: Optional[str] = None
    video_poster_url: Optional[str] = None
    
    # Transcriptions (your database has these, not "question_text")
    transcription_fr: Optional[str] = None
    transcription_en: Optional[str] = None
    
    # Interaction type (from database + JOIN for name)
    interaction_type_id: Optional[str] = None
    interaction_type_name: Optional[str] = None
    
    # Metrics (numeric fields)
    interaction_optimum_level: Optional[float] = None
    boredom: Optional[float] = None
    
    # Array fields (relationships)
    intents: Optional[List[str]] = None
    expected_entities_id: Optional[List[str]] = None
    expected_vocab_id: Optional[List[str]] = None
    expected_notion_id: Optional[List[str]] = None
    interaction_vocab_id: Optional[List[str]] = None
    hint_ids: Optional[List[str]] = None
    
    # Metadata
    live: Optional[bool] = None
    created_at: Optional[str] = None
    
    # Error handling
    error: Optional[str] = None


@router.get("/get-interaction/{interaction_id}", response_model=BubbleInteractionResponse)
async def bubble_get_interaction(interaction_id: str):
    """
    🎥 ENDPOINT 4: GET INTERACTION DATA - ✅ FIXED TO MATCH YOUR DATABASE
    
    Returns complete interaction data from PostgreSQL using ONLY columns that exist.
    
    Your database has:
    ✅ transcription_fr, transcription_en (not question_text_fr/en)
    ✅ interaction_optimum_level (not optimum_level)
    ✅ interaction_type_id (not interaction_type)
    ✅ video_url, video_poster_url (these exist!)
    ✅ All array fields: intents, expected_vocab_id, hint_ids, etc.
    
    Usage in Bubble.io:
    1. Call: GET /api/bubble/get-interaction/{interaction_id}
    2. Use response.video_url in video player
    3. Display response.transcription_fr to user
    4. Use response.interaction_type_name for UI logic
    
    Example:
        GET /api/bubble/get-interaction/INT202505090900
    """
    start_time = time.time()
    
    try:
        logger.info(f"📥 Fetching interaction: {interaction_id}")
        
        if not interaction_id:
            raise HTTPException(status_code=400, detail="interaction_id is required")
        
        # Create database connection pool
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            # ✅ SQL QUERY USING ONLY COLUMNS THAT EXIST IN YOUR DATABASE
            query = """
            SELECT 
                -- Core fields
                bi.id,
                bi.subtopic_id,
                bs.name_fr as subtopic_name,
                
                -- Video fields (these exist!)
                bi.video_url,
                bi.video_poster_url,
                
                -- Transcription fields (not "question_text")
                bi.transcription_fr,
                bi.transcription_en,
                
                -- Type information
                bi.interaction_type_id,
                bit.name as interaction_type_name,
                
                -- Numeric metrics
                bi.interaction_optimum_level,
                bi.boredom,
                
                -- Array fields (relationships)
                bi.intents,
                bi.expected_entities_id,
                bi.expected_vocab_id,
                bi.expected_notion_id,
                bi.interaction_vocab_id,
                bi.hint_ids,
                
                -- Metadata
                bi.live,
                bi.created_at
                
            FROM brain_interaction bi
            LEFT JOIN brain_subtopic bs ON bi.subtopic_id = bs.id
            LEFT JOIN brain_interaction_type bit ON bi.interaction_type_id = bit.id
            WHERE bi.id = $1 AND bi.live = TRUE
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
                        error=f"Interaction '{interaction_id}' not found or not live"
                    )
                
                # Convert row to dict
                data = dict(row)
                
                # Log what we found
                logger.info(f"✅ Found interaction {interaction_id}")
                logger.info(f"   Type: {data.get('interaction_type_name')}")
                logger.info(f"   Subtopic: {data.get('subtopic_name')}")
                logger.info(f"   Has video: {'Yes' if data.get('video_url') else 'No'}")
                
                processing_time = round((time.time() - start_time) * 1000, 2)
                
                # Return perfectly matched response
                return BubbleInteractionResponse(
                    success=True,
                    processing_time_ms=processing_time,
                    timestamp=datetime.now().isoformat(),
                    
                    # Core
                    interaction_id=data['id'],
                    subtopic_id=data.get('subtopic_id'),
                    subtopic_name=data.get('subtopic_name'),
                    
                    # Video URLs (directly from database)
                    video_url=data.get('video_url'),
                    video_poster_url=data.get('video_poster_url'),
                    
                    # Transcriptions (use these, not "question_text")
                    transcription_fr=data.get('transcription_fr'),
                    transcription_en=data.get('transcription_en'),
                    
                    # Type
                    interaction_type_id=data.get('interaction_type_id'),
                    interaction_type_name=data.get('interaction_type_name'),
                    
                    # Metrics
                    interaction_optimum_level=float(data['interaction_optimum_level']) if data.get('interaction_optimum_level') else None,
                    boredom=float(data['boredom']) if data.get('boredom') else None,
                    
                    # Arrays (relationships)
                    intents=data.get('intents'),
                    expected_entities_id=data.get('expected_entities_id'),
                    expected_vocab_id=data.get('expected_vocab_id'),
                    expected_notion_id=data.get('expected_notion_id'),
                    interaction_vocab_id=data.get('interaction_vocab_id'),
                    hint_ids=data.get('hint_ids'),
                    
                    # Metadata
                    live=data.get('live'),
                    created_at=data.get('created_at').isoformat() if data.get('created_at') else None
                )
                
        finally:
            await pool.close()
            
    except HTTPException:
        raise
    except Exception as e:
        processing_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"❌ Error fetching interaction {interaction_id}: {e}", exc_info=True)
        
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
        "integration_type": "4_separate_endpoints",
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
            },
            "4_get_interaction": {
                "url": "/api/bubble/get-interaction/{interaction_id}",
                "method": "GET",
                "description": "Get interaction data including video URL and text",
                "input": "interaction_id",
                "output": "video_url + transcription + metadata",
                "use_when": "Loading interaction for user to respond to",
                "✅_fixed": "Now uses correct database column names"
            }
        },
        "workflow_patterns": {
            "happy_path": [
                "1. GET /get-interaction/{id} to load interaction",
                "2. Show video and transcription_fr to user",
                "3. POST /bubble-adjust-transcript with user speech",
                "4. If quality_score = 'good/excellent', POST /bubble-match-answer", 
                "5. If match_found = true, show success feedback",
                "6. If match_found = false, optionally POST /bubble-gpt-fallback"
            ],
            "poor_quality_path": [
                "1. GET /get-interaction/{id}",
                "2. POST /bubble-adjust-transcript",
                "3. If suggest_gpt_fallback = true, POST /bubble-gpt-fallback",
                "4. Handle based on detected intent"
            ]
        },
        "bubble_field_mapping": {
            "display_question": "response.transcription_fr",
            "video_source": "response.video_url",
            "video_poster": "response.video_poster_url",
            "interaction_type": "response.interaction_type_name",
            "difficulty": "response.interaction_optimum_level"
        }
    }

@router.get("/bubble-health")
async def bubble_integration_health():
    """Health check for Bubble integration"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1)
        
        try:
            async with pool.acquire() as conn:
                # Test database and count live interactions
                count = await conn.fetchval("""
                    SELECT COUNT(*) FROM brain_interaction WHERE live = TRUE
                """)
                
                # Get sample interaction
                sample = await conn.fetchval("""
                    SELECT id FROM brain_interaction WHERE live = TRUE LIMIT 1
                """)
                
                return {
                    "status": "healthy",
                    "service": "bubble_integration_4_endpoints",
                    "database": "connected",
                    "live_interactions": count,
                    "sample_interaction_id": sample,
                    "endpoints": {
                        "adjustment": "✅ Ready",
                        "matching": "✅ Ready",
                        "gpt_fallback": "✅ Ready",
                        "get_interaction": "✅ Ready (Fixed schema)"
                    },
                    "integration_pattern": "4 independent API calls",
                    "cost_optimization": "✅ GPT only when needed",
                    "schema_status": "✅ Matches PostgreSQL exactly",
                    "test_get_interaction": f"/api/bubble/get-interaction/{sample}" if sample else None
                }
        finally:
            await pool.close()
            
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
