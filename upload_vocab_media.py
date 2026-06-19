"""
Upload Vocab Media Endpoints
Uploads Vocab audio (normal+slow) and image from Airtable to Cloudinary.
Folders: tuje/audio/vocab/{vocab_id}_{normal,slow}, tuje/images/vocab/{vocab_id}
"""

import logging
import time
from fastapi import HTTPException, APIRouter
from pydantic import BaseModel, validator
from cloudinary_service import CloudinaryService

logger = logging.getLogger(__name__)
router = APIRouter()

# ================================================
# VOCAB IMAGE — REQUEST MODEL
# ================================================

class VocabImageUploadRequest(BaseModel):
    """Request model for vocab image upload"""
    vocab_id: str
    image_url: str

    @validator('vocab_id')
    def validate_vocab_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Vocab ID cannot be empty')
        return v.strip()

    @validator('image_url')
    def validate_image_url(cls, v):
        if not v or not v.startswith('http'):
            raise ValueError('Invalid image URL - must start with http or https')
        return v.strip()


# ================================================
# VOCAB IMAGE — ENDPOINT
# ================================================

@router.post("/upload-vocab-image-to-cloudinary")
async def upload_vocab_image_to_cloudinary(request: VocabImageUploadRequest):
    """Upload a vocab image to Cloudinary (tuje/images/vocab/{vocab_id})."""
    start_time = time.time()
    try:
        logger.info(f"🖼️ Uploading image for vocab {request.vocab_id}")
        cloudinary_url = await CloudinaryService.upload_vocab_image_from_url(
            airtable_url=request.image_url,
            vocab_id=request.vocab_id
        )

        if not cloudinary_url:
            raise HTTPException(
                status_code=500,
                detail="Cloudinary upload failed - upload returned None"
            )

        elapsed = time.time() - start_time
        clean_vocab_id = request.vocab_id.replace('-', '_')

        logger.info(f"✅ Image uploaded in {elapsed:.2f}s")
        return {
            "success": True,
            "message": "✅ Image uploaded successfully",
            "cloudinary_url": cloudinary_url,
            "execution_time": f"{elapsed:.2f}s",
            "cloudinary_path": f"tuje/images/vocab/{clean_vocab_id}"
        }

    except HTTPException:
        raise

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Upload failed after {elapsed:.2f}s: {e}")
        return {
            "success": False,
            "message": f"❌ Upload failed: {str(e)}",
            "cloudinary_url": None,
            "execution_time": f"{elapsed:.2f}s",
            "error": str(e)
        }


# ================================================
# VOCAB AUDIO — REQUEST MODEL
# ================================================

class VocabAudioUploadRequest(BaseModel):
    """Request model for vocab audio upload (normal + slow speeds)"""
    vocab_id: str
    audio_normal_url: str
    audio_slow_url: str

    @validator('vocab_id')
    def validate_vocab_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Vocab ID cannot be empty')
        return v.strip()

    @validator('audio_normal_url', 'audio_slow_url')
    def validate_audio_urls(cls, v):
        if not v or not v.startswith('http'):
            raise ValueError('Invalid audio URL - must start with http or https')
        return v.strip()


# ================================================
# VOCAB AUDIO — ENDPOINT
# ================================================

@router.post("/upload-vocab-audio-to-cloudinary")
async def upload_vocab_audio_to_cloudinary(request: VocabAudioUploadRequest):
    """Upload a vocab's normal + slow audio to Cloudinary (tuje/audio/vocab/...)."""
    start_time = time.time()
    try:
        logger.info(f"🔊 Uploading audio for vocab {request.vocab_id}")
        result = await CloudinaryService.upload_vocab_audio_from_url(
            vocab_id=request.vocab_id,
            audio_normal_url=request.audio_normal_url,
            audio_slow_url=request.audio_slow_url
        )

        if not result.get("success"):
            return {
                "success": False,
                "message": f"❌ Audio upload failed: {result.get('error')}",
                "audio_normal_url": None,
                "audio_slow_url": None,
                "execution_time": result.get("execution_time", f"{time.time() - start_time:.2f}s"),
                "error": result.get("error")
            }

        logger.info(f"✅ Audio uploaded in {result['execution_time']}")
        return {
            "success": True,
            "message": "✅ Audio uploaded successfully",
            "audio_normal_url": result["audio_normal_url"],
            "audio_slow_url": result["audio_slow_url"],
            "execution_time": result["execution_time"]
        }

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Audio upload failed after {elapsed:.2f}s: {e}")
        return {
            "success": False,
            "message": f"❌ Upload failed: {str(e)}",
            "audio_normal_url": None,
            "audio_slow_url": None,
            "execution_time": f"{elapsed:.2f}s",
            "error": str(e)
        }
