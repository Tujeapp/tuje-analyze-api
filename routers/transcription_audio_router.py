from fastapi import APIRouter, UploadFile, File, HTTPException
from openai import AsyncOpenAI
import os
import tempfile

router = APIRouter()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@router.post("/transcribe-audio")
async def transcribe_audio(audio: UploadFile = File(...)):
    """
    Accepts an audio file, sends to Whisper, returns transcript.
    Called by iOS app after recording.
    """
    try:
        # Save upload to temp file (Whisper needs a real file, not bytes)
        suffix = ".m4a"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await audio.read()
            tmp.write(content)
            tmp_path = tmp.name

        # Call Whisper
        with open(tmp_path, "rb") as f:
            response = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="fr"  # French — faster and more accurate
            )

        # Clean up temp file
        os.unlink(tmp_path)

        return {
            "success": True,
            "transcript": response.text,
            "language": "fr"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
