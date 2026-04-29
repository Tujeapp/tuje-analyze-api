from fastapi import APIRouter, UploadFile, File, HTTPException
from openai import AsyncOpenAI
import os
import tempfile
import logging

router = APIRouter()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
logger = logging.getLogger(__name__)

# Known Whisper hallucination patterns on silence or noise
HALLUCINATION_PATTERNS = [
    "sous-titres",
    "amara.org",
    "sous titres",
    "transcrit par",
    "merci d'avoir regardé",
    "merci pour votre attention",
    "abonnez-vous",
    "like et abonnez",
    "la communauté",
    "sous-titrée par",
]

MIN_AUDIO_DURATION_SECONDS = 0.5  # ignore recordings shorter than this

@router.post("/transcribe-audio")
async def transcribe_audio(audio: UploadFile = File(...)):
    try:
        suffix = ".m4a"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await audio.read()
            tmp.write(content)
            tmp_path = tmp.name

        # Fix 1 — reject audio that is too short (likely silence or accidental tap)
        audio_duration = len(content) / 16000
        if audio_duration < MIN_AUDIO_DURATION_SECONDS:
            os.unlink(tmp_path)
            logger.info(f"⏱️ Audio too short ({audio_duration:.2f}s) — skipping Whisper")
            return {
                "success": True,
                "transcript": "",
                "language": "fr",
                "skipped": True,
                "reason": "audio_too_short"
            }

        with open(tmp_path, "rb") as f:
            # Fix 2 — prompt biases Whisper toward short natural French
            # Fix 3 — temperature=0 reduces hallucination creativity
            response = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="fr",
                prompt="Réponse courte en français parlé naturel.",
                temperature=0
            )

        os.unlink(tmp_path)

        transcript = response.text.strip()

        # Fix 4 — reject known hallucination patterns
        if any(pattern in transcript.lower() for pattern in HALLUCINATION_PATTERNS):
            logger.warning(f"🚫 Whisper hallucination detected: '{transcript}'")
            return {
                "success": True,
                "transcript": "",
                "language": "fr",
                "skipped": True,
                "reason": "hallucination_detected"
            }

        logger.info(
            f"✅ Whisper transcribed: '{transcript}' "
            f"— duration: {audio_duration:.1f}s "
            f"— cost: ${(audio_duration / 60) * 0.006:.5f}"
        )

        return {
            "success": True,
            "transcript": transcript,
            "language": "fr",
            "skipped": False,
            "reason": None
        }

    except Exception as e:
        logger.error(f"❌ Whisper transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
