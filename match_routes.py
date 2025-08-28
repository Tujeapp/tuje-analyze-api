# Updated match_routes.py - Enhanced with new matching service integration
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict
import json
import openai
import logging
import asyncpg
import difflib
import time
import os

# Import from your transcription service
from adjustement_types import TranscriptionAdjustRequest, AdjustmentResult
from adjustement_models import adjust_transcription_endpoint

# NEW: Import from the new matching service
from matching_answer_service import answer_matching_service
from matching_answer_types import MatchAnswerRequest, CombinedAdjustmentAndMatchRequest

# Use the same pattern as your other files
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

router = APIRouter()
logger = logging.getLogger(__name__)

# -------------------------
# NEW: Models for Answer Matching (Enhanced)
# -------------------------
class MatchAnswerRequest(BaseModel):
    """Request for matching user answer against expected answers"""
    interaction_id: str
    user_transcription: str
    threshold: int = 85
    auto_adjust: bool = True  # Enable/disable automatic transcription adjustment
    user_id: Optional[str] = None

class MatchAnswerResponse(BaseModel):
    """Response with matching results and adjustment details"""
    match_found: bool
    call_gpt: bool
    best_answer: Optional[Dict] = None
    reason: Optional[str] = None
    best_attempt: Optional[Dict] = None
    # Adjustment details
    adjustment_applied: bool = False
    original_transcript: Optional[str] = None
    adjusted_transcript: Optional[str] = None
    vocabulary_found: List[Dict] = []
    entities_found: List[Dict] = []
    processing_time_ms: Optional[float] = None

