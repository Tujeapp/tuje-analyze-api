from fastapi import FastAPI, Request, Header, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
from rapidfuzz import fuzz
import uvicorn
import re

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

# Helper function to extract vocabulary
def find_vocabulary(transcription, vocab_list):
    found = []
    entities = {}
    already_matched = []

    # Sort vocab by length to match longest phrases first
    for vocab in sorted(vocab_list, key=lambda v: len(v.phrase), reverse=True):
        pattern = r'\b{}\b'.format(re.escape(vocab.phrase.lower()))
        match = re.search(pattern, transcription.lower())
        if match:
            span = match.span()
            if any(start < span[1] and end > span[0] for start, end in already_matched):
                continue
            found.append(vocab.phrase)
            already_matched.append(span)

            # Entity extraction pattern (optional enhancement)
            if vocab.phrase.startswith("entity"):
                entities[vocab.phrase] = match.group()

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
