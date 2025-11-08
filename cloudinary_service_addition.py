"""
Add this method to your cloudinary_service.py file
This is a simplified version that uses public_id directly
"""

# Add this method to the CloudinaryService class:

@staticmethod
async def upload_video_from_url_simple(
    airtable_url: str,
    public_id: str
) -> Optional[str]:
    """
    Simplified video upload using public_id directly.
    
    Args:
        airtable_url: URL of video in Airtable
        public_id: Full Cloudinary public_id path
                  Example: "tuje/videos/interactions/subtopic_123/int_456"
        
    Returns:
        Cloudinary URL with transformations or None if failed
    """
    try:
        logger.info(f"📤 Uploading to Cloudinary: {public_id}")
        
        # Upload to Cloudinary with mobile optimizations
        result = cloudinary.uploader.upload(
            airtable_url,
            resource_type="video",
            public_id=public_id,
            overwrite=True,
            eager=[CloudinaryService.VIDEO_TRANSFORMATION],
            eager_async=False,
            invalidate=True,
            timeout=120  # 2 minute timeout
        )
        
        # Build optimized URL
        optimized_url = cloudinary.CloudinaryVideo(result['public_id']).build_url(
            **CloudinaryService.VIDEO_TRANSFORMATION
        )
        
        logger.info(f"✅ Upload complete: {optimized_url}")
        
        return optimized_url
        
    except Exception as e:
        logger.error(f"❌ Upload failed for {public_id}: {e}")
        return None
