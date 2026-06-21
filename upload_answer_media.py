"""
Upload Answer Image Endpoint
Uploads images from Airtable Answer table to Cloudinary
Folder structure: tuje/images/answers/{answer_id}
"""

import logging
import time
from fastapi import HTTPException, APIRouter
from pydantic import BaseModel, validator
from cloudinary_service import CloudinaryService

logger = logging.getLogger(__name__)
router = APIRouter()

# ================================================
# REQUEST MODEL
# ================================================

class AnswerImageUploadRequest(BaseModel):
    """
    Request model for answer image upload
    """
    answer_id: str      # From Answer ID field
    image_url: str      # From Image attachment field
    
    @validator('answer_id')
    def validate_answer_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Answer ID cannot be empty')
        return v.strip()
    
    @validator('image_url')
    def validate_image_url(cls, v):
        if not v or not v.startswith('http'):
            raise ValueError('Invalid image URL - must start with http or https')
        return v.strip()
    
    class Config:
        json_schema_extra = {
            "example": {
                "answer_id": "ANS_001",
                "image_url": "https://dl.airtable.com/.attachments/abc123/image.png"
            }
        }


# ================================================
# ENDPOINT
# ================================================

@router.post("/upload-answer-image-to-cloudinary")
async def upload_answer_image_to_cloudinary(request: AnswerImageUploadRequest):
    """
    Upload answer image to Cloudinary.
    
    Required fields:
    - answer_id: Used in Cloudinary public_id
    - image_url: Airtable attachment URL to upload
    
    Cloudinary folder structure:
    tuje/images/answers/{answer_id}
    
    Returns:
        {
            "success": bool,
            "cloudinary_url": str,
            "execution_time": str,
            "cloudinary_path": str
        }
    """
    start_time = time.time()
    
    try:
        logger.info(f"🖼️ Uploading image for answer {request.answer_id}")
        logger.info(f"   Image URL: {request.image_url[:80]}...")
        
        # Upload to Cloudinary
        cloudinary_url = await CloudinaryService.upload_answer_image_from_url(
            airtable_url=request.image_url,
            answer_id=request.answer_id
        )
        
        if not cloudinary_url:
            raise HTTPException(
                status_code=500,
                detail="Cloudinary upload failed - upload returned None"
            )
        
        elapsed = time.time() - start_time
        
        # Build the path for reference
        clean_answer_id = request.answer_id.replace('-', '_')
        cloudinary_path = f"tuje/images/answers/{clean_answer_id}"
        
        logger.info(f"✅ Image uploaded in {elapsed:.2f}s")
        logger.info(f"   URL: {cloudinary_url}")
        
        return {
            "success": True,
            "message": "✅ Image uploaded successfully",
            "cloudinary_url": cloudinary_url,
            "execution_time": f"{elapsed:.2f}s",
            "cloudinary_path": cloudinary_path
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
# ANSWER AUDIO — REQUEST MODEL
# ================================================

class AnswerAudioUploadRequest(BaseModel):
    """Request model for answer audio upload (normal + slow speeds)"""
    answer_id: str
    audio_normal_url: str
    audio_slow_url: str

    @validator('answer_id')
    def validate_answer_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Answer ID cannot be empty')
        return v.strip()

    @validator('audio_normal_url', 'audio_slow_url')
    def validate_audio_urls(cls, v):
        if not v or not v.startswith('http'):
            raise ValueError('Invalid audio URL - must start with http or https')
        return v.strip()


# ================================================
# ANSWER AUDIO — ENDPOINT
# ================================================

@router.post("/upload-answer-audio-to-cloudinary")
async def upload_answer_audio_to_cloudinary(request: AnswerAudioUploadRequest):
    """Upload an answer's normal + slow audio to Cloudinary (tuje/audio/answers/...)."""
    start_time = time.time()
    try:
        logger.info(f"🔊 Uploading audio for answer {request.answer_id}")
        result = await CloudinaryService.upload_answer_audio_from_url(
            answer_id=request.answer_id,
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
