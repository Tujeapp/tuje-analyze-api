"""
Cloudinary Service for TuJe
Handles video and image uploads from Airtable to Cloudinary
"""

import os
import logging
import cloudinary
import cloudinary.uploader
import cloudinary.api
from typing import Optional, Dict, Any
import httpx
from pathlib import Path

logger = logging.getLogger(__name__)

# Initialize Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

class CloudinaryService:
    """
    Service for uploading and managing media files in Cloudinary
    """
    
    # Folder structure
    VIDEO_BASE_FOLDER = "tuje/videos/interactions"
    IMAGE_BASE_FOLDER = "tuje/images/subtopics"
    TUTORIAL_FOLDER = "tuje/videos/tutorials"
    UI_FOLDER = "tuje/images/ui"
    
    # Video transformation for mobile optimization
    VIDEO_TRANSFORMATION = {
        'quality': 'auto:low',
        'fetch_format': 'auto',
        'width': 720,
        'video_codec': 'auto'
    }
    
    # Image transformation for subtopic images
    IMAGE_TRANSFORMATION = {
        'quality': 'auto:good',
        'fetch_format': 'auto',
        'width': 400,
        'height': 400,
        'crop': 'fill',
        'gravity': 'center'
    }

    @staticmethod
    async def upload_video_from_url_simple(
        airtable_url: str,
        public_id: str
    ) -> Optional[str]:
        """Simplified video upload using public_id directly"""
        try:
            logger.info(f"📤 Uploading to Cloudinary: {public_id}")
            
            result = cloudinary.uploader.upload(
                airtable_url,
                resource_type="video",
                public_id=public_id,
                overwrite=True,
                eager=[CloudinaryService.VIDEO_TRANSFORMATION],
                eager_async=False,
                invalidate=True,
                timeout=120
            )
            
            optimized_url = cloudinary.CloudinaryVideo(result['public_id']).build_url(
                **CloudinaryService.VIDEO_TRANSFORMATION
            )
            
            logger.info(f"✅ Upload complete: {optimized_url}")
            return optimized_url
            
        except Exception as e:
            logger.error(f"❌ Upload failed for {public_id}: {e}")
            return None
    
    @staticmethod
    async def upload_video_from_url(
        airtable_url: str,
        interaction_id: str,
        subtopic_name: str,
        level: int,
        optimum_level: Optional[int] = None
    ) -> Optional[str]:
        """
        Upload video from Airtable URL to Cloudinary
        
        Args:
            airtable_url: URL of video in Airtable
            interaction_id: Unique interaction ID
            subtopic_name: Name of subtopic (for folder organization)
            level: Interaction level (1-5)
            optimum_level: Optional optimum level for folder organization
            
        Returns:
            Cloudinary URL with transformations or None if failed
        """
        try:
            # Clean subtopic name for folder structure
            clean_subtopic = subtopic_name.lower().replace(' ', '_').replace('/', '_')
            
            # Determine folder based on level
            folder = f"{CloudinaryService.VIDEO_BASE_FOLDER}/level_{level}"
            
            # Create public_id (unique identifier in Cloudinary)
            public_id = f"{folder}/int_{interaction_id}_{clean_subtopic}"
            
            logger.info(f"Uploading video: {public_id}")
            
            # Upload to Cloudinary
            result = cloudinary.uploader.upload(
                airtable_url,
                resource_type="video",
                public_id=public_id,
                overwrite=True,
                notification_url=None,  # Can add webhook for upload completion
                eager=[CloudinaryService.VIDEO_TRANSFORMATION],  # Pre-generate transformations
                eager_async=False,  # Wait for transformations to complete
                invalidate=True  # Invalidate CDN cache
            )
            
            # Build optimized URL
            optimized_url = cloudinary.CloudinaryVideo(result['public_id']).build_url(
                **CloudinaryService.VIDEO_TRANSFORMATION
            )
            
            logger.info(f"✅ Video uploaded successfully: {optimized_url}")
            
            return optimized_url
            
        except Exception as e:
            logger.error(f"❌ Failed to upload video {interaction_id}: {e}")
            return None

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
    
    @staticmethod
    async def upload_image_from_url(
        airtable_url: str,
        subtopic_id: str,
        subtopic_name: str,
        image_type: str = "subtopic"  # subtopic, icon, background
    ) -> Optional[str]:
        """
        Upload image from Airtable URL to Cloudinary
        
        Args:
            airtable_url: URL of image in Airtable
            subtopic_id: Unique subtopic ID
            subtopic_name: Name of subtopic
            image_type: Type of image (subtopic, icon, background)
            
        Returns:
            Cloudinary URL with transformations or None if failed
        """
        try:
            # Clean subtopic name
            clean_name = subtopic_name.lower().replace(' ', '_').replace('/', '_')
            
            # Determine folder
            if image_type == "subtopic":
                folder = f"{CloudinaryService.IMAGE_BASE_FOLDER}/{clean_name}"
                public_id = f"{folder}/sub_{subtopic_id}"
            elif image_type == "icon":
                folder = f"{CloudinaryService.UI_FOLDER}/icons"
                public_id = f"{folder}/icon_{clean_name}"
            else:
                folder = f"{CloudinaryService.UI_FOLDER}/backgrounds"
                public_id = f"{folder}/bg_{clean_name}"
            
            logger.info(f"Uploading image: {public_id}")
            
            # Upload to Cloudinary
            result = cloudinary.uploader.upload(
                airtable_url,
                resource_type="image",
                public_id=public_id,
                overwrite=True,
                eager=[CloudinaryService.IMAGE_TRANSFORMATION],
                eager_async=False,
                invalidate=True
            )
            
            # Build optimized URL
            optimized_url = cloudinary.CloudinaryImage(result['public_id']).build_url(
                **CloudinaryService.IMAGE_TRANSFORMATION
            )
            
            logger.info(f"✅ Image uploaded successfully: {optimized_url}")
            
            return optimized_url
            
        except Exception as e:
            logger.error(f"❌ Failed to upload image {subtopic_id}: {e}")
            return None
    
    @staticmethod
    async def download_and_upload(
        airtable_url: str,
        public_id: str,
        resource_type: str = "video",
        transformations: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Generic method to download from Airtable and upload to Cloudinary
        
        Args:
            airtable_url: URL to download from
            public_id: Cloudinary public ID
            resource_type: 'video' or 'image'
            transformations: Optional transformations dict
            
        Returns:
            Cloudinary URL or None
        """
        try:
            # Use httpx for async download
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(airtable_url)
                response.raise_for_status()
                
                # Save temporarily
                temp_path = f"/tmp/{public_id.replace('/', '_')}"
                with open(temp_path, 'wb') as f:
                    f.write(response.content)
            
            # Upload to Cloudinary
            result = cloudinary.uploader.upload(
                temp_path,
                resource_type=resource_type,
                public_id=public_id,
                overwrite=True,
                eager=[transformations] if transformations else [],
                eager_async=False,
                invalidate=True
            )
            
            # Clean up temp file
            os.remove(temp_path)
            
            # Build URL based on resource type
            if resource_type == "video":
                url = cloudinary.CloudinaryVideo(result['public_id']).build_url(
                    **(transformations or {})
                )
            else:
                url = cloudinary.CloudinaryImage(result['public_id']).build_url(
                    **(transformations or {})
                )
            
            logger.info(f"✅ Uploaded to Cloudinary: {url}")
            return url
            
        except Exception as e:
            logger.error(f"❌ Upload failed for {public_id}: {e}")
            # Clean up temp file if it exists
            try:
                os.remove(temp_path)
            except:
                pass
            return None
    
    @staticmethod
    def get_video_poster_url(video_url: str, frame_offset: float = 2.0) -> str:
        """
        Generate poster image URL from video URL
        
        Args:
            video_url: Cloudinary video URL
            frame_offset: Time offset in seconds for poster frame
            
        Returns:
            Poster image URL
        """
        try:
            # Extract public_id from URL
            # Format: https://res.cloudinary.com/{cloud}/video/upload/{transformations}/{public_id}.mp4
            parts = video_url.split('/')
            public_id_with_ext = parts[-1]
            public_id = public_id_with_ext.rsplit('.', 1)[0]
            
            # Reconstruct path without version and transformations
            path_parts = []
            found_upload = False
            for part in parts:
                if found_upload and not part.startswith('v'):
                    path_parts.append(part)
                elif part == 'upload':
                    found_upload = True
            
            full_public_id = '/'.join(path_parts[:-1]) + '/' + public_id
            
            # Generate poster URL
            poster_url = cloudinary.CloudinaryVideo(full_public_id).build_url(
                format='jpg',
                start_offset=frame_offset,
                quality='auto:good'
            )
            
            return poster_url
            
        except Exception as e:
            logger.error(f"❌ Failed to generate poster URL: {e}")
            return video_url.replace('.mp4', '.jpg')
    
    @staticmethod
    async def delete_asset(public_id: str, resource_type: str = "video") -> bool:
        """
        Delete asset from Cloudinary
        
        Args:
            public_id: Cloudinary public ID
            resource_type: 'video' or 'image'
            
        Returns:
            True if successful, False otherwise
        """
        try:
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type=resource_type,
                invalidate=True
            )
            
            if result.get('result') == 'ok':
                logger.info(f"✅ Deleted from Cloudinary: {public_id}")
                return True
            else:
                logger.warning(f"⚠️ Delete returned: {result}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to delete {public_id}: {e}")
            return False
    
    @staticmethod
    async def check_asset_exists(public_id: str, resource_type: str = "video") -> bool:
        """
        Check if asset exists in Cloudinary
        
        Args:
            public_id: Cloudinary public ID
            resource_type: 'video' or 'image'
            
        Returns:
            True if exists, False otherwise
        """
        try:
            result = cloudinary.api.resource(
                public_id,
                resource_type=resource_type
            )
            return True
        except cloudinary.exceptions.NotFound:
            return False
        except Exception as e:
            logger.error(f"❌ Error checking asset: {e}")
            return False


# Utility functions for cost optimization

def get_optimized_video_url(cloudinary_url: str, quality: str = "auto:low") -> str:
    """
    Get video URL with specific quality settings for cost optimization
    
    Args:
        cloudinary_url: Original Cloudinary URL
        quality: Quality setting (auto:low, auto:good, auto:best)
        
    Returns:
        Optimized URL
    """
    # This allows you to serve different quality levels based on user tier
    # Free users: auto:low
    # Premium users: auto:good
    return cloudinary_url.replace('q_auto:low', f'q_{quality}')


def get_thumbnail_url(video_url: str, width: int = 200) -> str:
    """
    Generate thumbnail URL from video
    
    Args:
        video_url: Cloudinary video URL
        width: Thumbnail width
        
    Returns:
        Thumbnail URL
    """
    try:
        parts = video_url.split('/')
        public_id = parts[-1].rsplit('.', 1)[0]
        
        return cloudinary.CloudinaryVideo(public_id).build_url(
            format='jpg',
            start_offset=2.0,
            width=width,
            height=width,
            crop='fill',
            quality='auto:low'
        )
    except Exception as e:
        logger.error(f"Failed to generate thumbnail: {e}")
        return ""
