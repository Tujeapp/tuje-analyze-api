# gpt_fallback_service.py
"""
Main service for GPT-powered intent detection from original transcripts
Follows the same architecture pattern as matching_answer_service.py
"""
import asyncpg
import logging
import time
import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import openai

from gpt_fallback_types import IntentCandidate, GPTFallbackResponse

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

class GPTFallbackService:
    """
    Core service for GPT-powered intent detection from original transcripts
    Handles intent loading, GPT analysis, and cost optimization
    """
    
    def __init__(self):
        self.intent_cache = {}
        self.cache_ttl_seconds = 600  # 10 minutes for intents (less volatile than vocab)
        self.cache_timestamp = None
        self.gpt_model = "gpt-4o-mini"  # Cost-effective choice
        self.default_threshold = 70
        
    async def analyze_intent(
        self,
        interaction_id: str,
        original_transcript: str,
        threshold: int = 70,
        custom_intent_ids: Optional[List[str]] = None,
        pool: Optional[asyncpg.Pool] = None
    ) -> Dict:
        """
        Main method to analyze original transcript for intent detection
        
        Args:
            interaction_id: The interaction to get relevant intents for
            original_transcript: Raw user transcript (before adjustment)
            threshold: Minimum confidence score (0-100)
            custom_intent_ids: Optional override for intent candidates
            pool: Optional database connection pool
            
        Returns:
            Dict with intent detection results
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
                # Step 1: Get relevant intent candidates
                intent_candidates = await self._get_interaction_intents(
                    interaction_id, custom_intent_ids, pool
                )
                
                if not intent_candidates:
                    logger.warning(f"No intent candidates found for interaction_id: {interaction_id}")
                    return self._create_no_candidates_result(
                        interaction_id, original_transcript, threshold, 
                        time.time() - start_time
                    )
                
                logger.info(f"Analyzing '{original_transcript}' against {len(intent_candidates)} intent candidates")
                
                # Step 2: Call GPT for intent analysis
                gpt_result = await self._analyze_with_gpt(
                    original_transcript, intent_candidates, threshold
                )
                
                # Step 3: Process GPT response and find matching intent
                processing_time = time.time() - start_time
                
                if gpt_result.get('matched_intent_id'):
                    # Find the full intent data
                    matched_intent = next(
                        (intent for intent in intent_candidates 
                         if intent.id == gpt_result['matched_intent_id']), 
                        None
                    )
                    
                    if matched_intent:
                        return self._create_success_result(
                            interaction_id, original_transcript, matched_intent,
                            gpt_result, threshold, processing_time
                        )
                
                # No match found above threshold
                return self._create_no_match_result(
                    interaction_id, original_transcript, threshold,
                    processing_time, gpt_result, len(intent_candidates)
                )
                    
            finally:
                if should_close_pool and pool:
                    await pool.close()
                    
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"GPT intent analysis failed for {interaction_id}: {e}")
            return self._create_error_result(
                interaction_id, original_transcript, threshold,
                processing_time, str(e)
            )
    
    async def _get_interaction_intents(
        self, 
        interaction_id: str, 
        custom_intent_ids: Optional[List[str]],
        pool: asyncpg.Pool
    ) -> List[IntentCandidate]:
        """
        Get relevant intent candidates for the interaction
        Uses brain_interaction.intents field or custom list
        """
        try:
            async with pool.acquire() as conn:
                if custom_intent_ids:
                    # Use custom intent list
                    logger.info(f"Using custom intent IDs: {custom_intent_ids}")
                    intent_rows = await conn.fetch("""
                        SELECT id, name, description
                        FROM brain_intent
                        WHERE id = ANY($1) AND live = TRUE
                        ORDER BY name ASC
                    """, custom_intent_ids)
                else:
                    # Get intents from interaction
                    interaction_row = await conn.fetchrow("""
                        SELECT intents
                        FROM brain_interaction
                        WHERE id = $1 AND live = TRUE
                    """, interaction_id)
                    
                    if not interaction_row or not interaction_row['intents']:
                        logger.warning(f"No intents found in brain_interaction for {interaction_id}")
                        return []
                    
                    intent_ids = interaction_row['intents']
                    logger.info(f"Found {len(intent_ids)} intent IDs in interaction: {intent_ids}")
                    
                    intent_rows = await conn.fetch("""
                        SELECT id, name, description
                        FROM brain_intent
                        WHERE id = ANY($1) AND live = TRUE
                        ORDER BY name ASC
                    """, intent_ids)
                
                # Convert to IntentCandidate objects
                candidates = []
                for row in intent_rows:
                    candidates.append(IntentCandidate(
                        id=row['id'],
                        name=row['name'],
                        description=row['description'] or f"Intent: {row['name']}"
                    ))
                
                logger.info(f"Loaded {len(candidates)} intent candidates")
                return candidates
                
        except Exception as e:
            logger.error(f"Failed to get interaction intents: {e}")
            raise
    
    async def _analyze_with_gpt(
        self, 
        original_transcript: str, 
        intent_candidates: List[IntentCandidate],
        threshold: int
    ) -> Dict:
        """
        Call GPT to analyze the transcript against intent candidates
        Optimized for cost and accuracy
        """
        # Build intent options for GPT
        intent_options = []
        for intent in intent_candidates:
            intent_line = f"- {intent.name} [ID: {intent.id}] - {intent.description}"
            intent_options.append(intent_line)
        
        # Create optimized prompt
        prompt = f"""Tu es un expert en analyse d'intentions pour l'apprentissage du français.