# -------------------------
# Helper function to get expected entities from database
# -------------------------
async def get_interaction_expected_entities(interaction_id: str) -> Optional[List[str]]:
    """Get expected entities for an interaction from database"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            result = await conn.fetchrow("""
                SELECT expected_entities_id 
                FROM brain_interaction 
                WHERE id = $1 AND live = TRUE
            """, interaction_id)
            
            if result and result["expected_entities_id"]:
                entities = result["expected_entities_id"]
                if isinstance(entities, list):
                    return [str(e).strip() for e in entities if e and str(e).strip()]
                elif isinstance(entities, str):
                    return [e.strip() for e in entities.split(',') if e.strip()]
            
            return None
        finally:
            await conn.close()
    except Exception as e:
        logger.warning(f"Failed to get expected entities: {e}")
        return None

# -------------------------
# NEW: Enhanced Match Answer Endpoint
# -------------------------
@router.post("/match-answer", response_model=MatchAnswerResponse)
async def match_answer_with_adjustment(request: MatchAnswerRequest, background_tasks: BackgroundTasks):
    """
    Enhanced answer matching with automatic transcription adjustment
    
    Workflow:
    1. If auto_adjust=True: Apply transcription adjustment first
    2. Use adjusted transcript for answer matching  
    3. Return both matching results and adjustment details
    """
    start_time = time.time()
    
    try:
        original_transcript = request.user_transcription
        adjusted_transcript = original_transcript
        adjustment_applied = False
        vocabulary_found = []
        entities_found = []
        adjustment_time = 0
        
        # STEP 1: Apply transcription adjustment if enabled
        if request.auto_adjust:
            logger.info(f"Applying transcription adjustment to: '{original_transcript}'")
            
            try:
                # NEW: Load expected entities from interaction if interaction_id provided
                expected_entities_ids = None
                if request.interaction_id:
                    expected_entities_ids = await get_interaction_expected_entities(request.interaction_id)
                    if expected_entities_ids:
                        logger.info(f"Loaded expected entities for interaction {request.interaction_id}: {expected_entities_ids}")
                
                # Call the adjustment service with context
                adjustment_request = TranscriptionAdjustRequest(
                    original_transcript=original_transcript,
                    user_id=request.user_id,
                    interaction_id=request.interaction_id,
                    expected_entities_ids=expected_entities_ids  # NEW: Pass expected entities
                )
                
                adjustment_result = await adjust_transcription_endpoint(adjustment_request)
                
                adjusted_transcript = adjustment_result.adjusted_transcript
                vocabulary_found = [vocab.dict() for vocab in adjustment_result.list_of_vocabulary]
                entities_found = [entity.dict() for entity in adjustment_result.list_of_entities]
                adjustment_time = adjustment_result.processing_time_ms
                adjustment_applied = True
                
                logger.info(f"Adjustment successful: '{original_transcript}' → '{adjusted_transcript}'")
                
            except Exception as e:
                logger.warning(f"Transcription adjustment failed: {e}")
                logger.info("Falling back to original transcript")
                # Continue with original transcript if adjustment fails
        
        # STEP 2: Use new matching service for better performance
        logger.info(f"🔄 Using new matching service for: '{adjusted_transcript}'")
        
        try:
            # Use the new matching service
            match_request = MatchAnswerRequest(
                interaction_id=request.interaction_id,
                completed_transcript=adjusted_transcript,
                threshold=request.threshold,
                user_id=request.user_id
            )
            
            match_result = await answer_matching_service.match_completed_transcript(
                interaction_id=request.interaction_id,
                completed_transcript=adjusted_transcript,
                threshold=request.threshold
            )
            
            # Calculate total processing time
            total_time = (time.time() - start_time) * 1000
            
            logger.info(f"New matching service result: match_found={match_result.get('match_found', False)}, "
                       f"score={match_result.get('similarity_score', 0)}")
            
            # Convert new service result to legacy response format
            if match_result.get('match_found'):
                best_answer = {
                    "id": match_result['answer_id'],
                    "transcriptionFr": match_result['answer_details']['transcription_fr'],
                    "transcriptionEn": match_result['answer_details']['transcription_en'], 
                    "transcriptionAdjusted": match_result['answer_details']['transcription_adjusted'],
                    "score": match_result['similarity_score'],
                    "interaction_answer_id": match_result['interaction_answer_id']
                }
                
                return MatchAnswerResponse(
                    match_found=True,
                    call_gpt=False,
                    best_answer=best_answer,
                    adjustment_applied=adjustment_applied,
                    original_transcript=original_transcript if adjustment_applied else None,
                    adjusted_transcript=adjusted_transcript if adjustment_applied else None,
                    vocabulary_found=vocabulary_found,
                    entities_found=entities_found,
                    processing_time_ms=total_time
                )
            else:
                return MatchAnswerResponse(
                    match_found=False,
                    call_gpt=True,
                    reason=match_result.get('reason', 'No match found'),
                    adjustment_applied=adjustment_applied,
                    original_transcript=original_transcript if adjustment_applied else None,
                    adjusted_transcript=adjusted_transcript if adjustment_applied else None,
                    vocabulary_found=vocabulary_found,
                    entities_found=entities_found,
                    processing_time_ms=total_time
                )
                
        except Exception as e:
            logger.warning(f"New matching service failed, falling back to legacy: {e}")
            
            # FALLBACK: Use legacy matching logic
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # Get answers linked to this interaction
                rows = await conn.fetch("""
                    SELECT a.id, a.transcription_fr, a.transcription_en, a.transcription_adjusted
                    FROM brain_interaction_answer ia
                    JOIN brain_answer a ON ia.answer_id = a.id
                    WHERE ia.interaction_id = $1 AND a.live = TRUE
                    ORDER BY a.created_at ASC
                """, request.interaction_id)
            finally:
                await conn.close()

            if not rows:
                raise HTTPException(
                    status_code=404, 
                    detail=f"No answers found for interaction_id: {request.interaction_id}"
                )

            # Compare user input against expected answers
            user_input = adjusted_transcript.strip().lower()
            best_score = 0
            best_match = None

            for row in rows:
                expected = row["transcription_adjusted"].strip().lower()
                score = difflib.SequenceMatcher(None, user_input, expected).ratio() * 100
                
                attempt = {
                    "id": row["id"],
                    "transcriptionFr": row["transcription_fr"],
                    "transcriptionEn": row["transcription_en"],
                    "transcriptionAdjusted": row["transcription_adjusted"],
                    "score": round(score, 1)
                }

                if score > best_score:
                    best_score = score
                    best_match = attempt

            # Calculate total processing time
            total_time = (time.time() - start_time) * 1000
            
            if best_match and best_score >= request.threshold:
                return MatchAnswerResponse(
                    match_found=True,
                    call_gpt=False,
                    best_answer=best_match,
                    adjustment_applied=adjustment_applied,
                    original_transcript=original_transcript if adjustment_applied else None,
                    adjusted_transcript=adjusted_transcript if adjustment_applied else None,
                    vocabulary_found=vocabulary_found,
                    entities_found=entities_found,
                    processing_time_ms=total_time
                )
            else:
                return MatchAnswerResponse(
                    match_found=False,
                    call_gpt=True,
                    reason=f"No match above threshold {request.threshold}%. Best score: {best_score:.1f}%",
                    best_attempt=best_match,
                    adjustment_applied=adjustment_applied,
                    original_transcript=original_transcript if adjustment_applied else None,
                    adjusted_transcript=adjusted_transcript if adjustment_applied else None,
                    vocabulary_found=vocabulary_found,
                    entities_found=entities_found,
                    processing_time_ms=total_time
                )

    except Exception as e:
        logger.error(f"Match answer with adjustment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# Backward Compatibility Endpoint
# -------------------------
@router.post("/match-answer-legacy")
async def match_answer_legacy(request: MatchAnswerRequest):
    """
    Legacy endpoint without automatic adjustment for backward compatibility
    """
    # Force auto_adjust to False
    request.auto_adjust = False
    return await match_answer_with_adjustment(request, BackgroundTasks())

# -------------------------
# Test Endpoint for Integration
# -------------------------
@router.post("/test-match-with-adjustment")
async def test_match_with_adjustment(
    original_transcript: str,
    interaction_id: str,
    threshold: int = 85,
    auto_adjust: bool = True
):
    """Test endpoint to see adjustment + matching in action"""
    
    request = MatchAnswerRequest(
        interaction_id=interaction_id,
        user_transcription=original_transcript,
        threshold=threshold,
        auto_adjust=auto_adjust,
        user_id="test_user"
    )
    
    result = await match_answer_with_adjustment(request, BackgroundTasks())
    
    return {
        "test_input": {
            "original_transcript": original_transcript,
            "interaction_id": interaction_id,
            "threshold": threshold,
            "auto_adjust_enabled": auto_adjust
        },
        "result": result,
        "summary": {
            "adjustment_worked": result.adjustment_applied,
            "match_found": result.match_found,
            "should_call_gpt": result.call_gpt,
            "processing_time": f"{result.processing_time_ms:.2f}ms",
            "improvement": "Check if adjusted_transcript differs from original_transcript"
        },
        "migration_note": {
            "recommendation": "Migrate to /api/matching/combined-adjust-and-match for better performance",
            "benefits": "Single API call, better error handling, comprehensive monitoring"
        }
    }

# -------------------------
# EXISTING: Your GPT Intent Models (Keep unchanged)
# -------------------------
class BubbleFilteredIntent(BaseModel):
    """Intent as filtered and sent from Bubble workflow - matches your actual schema"""
    id: str
    name: str           # Single name field (could be French or mixed)
    description: Optional[str] = None

class BubbleGPTFallbackRequest(BaseModel):
    """Request from Bubble with pre-filtered intents"""
    user_transcription: str
    filtered_intents: List[BubbleFilteredIntent]
    interaction_context: Optional[str] = None  # Optional context from Bubble
    confidence_threshold: int = 70

class GPTIntentAnalysisResponse(BaseModel):
    """Response matching your exact needs"""
    matched_intent_id: Optional[str] = None     # ID from your filtered list, or None
    matched_intent_name: Optional[str] = None   # Name from your database
    confidence_score: int
    gpt_suggested_intent: Optional[str] = None  # GPT's own interpretation when no match
    reasoning: str
    cost_estimate: float

# -------------------------
# EXISTING: Your GPT Endpoints (Keep unchanged)
# -------------------------
@router.post("/bubble-gpt-fallback", response_model=GPTIntentAnalysisResponse)
async def bubble_gpt_fallback(request: BubbleGPTFallbackRequest):
    """
    GPT fallback that works with Bubble's pre-filtered intent list.
    """
    
    try:
        if not request.filtered_intents:
            raise HTTPException(status_code=400, detail="No filtered intents provided by Bubble")
        
        # Call GPT with the pre-filtered intent list
        gpt_response = await analyze_against_filtered_intents(
            user_input=request.user_transcription,
            filtered_intents=request.filtered_intents,
            context=request.interaction_context,
            threshold=request.confidence_threshold
        )
        
        # Process response and find matching intent
        result = process_filtered_intent_response(
            gpt_response, 
            request.filtered_intents,
            request.confidence_threshold
        )
        
        # Log for analytics
        logger.info(f"Bubble GPT fallback: intents_checked={len(request.filtered_intents)}, "
                   f"matched={result.matched_intent_name}, "
                   f"confidence={result.confidence_score}, "
                   f"cost=${result.cost_estimate}")
        
        return result
        
    except Exception as e:
        logger.error(f"Bubble GPT fallback error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"GPT intent analysis failed: {str(e)}")

# Test endpoint using your actual schema
@router.post("/test-bubble-gpt-fallback")
async def test_bubble_gpt_fallback(
    user_transcription: str,
    test_intents: List[Dict] = None
):
    """
    Test endpoint for debugging GPT responses with your actual schema
    """
    if not test_intents:
        # Example intents matching your schema
        test_intents = [
            {
                "id": "intent_001", 
                "name": "se_presenter", 
                "description": "L'utilisateur veut se présenter (nom, prénom)"
            },
            {
                "id": "intent_002", 
                "name": "saluer", 
                "description": "L'utilisateur veut dire bonjour ou saluer"
            },
            {
                "id": "intent_003", 
                "name": "donner_age", 
                "description": "L'utilisateur veut donner son âge"
            },
            {
                "id": "intent_004", 
                "name": "remercier", 
                "description": "L'utilisateur veut dire merci"
            }
        ]
    
    filtered_intents = [BubbleFilteredIntent(**intent) for intent in test_intents]
    
    request = BubbleGPTFallbackRequest(
        user_transcription=user_transcription,
        filtered_intents=filtered_intents,
        interaction_context="Conversation d'introduction"
    )
    
    return await bubble_gpt_fallback(request)

# Helper endpoint for Bubble workflow optimization
@router.get("/intent-filtering-tips")
async def get_intent_filtering_tips():
    """
    Provides tips for Bubble on how to filter intents effectively
    """
    return {
        "optimal_intent_count": "3-5 intents per GPT call for best cost/accuracy",
        "filtering_strategies": [
            "Filter by subtopic/lesson context",
            "Include common fallback intents (clarify, repeat, help)",
            "Consider user progress level",
            "Include intents from current and previous lessons"
        ],
        "cost_optimization": [
            "Pre-filter in Bubble rather than loading all intents",
            "Batch similar interactions to reuse intent lists",
            "Cache common intent combinations"
        ],
        "accuracy_tips": [
            "Include intent descriptions for better GPT understanding",
            "Use consistent naming conventions",
            "Test with actual user transcriptions"
        ]
    }

# -------------------------
# EXISTING: Helper Functions (Keep unchanged)
# -------------------------
async def analyze_against_filtered_intents(
    user_input: str,
    filtered_intents: List[BubbleFilteredIntent], 
    context: Optional[str],
    threshold: int
) -> Dict:
    """
    Analyze user input against Bubble's pre-filtered intent list
    """
    
    # Format the filtered intents for GPT
    intent_options = []
    for intent in filtered_intents:
        intent_line = f"- {intent.name} [ID: {intent.id}]"
        if intent.description:
            intent_line += f" - {intent.description}"
        intent_options.append(intent_line)
    
    context_section = ""
    if context:
        context_section = f"\nContexte de l'interaction: {context}\n"
    
    prompt = f"""Tu es un expert en analyse d'intentions pour l'apprentissage du français.

