# answer_processing_orchestrator.py
"""
Orchestrates the complete answer processing pipeline
Connects all existing services with the new Answer Service
"""
import asyncpg
import logging
from typing import Dict

# Import your EXISTING services
from adjustement_adjuster import TranscriptionAdjuster
from matching_answer_service import answer_matching_service
from gpt_fallback_service import gpt_fallback_service

# Import NEW session management services
from session_management import answer_service, interaction_service

logger = logging.getLogger(__name__)


async def process_user_answer_complete(
    interaction_id: str,
    user_id: str,
    original_transcript: str,
    db_pool: asyncpg.Pool
) -> Dict:
    """
    Complete answer processing pipeline:
    1. Create answer record
    2. Call adjustment service (existing)
    3. Call matching service (existing)
    4. Optionally call GPT (existing)
    5. Update answer record with all results
    6. Return results to Bubble
    
    Args:
        interaction_id: Current interaction ID
        user_id: User ID
        original_transcript: Raw speech from user
        db_pool: Database connection pool
        
    Returns:
        Dict with all results and feedback for user
    """
    
    logger.info(f"🎯 Processing answer for interaction {interaction_id}")
    
    try:
        # ================================================================
        # STEP 1: Create Answer Record
        # ================================================================
        answer_id = await answer_service.create_answer(
            interaction_id=interaction_id,
            user_id=user_id,
            original_transcript=original_transcript,
            db_pool=db_pool
        )
        
        # Increment attempt counter
        await interaction_service.increment_attempt_count(
            interaction_id, db_pool
        )
        
        logger.info(f"✅ Created answer: {answer_id}")
        
        # ================================================================
        # STEP 2: Call Adjustment Service (YOUR EXISTING CODE)
        # ================================================================
        logger.info("📝 Calling adjustment service...")
        
        adjuster = TranscriptionAdjuster()
        adjustment_result = await adjuster.adjust_transcription(
            request={
                "original_transcript": original_transcript,
                "interaction_id": interaction_id,
                "user_id": user_id
            },
            pool=db_pool
        )
        
        # Save adjustment results to database
        await answer_service.update_answer_with_adjustment(
            answer_id=answer_id,
            adjusted_transcript=adjustment_result.adjusted_transcript,
            completed_transcript=adjustment_result.completed_transcript,
            vocabulary_found=adjustment_result.list_of_vocabulary,
            entities_found=adjustment_result.list_of_entities,
            notion_matches=adjustment_result.list_of_notions,
            db_pool=db_pool
        )
        
        logger.info(f"✅ Adjustment complete")
        
        # ================================================================
        # STEP 3: Call Matching Service (YOUR EXISTING CODE)
        # ================================================================
        logger.info("🔍 Calling matching service...")
        
        matching_result = await answer_matching_service.match_completed_transcript(
            interaction_id=interaction_id,
            completed_transcript=adjustment_result.completed_transcript,
            threshold=80
        )
        
        # Save matching results to database
        await answer_service.update_answer_with_matching(
            answer_id=answer_id,
            similarity_score=matching_result.get('similarity_score', 0),
            matched_answer_id=matching_result.get('answer_id'),
            db_pool=db_pool
        )
        
        logger.info(f"✅ Matching complete (score: {matching_result.get('similarity_score', 0)})")
        
        # ================================================================
        # STEP 4: Decide What Happens Next
        # ================================================================
        
        # Check if we have a good match
        if matching_result['match_found'] and matching_result['similarity_score'] >= 80:
            # ✅ SUCCESS - Good answer match!
            logger.info("🎉 Good answer match found!")
            
            # Mark as final answer
            await answer_service.mark_as_final_answer(
                answer_id=answer_id,
                processing_method="answer_match",
                cost_saved=0.002,  # Saved GPT call
                db_pool=db_pool
            )
            
            # Calculate score (we'll do this in Part 3)
            interaction_score = int(matching_result['similarity_score'])
            
            # Complete the interaction
            await interaction_service.complete_interaction(
                interaction_id=interaction_id,
                final_answer_id=answer_id,
                interaction_score=interaction_score,
                db_pool=db_pool
            )
            
            return {
                "status": "success",
                "answer_id": answer_id,
                "method": "answer_match",
                "similarity_score": matching_result['similarity_score'],
                "interaction_score": interaction_score,
                "interaction_complete": True,
                "feedback": "Perfect! Well done! 🎉",
                "gpt_used": False,
                "cost_saved": 0.002
            }
        
        else:
            # ⚠️ NO GOOD MATCH - User needs to try again
            logger.info("⚠️ No good match - user should retry")
            
            # Don't complete interaction yet - let user try again
            
            return {
                "status": "retry",
                "answer_id": answer_id,
                "method": "no_match",
                "similarity_score": matching_result.get('similarity_score', 0),
                "interaction_score": 0,
                "interaction_complete": False,
                "feedback": "Not quite right. Try again! 💪",
                "gpt_used": False,
                "cost_saved": 0
            }
        
    except Exception as e:
        logger.error(f"❌ Error processing answer: {e}", exc_info=True)
        raise


# ================================================================
# OPTIONAL: With GPT Fallback (for later - Phase 2)
# ================================================================
async def process_user_answer_with_gpt(
    interaction_id: str,
    user_id: str,
    original_transcript: str,
    db_pool: asyncpg.Pool
) -> Dict:
    """
    Same as above, but includes GPT fallback logic
    This is for Phase 2 - after basic system works
    """
    
    # Steps 1-3 same as above...
    # ... (adjustment and matching)
    
    # STEP 4: If no good match, try GPT
    if not matching_result['match_found']:
        logger.info("🤖 Calling GPT fallback...")
        
        gpt_result = await gpt_fallback_service.analyze_intent(
            interaction_id=interaction_id,
            original_transcript=original_transcript,
            threshold=70
        )
        
        if gpt_result.get('intent_matched'):
            # GPT detected intent
            await answer_service.update_answer_with_gpt(
                answer_id=answer_id,
                gpt_intent_detected=gpt_result.get('intent_id'),
                processing_method="gpt_fallback",
                db_pool=db_pool
            )
            
            # Partial score for intent match
            interaction_score = int(gpt_result.get('similarity_score', 0) * 0.6)
            
            return {
                "status": "partial_success",
                "method": "gpt_fallback",
                "gpt_intent": gpt_result.get('intent_name'),
                "interaction_score": interaction_score,
                "feedback": "I understood your intent, but try to be more specific! 💡",
                "gpt_used": True,
                "cost_saved": 0
            }
