from fastapi import APIRouter, UploadFile, File, HTTPException
from openai import AsyncOpenAI
import os
import tempfile
import logging

router = APIRouter()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
logger = logging.getLogger(__name__)

@router.post("/transcribe-audio")
async def transcribe_audio(audio: UploadFile = File(...)):
    try:
        suffix = ".m4a"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await audio.read()
            tmp.write(content)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as f:
            response = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="fr"
            )

        os.unlink(tmp_path)

        # Log BEFORE return
        logger.info(f"✅ Whisper transcribed: '{response.text}' — duration charged: {len(content)/16000:.1f}s")

        return {
            "success": True,
            "transcript": response.text,
            "language": "fr"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
