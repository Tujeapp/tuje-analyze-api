from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
import json
import openai
import logging

from config import OPENAI_API_KEY

router = APIRouter()
logger = logging.getLogger(__name__)

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

@router.post("/bubble-gpt-fallback", response_model=GPTIntentAnalysisResponse)
async def bubble_gpt_fallback(request: BubbleGPTFallbackRequest):
    """
    GPT fallback that works with Bubble's pre-filtered intent list.
    
    Your workflow:
    1. Bubble filters intents based on interaction context (from brain_intent table)
    2. Sends filtered list to this endpoint  
    3. GPT tries to match user answer to filtered intents
    4. If no match, GPT provides its own intent interpretation
    5. Returns structured response for Bubble to process
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
            temperature=0.1,  # Low for consistent analysis
            max_tokens=200    # Sufficient for structured response
        )
        
        content = response.choices[0].message["content"].strip()
        
        # Clean JSON response
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        elif content.startswith("```"):
            content = content.replace("```", "").strip()
        
        return json.loads(content)
        
    except json.JSONDecodeError as e:
        logger.error(f"GPT returned invalid JSON: {content}")
        # Fallback response structure
        return {
            "matched_intent_name": "other",
            "matched_intent_id": None,
            "confidence_score": 0,
            "reasoning": "Erreur de parsing GPT",
            "gpt_own_interpretation": "Réponse non analysable"
        }
    except Exception as e:
        logger.error(f"OpenAI API error: {str(e)}")
        raise

def process_filtered_intent_response(
    gpt_response: Dict, 
    filtered_intents: List[BubbleFilteredIntent],
    threshold: int
) -> GPTIntentAnalysisResponse:
    """
    Process GPT response and create structured result for Bubble
    """
    
    matched_intent_name = gpt_response.get("matched_intent_name")
    matched_intent_id = gpt_response.get("matched_intent_id")
    confidence = gpt_response.get("confidence_score", 0)
    
    # Validate that the matched intent actually exists in the filtered list
    if matched_intent_name != "other" and matched_intent_id:
        intent_found = False
        for intent in filtered_intents:
            if intent.id == matched_intent_id and intent.name == matched_intent_name:
                intent_found = True
                break
        
        # If GPT returned an invalid intent, treat as "other"
        if not intent_found:
            logger.warning(f"GPT returned invalid intent: {matched_intent_id}/{matched_intent_name}")
            matched_intent_name = "other"
            matched_intent_id = None
    
    # Handle "other" case - extract GPT's own interpretation
    gpt_suggested_intent = None
    if matched_intent_name == "other":
        gpt_suggested_intent = gpt_response.get("gpt_own_interpretation")
        matched_intent_id = None
        matched_intent_name = None
    
    # Calculate cost estimate
    cost_estimate = estimate_mini_cost(gpt_response, len(filtered_intents))
    
    return GPTIntentAnalysisResponse(
        matched_intent_id=matched_intent_id,
        matched_intent_name=matched_intent_name,
        confidence_score=confidence,
        gpt_suggested_intent=gpt_suggested_intent,
        reasoning=gpt_response.get("reasoning", "Aucune raison fournie"),
        cost_estimate=cost_estimate
    )

def estimate_mini_cost(response_data: Dict, num_intents: int) -> float:
    """
    Estimate GPT-4o-mini cost based on actual usage
    """
    # Token estimation for your use case
    base_prompt_tokens = 180 + (num_intents * 12)  # Base prompt + intent list
    user_input_tokens = len(str(response_data.get("user_input", ""))) / 4
    response_tokens = len(str(response_data)) / 4
    
    total_input_tokens = base_prompt_tokens + user_input_tokens
    
    # GPT-4o-mini pricing (input: $0.000150/1K, output: $0.000600/1K)
    input_cost = total_input_tokens * (0.000150 / 1000)
    output_cost = response_tokens * (0.000600 / 1000)
    
    return round(input_cost + output_cost, 6)

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
    