{context_section}L'apprenant a dit (transcription vocale possiblement imparfaite): "{user_input}"

LISTE DES INTENTIONS POSSIBLES (pré-filtrées par le contexte):
{chr(10).join(intent_options)}

TÂCHE:
1. Analyse ce que l'utilisateur essaie de dire, même si la transcription est imparfaite
2. Trouve l'intention la plus proche dans la liste ci-dessus
3. Donne un score de confiance (0-100)
4. Si AUCUNE intention de la liste ne correspond bien (score < {threshold}), retourne "other"

RÈGLES IMPORTANTES:
- Concentre-toi sur l'INTENTION plutôt que la grammaire parfaite
- Considère les erreurs de transcription vocale (mots coupés, sons similaires)
- "je suis marie" = intention de se présenter
- "bonjour comment" = intention de saluer (même si incomplet)
- "j'ai vingt" = donner son âge (même si coupé)
- "merci beaucoup" = remercier

RÉPONSE REQUISE:
Si une intention correspond (score >= {threshold}):
{{
  "matched_intent_name": "se_presenter",
  "matched_intent_id": "intent_123",
  "confidence_score": 85,
  "reasoning": "L'utilisateur essaie de se présenter malgré la transcription imparfaite"
}}

Si AUCUNE intention ne correspond (score < {threshold}):
{{
  "matched_intent_name": "other", 
  "matched_intent_id": null,
  "confidence_score": 30,
  "reasoning": "Aucune intention de la liste ne correspond au contexte",
  "gpt_own_interpretation": "L'utilisateur semble vouloir [votre interprétation]"
}}

Réponds UNIQUEMENT avec le JSON, pas d'explication supplémentaire."""

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # Cost-effective choice
            messages=[
                {
                    "role": "system",
                    "content": "Tu es un assistant expert en compréhension des intentions d'apprenants français. Tu dois analyser des transcriptions vocales imparfaites et les associer à des intentions prédéfinies."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
