# matching_answer_service.py
"""
Main service for matching completed transcripts against saved interaction answers
Follows the same architecture pattern as the transcription adjustment service
"""
import asyncpg
import logging
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import os
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")

class AnswerMatchingService:
    """
    Core service for matching completed transcripts against interaction answers
    Handles caching, fuzzy matching, and result ranking
    """
    
    def __init__(self):
        self.answer_cache = {}
        self.cache_ttl_seconds = 300  # 5 minutes
        self.cache_timestamp = None
        
    async def match_completed_transcript(
        self, 
        interaction_id: str, 
        completed_transcript: str,
        threshold: int = 80,
        pool: Optional[asyncpg.Pool] = None
    ) -> Dict:
        """
        Main method to match a completed transcript against interaction answers
        
        Args:
            interaction_id: The interaction to find answers for
            completed_transcript: The processed transcript from adjustment service
            threshold: Minimum similarity score (0-100)
            pool: Optional database connection pool
            
        Returns:
            Dict with match results or None if no match above threshold
        """
        start_time = time.time()
        
        try:
            # Get or create connection pool
            if pool is None:
                pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
                should_close_pool = True
            else:
                should_close_pool = False
            
            try:
                # Step 1: Get all possible answers for this interaction
                possible_answers = await self._get_interaction_answers(interaction_id, pool)
                
                if not possible_answers:
                    logger.warning(f"No answers found for interaction_id: {interaction_id}")
                    return self._create_no_match_result(
                        interaction_id, completed_transcript, threshold, 
                        time.time() - start_time, "no_answers_found"
                    )
                
                # Step 2: Match transcript against all possible answers
                match_results, best_score, best_expected = await self._match_against_answers(
                    completed_transcript, possible_answers, threshold
                )
                
                # Step 3: Return best match or no match result
                processing_time = time.time() - start_time
                
                if match_results:
                    best_match = match_results[0]  # Already sorted by score
                    return self._create_match_result(
                        interaction_id, completed_transcript, best_match, 
                        threshold, processing_time
                    )
                else:
                    return self._create_no_match_result(
                        interaction_id, completed_transcript, threshold,
                        processing_time, "below_threshold",
                        best_similarity_score=best_score,
                        best_expected_transcript=best_expected
                    )
                    
            finally:
                if should_close_pool and pool:
                    await pool.close()
                    
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Answer matching failed for {interaction_id}: {e}")
            return self._create_error_result(
                interaction_id, completed_transcript, threshold,
                processing_time, str(e)
            )
    
    async def _get_interaction_answers(
        self, 
        interaction_id: str, 
        pool: asyncpg.Pool
    ) -> List[Dict]:
        """
        Get all possible answers for an interaction from the junction table
        Returns list of answer data with interaction_answer_id
        """
        try:
            async with pool.acquire() as conn:
                # Join all three tables to get complete answer data
                rows = await conn.fetch("""
                    SELECT 
                        ia.id as interaction_answer_id,
                        ia.interaction_id,
                        ia.answer_id,
                        a.transcription_fr,
                        a.transcription_en,
                        a.transcription_adjusted,
                        a.live as answer_live
                    FROM brain_interaction_answer ia
                    JOIN brain_answer a ON ia.answer_id = a.id
                    JOIN brain_interaction i ON ia.interaction_id = i.id
                    WHERE ia.interaction_id = $1 
                    AND ia.live = TRUE 
                    AND a.live = TRUE 
                    AND i.live = TRUE
                    ORDER BY a.created_at ASC
                """, interaction_id)
                
                results = []
                for row in rows:
                    results.append({
                        'interaction_answer_id': row['interaction_answer_id'],
                        'interaction_id': row['interaction_id'],
                        'answer_id': row['answer_id'],
                        'transcription_fr': row['transcription_fr'],
                        'transcription_en': row['transcription_en'],
                        'transcription_adjusted': row['transcription_adjusted'],
                        'answer_live': row['answer_live']
                    })
                
                logger.info(f"Found {len(results)} possible answers for interaction {interaction_id}")
                return results
                
        except Exception as e:
            logger.error(f"Failed to get interaction answers: {e}")
            raise
    
    async def _match_against_answers(
        self, 
        completed_transcript: str, 
        possible_answers: List[Dict],
        threshold: int
    ) -> Tuple[List[Dict], float, str]:
        """
        Match the completed transcript against all possible answers using fuzzy matching
        Returns: (matches_above_threshold, best_score_overall, best_expected_transcript)
        """
        matches_above_threshold = []
        all_scores = []
        completed_transcript_clean = completed_transcript.strip().lower()
        
        logger.info(f"Matching '{completed_transcript_clean}' against {len(possible_answers)} answers")
        
        for answer_data in possible_answers:
            # Use transcription_adjusted for matching (same as adjustment service)
            expected_transcript = answer_data['transcription_adjusted'].strip().lower()
            
            # Calculate similarity using rapidfuzz (same as your existing code)
            similarity_score = fuzz.ratio(completed_transcript_clean, expected_transcript)
            
            logger.debug(f"  Answer {answer_data['answer_id']}: '{expected_transcript}' -> {similarity_score:.1f}%")
            
            # Keep track of all scores for debugging
            all_scores.append({
                'score': similarity_score,
                'expected': expected_transcript,
                'answer_data': answer_data
            })
            
            # Only include in results if above threshold
            if similarity_score >= threshold:
                match_data = answer_data.copy()
                match_data['similarity_score'] = round(similarity_score, 1)
                match_data['expected_transcript'] = expected_transcript
                matches_above_threshold.append(match_data)
        
        # Sort matches above threshold by similarity score (highest first)
        matches_above_threshold.sort(key=lambda x: x['similarity_score'], reverse=True)
        
        # Find the overall best score (even if below threshold) for debugging
        best_overall = max(all_scores, key=lambda x: x['score']) if all_scores else None
        best_score_overall = best_overall['score'] if best_overall else 0
        best_expected_overall = best_overall['expected'] if best_overall else None
        
        logger.info(f"Found {len(matches_above_threshold)} matches above threshold {threshold}%")
        logger.info(f"Best overall score: {best_score_overall:.1f}% for '{best_expected_overall}'")
        
        if matches_above_threshold:
            logger.info(f"Best qualifying match: {matches_above_threshold[0]['similarity_score']:.1f}% for answer {matches_above_threshold[0]['answer_id']}")
        
        return matches_above_threshold, best_score_overall, best_expected_overall
    
    def _create_match_result(
        self, 
        interaction_id: str, 
        completed_transcript: str,
        best_match: Dict, 
        threshold: int, 
        processing_time: float
    ) -> Dict:
        """Create successful match result"""
        return {
            "match_found": True,
            "interaction_id": interaction_id,
            "completed_transcription": completed_transcript,  # Note: keeping your naming
            "interaction_answer_id": best_match['interaction_answer_id'],
            "answer_id": best_match['answer_id'],
            "threshold": threshold,
            "similarity_score": best_match['similarity_score'],
            "expected_transcript": best_match['expected_transcript'],
            "answer_details": {
                "transcription_fr": best_match['transcription_fr'],
                "transcription_en": best_match['transcription_en'],
                "transcription_adjusted": best_match['transcription_adjusted']
            },
            "processing_time_ms": round(processing_time * 1000, 2),
            "timestamp": datetime.now().isoformat()
        }
    
    def _create_no_match_result(
        self, 
        interaction_id: str, 
        completed_transcript: str,
        threshold: int, 
        processing_time: float, 
        reason: str,
        best_similarity_score: float = None,
        best_expected_transcript: str = None
    ) -> Dict:
        """Create no match result with best attempt info"""
        return {
            "match_found": False,
            "interaction_id": interaction_id,
            "completed_transcription": completed_transcript,
            "interaction_answer_id": None,
            "answer_id": None,
            "threshold": threshold,
            "similarity_score": best_similarity_score,  # Show best score even if below threshold
            "expected_transcript": best_expected_transcript,  # Show what was closest
            "reason": reason,
            "processing_time_ms": round(processing_time * 1000, 2),
            "timestamp": datetime.now().isoformat()
        }
    
    def _create_error_result(
        self, 
        interaction_id: str, 
        completed_transcript: str,
        threshold: int, 
        processing_time: float, 
        error_message: str
    ) -> Dict:
        """Create error result"""
        return {
            "match_found": False,
            "interaction_id": interaction_id,
            "completed_transcription": completed_transcript,
            "interaction_answer_id": None,
            "answer_id": None,
            "threshold": threshold,
            "error": error_message,
            "processing_time_ms": round(processing_time * 1000, 2),
            "timestamp": datetime.now().isoformat()
        }
    
    async def get_service_stats(self) -> Dict:
        """Get service statistics for monitoring"""
        return {
            "service_name": "answer_matching_service",
            "cache_status": {
                "enabled": bool(self.answer_cache),
                "ttl_seconds": self.cache_ttl_seconds,
                "last_refresh": self.cache_timestamp
            },
            "default_threshold": 80,
            "fuzzy_matching_algorithm": "rapidfuzz.fuzz.ratio"
        }

# Global service instance
answer_matching_service = AnswerMatchingService()
