from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from config import DATABASE_URL, OPENAI_API_KEY
import asyncpg
import httpx

router = APIRouter()

# ----------- INPUT MODEL -----------
class MatchRequest(BaseModel):
    transcription: str
    matched_vocab: List[str]
    intent_options: List[str]

# ----------- RESPONSE MODEL -----------
class IntentResponse(BaseModel):
    intent_topic: str
    intent_confidence_score: int
    intent_GPT: str


# ----------------------
# Extract Ordered Vocab
# ----------------------
@app.post("/extract-ordered-vocab")
async def extract_ordered_vocab(request: ExtractOrderedRequest):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("SELECT id, transcription_fr, transcription_en, transcription_adjusted, airtable_record_id, last_modified_time_ref FROM brain_vocab")
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

        # Match based on transcriptionAdjusted
        for entry in sorted(vocab_entries, key=lambda e: -len(e.transcriptionAdjusted)):
            pattern = r'\b' + re.escape(entry.transcriptionAdjusted.lower()) + r'\b'
            for match in re.finditer(pattern, transcription):
                start, end = match.span()
                if all(end <= s or start >= e for s, e in used_spans):
                    used_spans.append((start, end))
                    matches.append((start, entry))
                    break

        matches.sort(key=lambda x: x[0])  # Sort by order of appearance

        results = []
        last_end = 0
        for start, entry in matches:
            gap_text = transcription[last_end:start]
            if gap_text.strip():  # If there's a non-space gap between last match and this one
                results.append({
                    "id": "vocabnotfound",
                    "transcriptionFr": "vocabnotfound",
                    "transcriptionEn": "not found",
                    "transcriptionAdjusted": "vocabnotfound"
                })
            results.append(entry.dict())
            last_end = start + len(entry.transcriptionAdjusted)

        # Check if there's leftover unmatched text at the end
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

