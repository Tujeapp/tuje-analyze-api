from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import asyncpg
import httpx
import difflib
import json
import re
import openai

from config import DATABASE_URL, OPENAI_API_KEY

router = APIRouter()


# -------------------------
# Models
# -------------------------
class VocabEntry(BaseModel):
    id: str
    transcriptionFr: str
    transcriptionEn: str
    transcriptionAdjusted: str
    airtableRecordId: Optional[str]
    lastModifiedTimeRef: Optional[int]

class ExtractOrderedRequest(BaseModel):
    transcription: str

class MatchAnswerRequest(BaseModel):
    interaction_id: str
    user_transcription: str
    threshold: int = 85

class MatchRequest(BaseModel):
    transcription: str
    matched_vocab: List[str]
    intent_options: List[str]

class GPTFallbackRequest(BaseModel):
    transcription: str
    intent_options: List[str]

class IntentResponse(BaseModel):
    intent_topic: str
    intent_confidence_score: int
    intent_GPT: str


# -------------------------
# Extract Ordered Vocab
# -------------------------
@router.post("/extract-ordered-vocab")
async def extract_ordered_vocab(request: ExtractOrderedRequest):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("""
            SELECT id, transcription_fr, transcription_en, transcription_adjusted, airtable_record_id, last_modified_time_ref
            FROM brain_vocab
        """)
        await conn.close()

        vocab_entries = [
            VocabEntry(
                id=row["id"],
                transcriptionFr=row["transcription_fr"],
                transcriptionEn=row["transcription_en"],
                transcriptionAdjusted=row["transcription_adjusted"],
                airtableRecordId=row["airtable_record_id"],
                lastModifiedTimeRef=row["last_modified_time_ref"]
            )
            for row in rows
        ]

        transcription = request.transcription.lower()
        matches = []
        used_spans = []

        for entry in sorted(vocab_entries, key=lambda e: -len(e.transcriptionAdjusted)):
            pattern = r'\b' + re.escape(entry.transcriptionAdjusted.lower()) + r'\b'
            for match in re.finditer(pattern, transcription):
                start, end = match.span()
                if all(end <= s or start >= e for s, e in used_spans):
                    used_spans.append((start, end))
                    matches.append((start, entry))
                    break

        matches.sort(key=lambda x: x[0])
        results = []
        last_end = 0

        for start, entry in matches:
            gap_text = transcription[last_end:start]
            if gap_text.strip():
                results.append({
                    "id": "vocabnotfound",
                    "transcriptionFr": "vocabnotfound",
                    "transcriptionEn": "not found",
                    "transcriptionAdjusted": "vocabnotfound"
                })
            results.append(entry.dict())
            last_end = start + len(entry.transcriptionAdjusted)

        if transcription[last_end:].strip():
            results.append({
                "id": "vocabnotfound",
                "transcriptionFr": "vocabnotfound",
                "transcriptionEn": "not found",
                "transcriptionAdjusted": "vocabnotfound"
            })

        return results

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------
# Match Answer to Interaction
# -------------------------
@router.post("/match-answer")
async def match_answer(req: MatchAnswerRequest):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("""
            SELECT a.id, a.transcription_fr, a.transcription_en, a.transcription_adjusted
            FROM brain_interaction_answer ia
            JOIN brain_answer a ON ia.answer_id = a.id
            WHERE ia.interaction_id = $1
        """, req.interaction_id)
        await conn.close()

        if not rows:
            raise HTTPException(status_code=404, detail="No answers linked to this interaction.")

        user_input = req.user_transcription.strip().lower()
        best_score = 0
        best_match = None

        for row in rows:
            expected = row["transcription_adjusted"].strip().lower()
            score = difflib.SequenceMatcher(None, user_input, expected).ratio() * 100

            if score > best_score:
                best_score = score
                best_match = {
                    "id": row["id"],
                    "transcriptionFr": row["transcription_fr"],
                    "transcriptionEn": row["transcription_en"],
                    "transcriptionAdjusted": row["transcription_adjusted"],
                    "score": round(score, 1)
                }

        if best_match and best_score >= req.threshold:
            return {
                "match_found": True,
                "call_gpt": False,
                "best_answer": best_match
            }

        return {
            "match_found": False,
            "call_gpt": True,
            "reason": f"No match passed threshold {req.threshold}",
            "best_attempt": best_match
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# -------------------------
# GPT Fallback Intent Matching
# -------------------------
@router.post("/gpt-fallback", response_model=IntentResponse)
async def gpt_fallback(request: GPTFallbackRequest):
    openai.api_key = OPENAI_API_KEY

    try:
        prompt = f"""
Détermine l’intention de l’utilisateur.

Transcription : "{request.transcription}"

Liste des intentions possibles :
{chr(10).join(f"- {opt}" for opt in request.intent_options)}

Règles :
- intent_name : choisis UNE et UNE SEULE intention depuis la liste fournie. Si aucune ne convient, écris "else".
- confidence_score : donne un score de confiance (0 à 100).
- intent_GPT : si intent_name est "else", donne l’intention libre proposée par GPT.

Réponds uniquement en JSON:
{{
  "intent_name": "...",
  "confidence_score": ...,
  "intent_GPT": "..."
}}
"""

        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "Tu es un assistant qui analyse les intentions des apprenants de français."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=200
        )

        content = response.choices[0].message["content"]

        # Clean output if wrapped in code block
        if content.strip().startswith("```"):
            content = content.strip("` \n").replace("json", "").strip()

        return IntentResponse(**json.loads(content))

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse GPT response: {str(e)}")
        
