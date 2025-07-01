from fastapi import FastAPI, Request, Header, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
from rapidfuzz import fuzz
import uvicorn
import re

def find_vocab_in_order(transcription: str, vocabulary_list: List[Dict]) -> List[str]:
    transcription_lower = transcription.lower()
    vocab_phrases = [v["phrase"].lower() for v in vocabulary_list]

    # Sort longer phrases first so "un chat orange" comes before "chat"
    vocab_phrases.sort(key=lambda x: -len(x))

    matches = []
    matched_spans = []

    for phrase in vocab_phrases:
        for match in re.finditer(r'\b' + re.escape(phrase) + r'\b', transcription_lower):
            start, end = match.start(), match.end()

            # Avoid overlapping matches (e.g., don't match both "chat" and "un chat orange")
            if all(end <= s or start >= e for s, e in matched_spans):
                matches.append((start, phrase))
                matched_spans.append((start, end))
                break  # Only take first occurrence per phrase

    # Sort matches by appearance order in transcription
    matches.sort(key=lambda m: m[0])

    return [phrase for _, phrase in matches]

app = FastAPI()

# Optional API key for secure access
API_KEY = "tuje-secure-key"

# Data models
class VocabularyEntry(BaseModel):
    phrase: str

class SavedAnswer(BaseModel):
    text: str
    is_correct: bool

class MatchRequest(BaseModel):
    transcription: str
    saved_answers: List[SavedAnswer]
    vocabulary_list: List[VocabularyEntry]
    threshold: Optional[int] = 85

class MatchResponse(BaseModel):
    matched_vocab: List[str]
    matched_entities: Dict[str, str]
    matches: List[Dict]
    call_gpt: bool

class GPTFallbackRequest(BaseModel):
    transcription: str
    matched_vocab: List[str]
    candidate_answers: Optional[List[SavedAnswer]] = []

@app.post("/gpt-fallback")
async def gpt_fallback(request: GPTFallbackRequest):
    import openai
    openai.api_key = "YOUR-OPENAI-API-KEY"  # Use Render ENV later

    # Format candidate answers
    candidates_text = "\n".join([f"- {a.text}" for a in request.candidate_answers]) if request.candidate_answers else "Aucun exemple"

    prompt = f"""
Tu es un assistant pour les apprenants de français. Voici une transcription vocale imparfaite :  
"{request.transcription}"

Voici le vocabulaire reconnu : {', '.join(request.matched_vocab)}

Voici quelques réponses attendues ou acceptables :
{candidates_text}

Analyse la réponse. Réponds uniquement en JSON avec les champs suivants :
- intent_match (yes/no)
- intent_topic (résumé du sens de la phrase)
- correct_french (la phrase corrigée)
- correction_type (e.g., vocabulaire, grammaire, ordre des mots)
- user_level_guess (A1/A2/B1...)
- feedback_message (message d'encouragement en français)
Réponds uniquement en JSON.
"""

    completion = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Tu es un assistant qui analyse les réponses d'apprenants de français."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )

    # Extract JSON from response
    content = completion.choices[0].message["content"]

    try:
        import json
        return json.loads(content)
    except:
        return {"error": "Invalid GPT response", "raw": content}

# Helper function to extract vocabulary
def find_vocabulary(transcription, vocab_list):
    transcription_lower = transcription.lower()
    phrases = [(v.phrase.lower(), v.phrase) for v in vocab_list]  # (lowered, original)

    # Sort by longer phrases first
    phrases.sort(key=lambda x: -len(x[0]))

    matches = []
    matched_spans = []
    entities = {}

    for lowered, original in phrases:
        for match in re.finditer(r'\b' + re.escape(lowered) + r'\b', transcription_lower):
            start, end = match.start(), match.end()

            # Avoid overlap
            if all(end <= s or start >= e for s, e in matched_spans):
                matches.append((start, original))
                matched_spans.append((start, end))

                if original.startswith("entity"):
                    entities[original] = match.group()
                break  # Only keep first occurrence of each phrase

    # Sort matches by appearance order
    matches.sort(key=lambda x: x[0])
    found = [phrase for _, phrase in matches]

    return found, entities

# Helper function to find best matching saved answers
def match_saved_answers(transcription, saved_answers, threshold):
    results = []

    for answer in saved_answers:
        score = fuzz.ratio(transcription.lower(), answer.text.lower())
        if score >= threshold:
            results.append({
                "matched_text": answer.text,
                "is_correct": answer.is_correct,
                "score": score
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results

@app.post("/analyze", response_model=MatchResponse)
async def analyze(request: MatchRequest, authorization: Optional[str] = Header(None)):
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    vocab_found, entities_found = find_vocabulary(request.transcription, request.vocabulary_list)
    saved_matches = match_saved_answers(request.transcription, request.saved_answers, request.threshold)

    return {
        "matched_vocab": vocab_found,
        "matched_entities": entities_found,
        "matches": saved_matches,
        "call_gpt": len(saved_matches) == 0
    }

# For local testing
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