L'apprenant a dit (transcription vocale brute): "{original_transcript}"

INTENTIONS POSSIBLES pour cette interaction:
{chr(10).join(intent_options)}

TÂCHE:
Analyse ce que l'utilisateur essaie de dire, même si la transcription est imparfaite.
Trouve l'intention la plus proche dans la liste ci-dessus.

RÈGLES IMPORTANTES:
- Concentre-toi sur l'INTENTION plutôt que la grammaire parfaite
- Considère les erreurs de transcription vocale (mots coupés, sons similaires)
- Sois tolérant aux fautes et approximations
- Si AUCUNE intention ne correspond bien (score < {threshold}), retourne "no_match"

RÉPONSE REQUISE (JSON uniquement):
Si une intention correspond (score >= {threshold}):
{{
  "matched_intent_name": "introduce_self",
  "matched_intent_id": "INTENT202508010901",
  "confidence_score": 85,
  "reasoning": "L'utilisateur essaie de se présenter malgré la transcription imparfaite"
}}

Si AUCUNE intention ne correspond (score < {threshold}):
{{
  "matched_intent_name": null,
  "matched_intent_id": null,
  "confidence_score": 30,
  "reasoning": "Aucune intention ne correspond clairement",
  "alternative_interpretation": "L'utilisateur semble vouloir [votre interprétation libre]"
}}

