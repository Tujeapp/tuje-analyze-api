"""
Updated Pydantic models with Cloudinary support
Add these fields to your existing models
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID

# ================================================
# Updated InteractionEntry Model
# ================================================
class InteractionEntry(BaseModel):
    """
    Updated model for Interaction sync with Cloudinary support
    """
    id: UUID
    airtableRecordId: str
    lastModifiedTimeRef: int
    
    # Existing fields
    answerIds: Optional[List[UUID]] = None
    hintIds: Optional[List[UUID]] = None
    interactionTypeId: Optional[UUID] = None
    interactionOptimumLevel: Optional[int] = None
    nameFr: Optional[str] = None
    nameEn: Optional[str] = None
    levelOwned: Optional[int] = None
    levelFrom: Optional[int] = None
    levelTo: Optional[int] = None
    sessionMoodIds: Optional[List[UUID]] = None
    subtopicId: Optional[UUID] = None
    interactionVocabId: Optional[List[UUID]] = None
    expectedEntitiesId: Optional[List[UUID]] = None
    expectedVocabId: Optional[List[UUID]] = None
    expectedNotionId: Optional[List[UUID]] = None
    
    # OLD VIDEO FIELD - Keep for backward compatibility
    videoFr: Optional[str] = None  # Airtable URL
    
    # NEW CLOUDINARY FIELDS
    videoCloudinaryUrl: Optional[str] = None  # Optimized Cloudinary URL
    videoPosterUrl: Optional[str] = None  # Poster/thumbnail URL
    videoUploadStatus: Optional[str] = Field(default="pending")  # pending, uploading, completed, failed
    
    createdAt: Optional[datetime] = None
    lastModified: Optional[datetime] = None
    
    @validator('videoUploadStatus')
    def validate_upload_status(cls, v):
        allowed = ['pending', 'uploading', 'completed', 'failed']
        if v and v not in allowed:
            raise ValueError(f'videoUploadStatus must be one of {allowed}')
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "airtableRecordId": "recABC123",
                "lastModifiedTimeRef": 1699564800,
                "nameFr": "Réserver une chambre",
                "nameEn": "Book a room",
                "videoFr": "https://dl.airtable.com/.attachments/video.mp4",
                "videoCloudinaryUrl": "https://res.cloudinary.com/tuje/video/upload/q_auto:low,f_auto,w_720,vc_auto/tuje/videos/interactions/level_3/int_550e8400_hotel_booking.mp4",
                "videoPosterUrl": "https://res.cloudinary.com/tuje/video/upload/so_2.0,q_auto:good/tuje/videos/interactions/level_3/int_550e8400_hotel_booking.jpg",
                "videoUploadStatus": "completed"
            }
        }


# ================================================
# Updated SubtopicEntry Model
# ================================================
class SubtopicEntry(BaseModel):
    """
    Updated model for Subtopic sync with Cloudinary support
    """
    id: UUID
    airtableRecordId: str
    lastModifiedTimeRef: int
    
    # Existing fields
    nameFr: Optional[str] = None
    nameEn: Optional[str] = None
    descriptionFr: Optional[str] = None
    descriptionEn: Optional[str] = None
    interactionIds: Optional[List[UUID]] = None
    
    # OLD IMAGE FIELD - Keep for backward compatibility
    imageFr: Optional[str] = None  # Airtable URL
    
    # NEW CLOUDINARY FIELDS
    imageCloudinaryUrl: Optional[str] = None  # Optimized Cloudinary URL (400x400)
    imageUploadStatus: Optional[str] = Field(default="pending")
    
    createdAt: Optional[datetime] = None
    lastModified: Optional[datetime] = None
    
    @validator('imageUploadStatus')
    def validate_upload_status(cls, v):
        allowed = ['pending', 'uploading', 'completed', 'failed']
        if v and v not in allowed:
            raise ValueError(f'imageUploadStatus must be one of {allowed}')
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "650e8400-e29b-41d4-a716-446655440001",
                "airtableRecordId": "recXYZ789",
                "lastModifiedTimeRef": 1699564800,
                "nameFr": "À l'hôtel",
                "nameEn": "At the hotel",
                "imageFr": "https://dl.airtable.com/.attachments/image.jpg",
                "imageCloudinaryUrl": "https://res.cloudinary.com/tuje/image/upload/q_auto:good,f_auto,w_400,h_400,c_fill,g_center/tuje/images/subtopics/hotel/sub_650e8400.jpg",
                "imageUploadStatus": "completed"
            }
        }


# ================================================
# CloudinaryUpload Model (for tracking table)
# ================================================
class CloudinaryUpload(BaseModel):
    """
    Model for cloudinary_uploads tracking table
    """
    id: Optional[UUID] = None
    entity_type: str  # 'interaction' or 'subtopic'
    entity_id: UUID
    airtable_record_id: Optional[str] = None
    original_url: str
    cloudinary_public_id: str
    cloudinary_url: str
    resource_type: str  # 'video' or 'image'
    upload_status: str = "pending"
    file_size_bytes: Optional[int] = None
    duration_seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    format: Optional[str] = None
    error_message: Optional[str] = None
    upload_attempts: int = 0
    created_at: Optional[datetime] = None
    uploaded_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "entity_type": "interaction",
                "entity_id": "550e8400-e29b-41d4-a716-446655440000",
                "airtable_record_id": "recABC123",
                "original_url": "https://dl.airtable.com/.attachments/video.mp4",
                "cloudinary_public_id": "tuje/videos/interactions/level_3/int_550e8400_hotel_booking",
                "cloudinary_url": "https://res.cloudinary.com/tuje/video/upload/q_auto:low,f_auto,w_720,vc_auto/tuje/videos/interactions/level_3/int_550e8400_hotel_booking.mp4",
                "resource_type": "video",
                "upload_status": "completed",
                "file_size_bytes": 15728640,
                "duration_seconds": 12.5,
                "width": 720,
                "height": 1280,
                "format": "mp4"
            }
        }


# ================================================
# Response Models
# ================================================
class CloudinaryUploadResponse(BaseModel):
    """
    Response model for Cloudinary upload operations
    """
    success: bool
    entity_id: UUID
    entity_type: str
    cloudinary_url: Optional[str] = None
    poster_url: Optional[str] = None
    upload_status: str
    message: str
    error: Optional[str] = None


class UploadStatsResponse(BaseModel):
    """
    Response model for upload statistics
    """
    total_interactions: int
    interactions_migrated: int
    interactions_pending: int
    total_subtopics: int
    subtopics_migrated: int
    subtopics_pending: int
    failed_uploads: int
    total_size_mb: float
