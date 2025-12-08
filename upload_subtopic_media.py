"""
Upload Subtopic Media Endpoints
Uploads video covers and icon images from Airtable Subtopic table to Cloudinary

Video Cover: tuje/videos/subtopics/{subtopic_id}
Icon Image: tuje/images/subtopics/{subtopic_id}
"""

import logging
import time
from fastapi import HTTPException, APIRouter
from pydantic import BaseModel, validator
from cloudinary_service import CloudinaryService

logger = logging.getLogger(__name__)
router = APIRouter()

# ================================================
# REQUEST MODELS
# ================================================

class SubtopicVideoCoverRequest(BaseModel):
    """Request model for subtopic video cover upload"""
    subtopic_id: str
    video_url: str
    
    @validator('subtopic_id')
    def validate_subtopic_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Subtopic ID cannot be empty')
        return v.strip()
    
    @validator('video_url')
    def validate_video_url(cls, v):
        if not v or not v.startswith('http'):
            raise ValueError('Invalid video URL - must start with http or https')
        return v.strip()


class SubtopicIconRequest(BaseModel):
    """Request model for subtopic icon upload"""
    subtopic_id: str
    image_url: str
    
    @validator('subtopic_id')
    def validate_subtopic_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Subtopic ID cannot be empty')
        return v.strip()
    
    @validator('image_url')
    def validate_image_url(cls, v):
        if not v or not v.startswith('http'):
            raise ValueError('Invalid image URL - must start with http or https')
        return v.strip()


# ================================================
# ENDPOINT: Video Cover
# ================================================

@router.post("/upload-subtopic-video-cover-to-cloudinary")
async def upload_subtopic_video_cover(request: SubtopicVideoCoverRequest):
    """
    Upload subtopic video cover to Cloudinary.
    
    Cloudinary folder structure: tuje/videos/subtopics/{subtopic_id}
    """
    start_time = time.time()
    
    try:
        logger.info(f"🎥 Uploading video cover for subtopic {request.subtopic_id}")
        logger.info(f"   Video URL: {request.video_url[:80]}...")
        
        cloudinary_url = await CloudinaryService.upload_subtopic_video_cover_from_url(
            airtable_url=request.video_url,
            subtopic_id=request.subtopic_id
        )
        
        if not cloudinary_url:
            raise HTTPException(
                status_code=500,
                detail="Cloudinary upload failed - upload returned None"
            )
        
        elapsed = time.time() - start_time
        clean_subtopic_id = request.subtopic_id.replace('-', '_')
        cloudinary_path = f"tuje/videos/subtopics/{clean_subtopic_id}"
        
        logger.info(f"✅ Video cover uploaded in {elapsed:.2f}s")
        
        return {
            "success": True,
            "message": "Video cover uploaded successfully",
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
            "message": f"Upload failed: {str(e)}",
            "cloudinary_url": None,
            "execution_time": f"{elapsed:.2f}s",
            "error": str(e)
        }


# ================================================
# ENDPOINT: Icon Image
# ================================================

@router.post("/upload-subtopic-icon-to-cloudinary")
async def upload_subtopic_icon(request: SubtopicIconRequest):
    """
    Upload subtopic icon image to Cloudinary.
    
    Cloudinary folder structure: tuje/images/subtopics/{subtopic_id}
    """
    start_time = time.time()
    
    try:
        logger.info(f"🖼️ Uploading icon for subtopic {request.subtopic_id}")
        logger.info(f"   Image URL: {request.image_url[:80]}...")
        
        cloudinary_url = await CloudinaryService.upload_subtopic_icon_from_url(
            airtable_url=request.image_url,
            subtopic_id=request.subtopic_id
        )
        
        if not cloudinary_url:
            raise HTTPException(
                status_code=500,
                detail="Cloudinary upload failed - upload returned None"
            )
        
        elapsed = time.time() - start_time
        clean_subtopic_id = request.subtopic_id.replace('-', '_')
        cloudinary_path = f"tuje/images/subtopics/{clean_subtopic_id}"
        
        logger.info(f"✅ Icon uploaded in {elapsed:.2f}s")
        
        return {
            "success": True,
            "message": "Icon uploaded successfully",
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
            "message": f"Upload failed: {str(e)}",
            "cloudinary_url": None,
            "execution_time": f"{elapsed:.2f}s",
            "error": str(e)
        }
