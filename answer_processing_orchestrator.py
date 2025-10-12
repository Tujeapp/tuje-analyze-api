# answer_processing_orchestrator.py
"""
Answer Processing Orchestrator
Coordinates all services for complete answer processing workflow
"""
import asyncpg
import logging
from typing import Dict

# Import your EXISTING services (no changes to these)
from adjustement_adjuster import TranscriptionAdjuster
from matching_answer_service import answer_matching_service
from gpt_fallback_service import gpt_fallback_service

# Import NEW session management services
from session_management import (
    answer_service,
    interaction_service,
    scoring_service,
    bonus_malus_service,
    cycle_service
)

logger = logging.getLogger(__name__)


async def process_user_answer_complete(
    interaction_id: str,
    user_id: str,
    original_transcript: str,
    db_pool: asyncpg.Pool
) -> Dict:
    """
    Complete answer processing pipeline
    
    This orchestrates ALL services in the correct order:
    1. Creates answer record in database
    2. Calls adjustment service (your existing code)
    3. Calls matching service (your existing code)
    4. Optionally calls GPT (your existing code)
    5. Calculates score with bonus-malus (new)
    6. Completes interaction if successful (new)
    7. Returns comprehensive results
    
    Args:
        interaction_id: Current interaction ID
        user_id: User ID
        original_transcript: Raw speech from user
        db_pool: Database connection pool
        
    Returns:
        Dict with all results for Bubble to display
    """
    
    logger.info(f"🎯 Processing answer for interaction {interaction_id}")
    
    try:
        # ====================================================================
        # STEP 1: Create Answer Record
        # ====================================================================
        logger.info("📝 Step 1: Creating answer record")
        
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
        
        logger.info(f"✅ Answer record created: {answer_id}")
        
        # ====================================================================
        # STEP 2: Call Adjustment Service (YOUR EXISTING CODE)
        # ====================================================================
        logger.info("📝 Step 2: Calling adjustment service")
        
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
        
        # ====================================================================
        # STEP 3: Call Matching Service (YOUR EXISTING CODE)
        # ====================================================================
        logger.info("🔍 Step 3: Calling matching service")
        
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
        
        logger.info(f"✅ Matching complete (score: {matching_result.get('similarity_score', 0)}%)")
        
        # ====================================================================
        # STEP 4: Decide Next Steps
        # ====================================================================
        
        # Check if we have a good match
        if matching_result['match_found'] and matching_result['similarity_score'] >= 80:
            # ✅ SUCCESS - Good answer match!
            logger.info("🎉 Good answer match found!")
            
            # ================================================================
            # STEP 5: Calculate Score with Bonus-Malus
            # ================================================================
            logger.info("💯 Step 5: Calculating interaction score")
            
            # Get user level for scoring
            async with db_pool.acquire() as conn:
                user_level = await conn.fetchval("""
                    SELECT sc.cycle_level
                    FROM session_interaction si
                    JOIN session_cycle sc ON si.cycle_id = sc.id
                    WHERE si.id = $1
                """, interaction_id) or 100
            
            # Calculate base score using scoring service
            interaction_score = await scoring_service.calculate_interaction_score(
                interaction_id=interaction_id,
                matched_answer_id=matching_result.get('answer_id'),
                similarity_score=matching_result['similarity_score'],
                user_id=user_id,
                user_level=user_level,
                db_pool=db_pool
            )
            
            logger.info(f"✅ Score calculated: {interaction_score}")
            
            # ================================================================
            # STEP 6: Mark as Final Answer & Complete Interaction
            # ================================================================
            logger.info("✅ Step 6: Completing interaction")
            
            await answer_service.mark_as_final_answer(
                answer_id=answer_id,
                processing_method="answer_match",
                cost_saved=0.002,  # Saved GPT call
                db_pool=db_pool
            )
            
            # Complete the interaction
            await interaction_service.complete_interaction(
                interaction_id=interaction_id,
                final_answer_id=answer_id,
                interaction_score=interaction_score,
                db_pool=db_pool
            )
            
            # Check if cycle is complete
            async with db_pool.acquire() as conn:
                cycle_id = await conn.fetchval("""
                    SELECT cycle_id FROM session_interaction WHERE id = $1
                """, interaction_id)
            
            cycle_complete = await interaction_service.check_cycle_complete(
                cycle_id, db_pool
            )
            
            if cycle_complete:
                logger.info("🎊 Cycle completed!")
                await cycle_service.complete_cycle(cycle_id, db_pool)
            
            # ================================================================
            # STEP 7: Return Success Response
            # ================================================================
            return {
                "answer_id": answer_id,
                "status": "success",
                "method": "answer_match",
                "similarity_score": matching_result['similarity_score'],
                "interaction_score": interaction_score,
                "interaction_complete": True,
                "cycle_complete": cycle_complete,
                "feedback": _get_feedback_for_score(interaction_score),
                "gpt_used": False,
                "cost_saved": 0.002
            }
        
        else:
            # ⚠️ NO GOOD MATCH - User needs to try again
            logger.info("⚠️ No good match - user should retry")
            
            # Option: Check if we should try GPT fallback
            # (This is optional - you can implement GPT fallback here if needed)
            
            return {
                "answer_id": answer_id,
                "status": "retry",
                "method": "no_match",
                "similarity_score": matching_result.get('similarity_score', 0),
                "interaction_score": 0,
                "interaction_complete": False,
                "cycle_complete": False,
                "feedback": _get_retry_feedback(matching_result.get('similarity_score', 0)),
                "gpt_used": False,
                "cost_saved": 0
            }
        
    except Exception as e:
        logger.error(f"❌ Error processing answer: {e}", exc_info=True)
        raise


# ============================================================================
# Helper Functions
# ============================================================================

def _get_feedback_for_score(score: int) -> str:
    """Get user-friendly feedback based on score"""
    if score >= 90:
        return "Excellent! Perfect answer! 🌟"
    elif score >= 80:
        return "Very good! Well done! 👍"
    elif score >= 70:
        return "Good job! 👌"
    elif score >= 60:
        return "Not bad! Keep practicing! 💪"
    else:
        return "Keep trying! You're learning! 📚"


def _get_retry_feedback(similarity: float) -> str:
    """Get user-friendly feedback for retry"""
    if similarity >= 60:
        return "Close! Try to be more specific. 🎯"
    elif similarity >= 40:
        return "You're on the right track. Try again! 💪"
    else:
        return "Not quite. Listen carefully and try again! 👂"
