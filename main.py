from fastapi import FastAPI, Request, Header, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
from rapidfuzz import fuzz
import uvicorn
import re
import os
import json
import openai

app = FastAPI()
API_KEY = "tuje-secure-key"

# ----------------------
# Data models
# ----------------------
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

class ScanVocabRequest(BaseModel):
    transcription: str
    vocabulary_phrases: List[str]

# ----------------------
# Helper functions
# ----------------------
def extract_vocab_sequence(transcription: str, vocab_phrases: List[str]) -> List[str]:
    transcription = transcription.lower()
    vocab_phrases = sorted(vocab_phrases, key=lambda p: -len(p))  # Match longest phrases first

    matches = []
    used_spans = []

    for phrase in vocab_phrases:
        pattern = r'\b' + re.escape(phrase) + r'\b'
        for match in re.finditer(pattern, transcription):
            start, end = match.span()
            if all(end <= s or start >= e for s, e in used_spans):
                matches.append((start, end, phrase))
                used_spans.append((start, end))
                break

    matches.sort(key=lambda m: m[0])  # Sort by order of appearance
    result = []
    last_end = 0

    for start, end, phrase in matches:
        gap_text = transcription[last_end:start]
        if gap_text.strip():  # If there's a non-space gap
            result.append("vocabNotFound")
        result.append(phrase)
        last_end = end

    trailing_text = transcription[last_end:]
    if trailing_text.strip():
        result.append("vocabNotFound")

    return result

def find_vocabulary(transcription, vocab_list):
    transcription_lower = transcription.lower()
    phrases = [(v.phrase.lower(), v.phrase) for v in vocab_list]
    phrases.sort(key=lambda x: -len(x[0]))

    matches = []
    matched_spans = []
    entities = {}

    for lowered, original in phrases:
        for match in re.finditer(r'\b' + re.escape(lowered) + r'\b', transcription_lower):
            start, end = match.start(), match.end()
            if all(end <= s or start >= e for s, e in matched_spans):
                matches.append((start, original))
                matched_spans.append((start, end))
                if original.startswith("entity"):
                    entities[original] = match.group()
                break

    matches.sort(key=lambda x: x[0])
    found = [phrase for _, phrase in matches]
    return found, entities

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

# ----------------------
# Main /analyze endpoint
# ----------------------
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

# ----------------------
# GPT fallback endpoint
# ----------------------
@app.post("/gpt-fallback")
async def gpt_fallback(request: GPTFallbackRequest):
    openai.api_key = os.getenv("OPENAI_API_KEY")

    try:
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

        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Tu es un assistant qui analyse les réponses d'apprenants de français."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=200
        )

        content = response.choices[0].message["content"]

        if content.strip().startswith("```"):
            content = content.strip("` \n").replace("json", "").strip()

        return json.loads(content)

    except Exception as e:
        return {
            "error": "Failed to parse GPT response",
            "raw_response": content if 'content' in locals() else "",
            "exception": str(e)
        }

# ----------------------
# Scan vocabulary endpoint
# ----------------------
@app.post("/scan-vocab")
async def scan_vocab(request: ScanVocabRequest):
    try:
        ordered_vocab = extract_vocab_sequence(request.transcription, request.vocabulary_phrases)
        return {"ordered_vocab": ordered_vocab}
    except Exception as e:
        return {"error": str(e)}

# ----------------------
# Local testing
# ----------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
