"""
Upload Subtopic Image Endpoint
Uploads images from Airtable Subtopic table to Cloudinary
Folder structure: tuje/images/subtopics/{subtopic_id}
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

class SubtopicImageUploadRequest(BaseModel):
    """
    Request model for subtopic image upload
    """
    subtopic_id: str      # From Subtopic ID field
    image_url: str        # From Image attachment field
    
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
    
    class Config:
        json_schema_extra = {
            "example": {
                "subtopic_id": "SUBT_001",
                "image_url": "https://dl.airtable.com/.attachments/abc123/image.png"
            }
        }


# ================================================
# ENDPOINT
# ================================================

@router.post("/upload-subtopic-image-to-cloudinary")
async def upload_subtopic_image_to_cloudinary(request: SubtopicImageUploadRequest):
    """
    Upload subtopic image to Cloudinary.
    
    Required fields:
    - subtopic_id: Used in Cloudinary public_id
    - image_url: Airtable attachment URL to upload
    
    Cloudinary folder structure:
    tuje/images/subtopics/{subtopic_id}
    
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
        logger.info(f"🖼️ Uploading image for subtopic {request.subtopic_id}")
        logger.info(f"   Image URL: {request.image_url[:80]}...")
        
        # Upload to Cloudinary
        cloudinary_url = await CloudinaryService.upload_subtopic_image_from_url(
            airtable_url=request.image_url,
            subtopic_id=request.subtopic_id
        )
        
        if not cloudinary_url:
            raise HTTPException(
                status_code=500,
                detail="Cloudinary upload failed - upload returned None"
            )
        
        elapsed = time.time() - start_time
        
        # Build the path for reference
        clean_subtopic_id = request.subtopic_id.replace('-', '_')
        cloudinary_path = f"tuje/images/subtopics/{clean_subtopic_id}"
        
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