Réponds UNIQUEMENT avec le JSON, sans explication supplémentaire."""

        try:
            logger.info(f"Calling GPT with {len(intent_candidates)} intent candidates")
            
            response = await openai.ChatCompletion.acreate(  # Use async version
                model=self.gpt_model,
                messages=[
                    {
                        "role": "system",
                        "content": "Tu es un assistant expert en compréhension des intentions d'apprenants français. Réponds uniquement en JSON structuré."
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                temperature=0.1,  # Low for consistent analysis
                max_tokens=250,   # Sufficient for structured response
                timeout=30        # Prevent hanging
            )
            
            content = response.choices[0].message["content"].strip()
            
            # Clean and parse JSON response
            content = self._clean_gpt_json_response(content)
            gpt_data = json.loads(content)
            
            # Add cost estimation
            gpt_data['cost_estimate_usd'] = self._estimate_gpt_cost(response)
            
            logger.info(f"GPT analysis result: matched={gpt_data.get('matched_intent_id')}, "
                       f"confidence={gpt_data.get('confidence_score')}, "
                       f"cost=${gpt_data.get('cost_estimate_usd'):.6f}")
            
            return gpt_data
            
        except json.JSONDecodeError as e:
            logger.error(f"GPT returned invalid JSON: {content}")
            return {
                "matched_intent_name": None,
                "matched_intent_id": None,
                "confidence_score": 0,
                "reasoning": "Erreur de parsing GPT",
                "alternative_interpretation": "Réponse GPT non analysable"
            }
        except Exception as e:
            logger.error(f"GPT API error: {str(e)}")
            raise
    
    def _clean_gpt_json_response(self, content: str) -> str:
        """Clean GPT response to extract valid JSON"""
        content = content.strip()
        
        # Remove markdown code blocks
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        elif content.startswith("```"):
            content = content.replace("```", "").strip()
        
        return content
    
    def _estimate_gpt_cost(self, response) -> float:
        """Estimate cost for GPT-4o-mini usage"""
        try:
            usage = response.get('usage', {})
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)
            
            # GPT-4o-mini pricing (as of 2024)
            input_cost = prompt_tokens * (0.000150 / 1000)    # $0.000150 per 1K tokens
            output_cost = completion_tokens * (0.000600 / 1000) # $0.000600 per 1K tokens
            
            return round(input_cost + output_cost, 8)
        except:
            return 0.001  # Fallback estimate
    
    def _create_success_result(
        self, 
        interaction_id: str, 
        original_transcript: str,
        matched_intent: IntentCandidate,
        gpt_result: Dict,
        threshold: int, 
        processing_time: float
    ) -> Dict:
        """Create successful intent match result"""
        return {
            "interaction_id": interaction_id,
            "original_transcription": original_transcript,
            "intent_matched": True,
            "intent_id": matched_intent.id,
            "intent_name": matched_intent.name,
            "similarity_score": gpt_result.get('confidence_score'),
            "threshold": threshold,
            "candidates_analyzed": 1,  # Will be updated by caller
            "gpt_reasoning": gpt_result.get('reasoning'),
            "processing_time_ms": round(processing_time * 1000, 2),
            "cost_estimate_usd": gpt_result.get('cost_estimate_usd'),
            "timestamp": datetime.now().isoformat()
        }
    
    def _create_no_match_result(
        self, 
        interaction_id: str, 
        original_transcript: str,
        threshold: int, 
        processing_time: float,
        gpt_result: Dict,
        candidates_count: int
    ) -> Dict:
        """Create no match result"""
        return {
            "interaction_id": interaction_id,
            "original_transcription": original_transcript,
            "intent_matched": False,
            "intent_id": None,
            "intent_name": None,
            "similarity_score": gpt_result.get('confidence_score'),
            "threshold": threshold,
            "candidates_analyzed": candidates_count,
            "gpt_reasoning": gpt_result.get('reasoning'),
            "gpt_alternative_interpretation": gpt_result.get('alternative_interpretation'),
            "processing_time_ms": round(processing_time * 1000, 2),
            "cost_estimate_usd": gpt_result.get('cost_estimate_usd'),
            "timestamp": datetime.now().isoformat()
        }
    
    def _create_no_candidates_result(
        self, 
        interaction_id: str, 
        original_transcript: str,
        threshold: int, 
        processing_time: float
    ) -> Dict:
        """Create result when no intent candidates available"""
        return {
            "interaction_id": interaction_id,
            "original_transcription": original_transcript,
            "intent_matched": False,
            "intent_id": None,
            "intent_name": None,
            "similarity_score": None,
            "threshold": threshold,
            "candidates_analyzed": 0,
            "gpt_reasoning": "No intent candidates found for this interaction",
            "processing_time_ms": round(processing_time * 1000, 2),
            "error": "no_candidates_available",
            "timestamp": datetime.now().isoformat()
        }
    
    def _create_error_result(
        self, 
        interaction_id: str, 
        original_transcript: str,
        threshold: int, 
        processing_time: float, 
        error_message: str
    ) -> Dict:
        """Create error result"""
        return {
            "interaction_id": interaction_id,
            "original_transcription": original_transcript,
            "intent_matched": False,
            "intent_id": None,
            "intent_name": None,
            "similarity_score": None,
            "threshold": threshold,
            "candidates_analyzed": 0,
            "processing_time_ms": round(processing_time * 1000, 2),
            "error": error_message,
            "timestamp": datetime.now().isoformat()
        }
    
    async def get_service_stats(self) -> Dict:
        """Get service statistics for monitoring"""
        return {
            "service_name": "gpt_fallback_service",
            "gpt_model": self.gpt_model,
            "default_threshold": self.default_threshold,
            "cache_status": {
                "enabled": bool(self.intent_cache),
                "ttl_seconds": self.cache_ttl_seconds,
                "last_refresh": self.cache_timestamp
            },
            "cost_optimization_tips": [
                "Use specific interaction intents instead of custom lists",
                "Batch similar requests when possible",
                "Consider caching intent analysis results for identical transcripts",
                f"Current model ({self.gpt_model}) is cost-optimized"
            ]
        }

# Global service instance
gpt_fallback_service = GPTFallbackService()
