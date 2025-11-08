"""
SIMPLIFIED Upload Video Endpoint - Only Essential Fields
Uses only: interaction_id, subtopic_id, video_url
"""

import logging
import time
from fastapi import HTTPException, APIRouter
from pydantic import BaseModel, validator
from typing import Optional
from cloudinary_service import CloudinaryService

logger = logging.getLogger(__name__)
router = APIRouter()

# ================================================
# SIMPLIFIED REQUEST MODEL
# ================================================

class VideoUploadRequest(BaseModel):
    """
    Simplified request - only essential fields for Cloudinary upload
    """
    interaction_id: str         # From Interaction ID field
    subtopic_id: str           # From ID (from Subtopic) field  
    video_url: str             # From VideoFr attachment
    
    @validator('interaction_id', 'subtopic_id')
    def validate_ids(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('IDs cannot be empty')
        return v.strip()
    
    @validator('video_url')
    def validate_video_url(cls, v):
        if not v or not v.startswith('http'):
            raise ValueError('Invalid video URL - must start with http or https')
        return v.strip()
    
    class Config:
        json_schema_extra = {
            "example": {
                "interaction_id": "550e8400-e29b-41d4-a716-446655440000",
                "subtopic_id": "650e8400-e29b-41d4-a716-446655440001",
                "video_url": "https://dl.airtable.com/.attachments/abc123/video.mp4"
            }
        }


# ================================================
# SIMPLIFIED ENDPOINT
# ================================================

@router.post("/upload-video-to-cloudinary")
async def upload_video_to_cloudinary(request: VideoUploadRequest):
    """
    Upload video to Cloudinary using ONLY essential fields.
    
    Required fields:
    - interaction_id: Used in Cloudinary public_id
    - subtopic_id: Used to organize videos in Cloudinary folders
    - video_url: Airtable attachment URL to upload
    
    Cloudinary folder structure:
    tuje/videos/interactions/{subtopic_id}/int_{interaction_id}.mp4
    
    Returns:
        {
            "success": bool,
            "cloudinary_url": str,
            "poster_url": str,
            "execution_time": str
        }
    """
    start_time = time.time()
    
    try:
        logger.info(f"🎥 Uploading video for interaction {request.interaction_id}")
        logger.info(f"   Subtopic ID: {request.subtopic_id}")
        logger.info(f"   Video URL: {request.video_url[:80]}...")
        
        # Clean IDs for use in folder/file names
        clean_subtopic = request.subtopic_id.replace('-', '_')
        clean_interaction = request.interaction_id.replace('-', '_')
        
        # Build Cloudinary public_id
        # Format: tuje/videos/interactions/{subtopic_id}/int_{interaction_id}
        folder = f"tuje/videos/interactions/{clean_subtopic}"
        public_id = f"{folder}/int_{clean_interaction}"
        
        logger.info(f"   Cloudinary path: {public_id}")
        
        # Upload to Cloudinary
        cloudinary_url = await CloudinaryService.upload_video_from_url_simple(
            airtable_url=request.video_url,
            public_id=public_id
        )
        
        if not cloudinary_url:
            raise HTTPException(
                status_code=500,
                detail="Cloudinary upload failed - upload returned None"
            )
        
        # Generate poster/thumbnail
        poster_url = CloudinaryService.get_video_poster_url(
            cloudinary_url,
            frame_offset=2.0
        )
        
        elapsed = time.time() - start_time
        
        logger.info(f"✅ Video uploaded in {elapsed:.2f}s")
        logger.info(f"   URL: {cloudinary_url}")
        
        return {
            "success": True,
            "message": "✅ Video uploaded successfully",
            "cloudinary_url": cloudinary_url,
            "poster_url": poster_url,
            "execution_time": f"{elapsed:.2f}s",
            "cloudinary_path": public_id
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
            "poster_url": None,
            "execution_time": f"{elapsed:.2f}s",
            "error": str(e)
        }


# ================================================
# HEALTH CHECK
# ================================================

@router.get("/cloudinary-health")
async def cloudinary_health():
    """Check Cloudinary connection"""
    try:
        from cloudinary import api as cloudinary_api
        result = cloudinary_api.ping()
        
        if result.get('status') == 'ok':
            return {
                "status": "healthy",
                "cloudinary": "✅ Connected"
            }
        else:
            return {
                "status": "unhealthy",
                "cloudinary": "⚠️ Unexpected response"
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "cloudinary": "❌ Not accessible",
            "error": str(e)
        }
