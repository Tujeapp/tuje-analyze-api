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
        """
        Simplified video upload using explicit folder parameter
        
        Args:
            airtable_url: URL of video in Airtable
            public_id: Full Cloudinary public_id path
                      Example: "tuje/videos/interactions/SUBT123/int_456"
            
        Returns:
            Cloudinary URL with transformations or None if failed
        """
        try:
            # ============================================
            # SPLIT public_id into folder + filename
            # ============================================
            # Example: "tuje/videos/interactions/SUBT123/int_456"
            # -> folder: "tuje/videos/interactions/SUBT123"
            # -> filename: "int_456"
            
            if '/' in public_id:
                parts = public_id.rsplit('/', 1)  # Split at last slash
                folder_path = parts[0]  # Everything before last slash
                file_name = parts[1]    # Everything after last slash
            else:
                folder_path = None
                file_name = public_id
            
            logger.info(f"📤 Uploading to Cloudinary")
            logger.info(f"   📁 Folder: {folder_path}")
            logger.info(f"   📄 Filename: {file_name}")
            logger.info(f"   🔗 Full path: {public_id}")
            
            # ============================================
            # UPLOAD WITH EXPLICIT FOLDER PARAMETER
            # ============================================
            upload_params = {
                "resource_type": "video",
                "public_id": file_name,  # Just the filename
                "overwrite": True,
                "use_filename": False,
                "unique_filename": False,
                "eager": [CloudinaryService.VIDEO_TRANSFORMATION],
                "eager_async": False,
                "invalidate": True,
                "timeout": 120
            }
            
            # Add folder parameter only if we have a folder path
            if folder_path:
                upload_params["folder"] = folder_path
            
            result = cloudinary.uploader.upload(airtable_url, **upload_params)
            
            # ============================================
            # LOG WHAT CLOUDINARY ACTUALLY SAVED
            # ============================================
            actual_public_id = result.get('public_id', 'UNKNOWN')
            actual_folder = result.get('folder', 'NONE')
            
            logger.info(f"   ✅ Cloudinary saved:")
            logger.info(f"      public_id: {actual_public_id}")
            logger.info(f"      folder: {actual_folder}")
            
            # Build optimized URL
            optimized_url = cloudinary.CloudinaryVideo(result['public_id']).build_url(
                **CloudinaryService.VIDEO_TRANSFORMATION
            )
            
            logger.info(f"✅ Upload complete: {optimized_url}")
            return optimized_url
            
        except Exception as e:
            logger.error(f"❌ Upload failed for {public_id}: {e}")
            logger.exception(e)  # Full stack trace
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
            # URL format: https://res.cloudinary.com/{cloud}/video/upload/{transformations}/v1/{public_id}.mp4
            
            # Split by / and find the parts after 'upload'
            parts = video_url.split('/')
            
            # Find 'upload' index
            upload_idx = -1
            for i, part in enumerate(parts):
                if part == 'upload':
                    upload_idx = i
                    break
            
            if upload_idx == -1:
                logger.error("Could not find 'upload' in URL")
                return video_url.replace('.mp4', '.jpg')
            
            # Get everything after upload, skipping transformations and version
            path_parts = []
            for i in range(upload_idx + 1, len(parts)):
                part = parts[i]
                # Skip transformation strings (contain commas or underscores but not slashes)
                # Skip version strings (start with 'v' followed by numbers)
                if not (',' in part or (part.startswith('v') and len(part) > 1 and part[1:].isdigit())):
                    path_parts.append(part)
            
            # Reconstruct public_id (without .mp4 extension)
            public_id_with_ext = '/'.join(path_parts)
            public_id = public_id_with_ext.rsplit('.', 1)[0] if '.' in public_id_with_ext else public_id_with_ext
            
            logger.info(f"   🖼️ Generating poster for: {public_id}")
            
            # Generate poster URL
            poster_url = cloudinary.CloudinaryVideo(public_id).build_url(
                format='jpg',
                start_offset=frame_offset,
                quality='auto:good',
                transformation=[
                    {'width': 720, 'crop': 'limit'}
                ]
            )
            
            return poster_url
            
        except Exception as e:
            logger.error(f"❌ Failed to generate poster URL: {e}")
            # Fallback: simple replacement
            return video_url.replace('.mp4', '.jpg')
    
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
                use_filename=False,
                unique_filename=False,
                eager=[CloudinaryService.VIDEO_TRANSFORMATION],
                eager_async=False,
                invalidate=True
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
    async def upload_image_from_url(
        airtable_url: str,
        subtopic_id: str,
        subtopic_name: str,
        image_type: str = "subtopic"
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
                use_filename=False,
                unique_filename=False,
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
