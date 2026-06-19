"""
Cloudinary Service for TuJe
Handles video and image uploads from Airtable to Cloudinary
"""

import os
import time
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
    ANSWER_IMAGE_FOLDER = "tuje/images/answers"
    ANSWER_AUDIO_FOLDER = "tuje/audio/answers"
    SUBTOPIC_VIDEO_FOLDER = "tuje/videos/subtopics"
    SUBTOPIC_ICON_FOLDER = "tuje/images/subtopics"
    VOCAB_AUDIO_FOLDER = "tuje/audio/vocab"
    VOCAB_IMAGE_FOLDER = "tuje/images/vocab"
    
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
   
    # Image transformation for answer images
    ANSWER_IMAGE_TRANSFORMATION = {
        'quality': 'auto:good',
        'fetch_format': 'auto',
        'width': 300,
        'crop': 'limit'
    }

    ICON_IMAGE_TRANSFORMATION = {
    'quality': 'auto:good',
    'fetch_format': 'auto',
    'width': 200,
    'height': 200,
    'crop': 'fill',
    'gravity': 'center'
    }

    # Audio transformation (Cloudinary handles audio under resource_type="video")
    AUDIO_TRANSFORMATION = {
        'audio_codec': 'auto',
        'quality': 'auto'
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
            if '/' in public_id:
                parts = public_id.rsplit('/', 1)
                folder_path = parts[0]
                file_name = parts[1]
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
                "public_id": file_name,
                "overwrite": True,
                "use_filename": False,
                "unique_filename": False,
                "eager": [CloudinaryService.VIDEO_TRANSFORMATION],
                "eager_async": False,
                "invalidate": True,
                "timeout": 120
            }
            
            if folder_path:
                upload_params["folder"] = folder_path
            
            result = cloudinary.uploader.upload(airtable_url, **upload_params)
            
            actual_public_id = result.get('public_id', 'UNKNOWN')
            actual_folder = result.get('folder', 'NONE')
            
            logger.info(f"   ✅ Cloudinary saved:")
            logger.info(f"      public_id: {actual_public_id}")
            logger.info(f"      folder: {actual_folder}")
            
            optimized_url = cloudinary.CloudinaryVideo(result['public_id']).build_url(
                **CloudinaryService.VIDEO_TRANSFORMATION
            )
            
            logger.info(f"✅ Upload complete: {optimized_url}")
            return optimized_url
            
        except Exception as e:
            logger.error(f"❌ Upload failed for {public_id}: {e}")
            logger.exception(e)
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
        """
        try:
            clean_subtopic = subtopic_name.lower().replace(' ', '_').replace('/', '_')
            folder = f"{CloudinaryService.VIDEO_BASE_FOLDER}/level_{level}"
            public_id = f"{folder}/int_{interaction_id}_{clean_subtopic}"
            
            logger.info(f"Uploading video: {public_id}")
            
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
        """
        try:
            clean_name = subtopic_name.lower().replace(' ', '_').replace('/', '_')
            
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

    @staticmethod
    async def upload_answer_image_from_url(
        airtable_url: str,
        answer_id: str
    ) -> Optional[str]:
        """
        Upload answer image from Airtable URL to Cloudinary
        
        Folder structure: tuje/images/answers/{answer_id}
        """
        try:
            clean_answer_id = answer_id.replace('-', '_')
            folder = CloudinaryService.ANSWER_IMAGE_FOLDER
            
            logger.info(f"📤 Uploading answer image")
            logger.info(f"   📁 Folder: {folder}")
            logger.info(f"   📄 Public ID: {clean_answer_id}")
            
            result = cloudinary.uploader.upload(
                airtable_url,
                resource_type="image",
                folder=folder,
                public_id=clean_answer_id,
                overwrite=True,
                use_filename=False,
                unique_filename=False,
                eager=[CloudinaryService.ANSWER_IMAGE_TRANSFORMATION],
                eager_async=False,
                invalidate=True
            )
            
            actual_public_id = result.get('public_id', 'UNKNOWN')
            logger.info(f"   ✅ Cloudinary saved: {actual_public_id}")
            
            optimized_url = cloudinary.CloudinaryImage(result['public_id']).build_url(
                **CloudinaryService.ANSWER_IMAGE_TRANSFORMATION
            )
            
            logger.info(f"✅ Answer image uploaded: {optimized_url}")
            return optimized_url
            
        except Exception as e:
            logger.error(f"❌ Failed to upload answer image {answer_id}: {e}")
            logger.exception(e)
            return None

    
    @staticmethod
    async def upload_subtopic_image_from_url(
        airtable_url: str,
        subtopic_id: str
    ) -> Optional[str]:
        """
        Upload subtopic image from Airtable URL to Cloudinary
        
        Folder structure: tuje/images/subtopics/{subtopic_id}
        
        Args:
            airtable_url: URL of image in Airtable
            subtopic_id: Unique subtopic ID
            
        Returns:
            Cloudinary URL with transformations or None if failed
        """
        try:
            # Clean subtopic ID for folder name (replace hyphens with underscores)
            clean_subtopic_id = subtopic_id.replace('-', '_')
            
            # Use existing folder constant
            folder = CloudinaryService.IMAGE_BASE_FOLDER  # "tuje/images/subtopics"
            
            logger.info(f"📤 Uploading subtopic image")
            logger.info(f"   📁 Folder: {folder}")
            logger.info(f"   📄 Public ID: {clean_subtopic_id}")
            
            # Upload to Cloudinary
            result = cloudinary.uploader.upload(
                airtable_url,
                resource_type="image",
                folder=folder,
                public_id=clean_subtopic_id,
                overwrite=True,
                use_filename=False,
                unique_filename=False,
                eager=[CloudinaryService.IMAGE_TRANSFORMATION],
                eager_async=False,
                invalidate=True
            )
            
            # Log what Cloudinary actually saved
            actual_public_id = result.get('public_id', 'UNKNOWN')
            logger.info(f"   ✅ Cloudinary saved: {actual_public_id}")
            
            # Build optimized URL
            optimized_url = cloudinary.CloudinaryImage(result['public_id']).build_url(
                **CloudinaryService.IMAGE_TRANSFORMATION
            )
            
            logger.info(f"✅ Subtopic image uploaded: {optimized_url}")
            
            return optimized_url
            
        except Exception as e:
            logger.error(f"❌ Failed to upload subtopic image {subtopic_id}: {e}")
            logger.exception(e)
            return None


    @staticmethod
    async def upload_subtopic_video_cover_from_url(
        airtable_url: str,
        subtopic_id: str
    ) -> Optional[str]:
        """
        Upload subtopic video cover from Airtable URL to Cloudinary
        
        Folder structure: tuje/videos/subtopics/{subtopic_id}
        
        Args:
            airtable_url: URL of video in Airtable
            subtopic_id: Unique subtopic ID
            
        Returns:
            Cloudinary URL with transformations or None if failed
        """
        try:
            clean_subtopic_id = subtopic_id.replace('-', '_')
            folder = CloudinaryService.SUBTOPIC_VIDEO_FOLDER
            
            logger.info(f"📤 Uploading subtopic video cover")
            logger.info(f"   📁 Folder: {folder}")
            logger.info(f"   📄 Public ID: {clean_subtopic_id}")
            
            result = cloudinary.uploader.upload(
                airtable_url,
                resource_type="video",
                folder=folder,
                public_id=clean_subtopic_id,
                overwrite=True,
                use_filename=False,
                unique_filename=False,
                eager=[CloudinaryService.VIDEO_TRANSFORMATION],
                eager_async=False,
                invalidate=True,
                timeout=120
            )
            
            actual_public_id = result.get('public_id', 'UNKNOWN')
            logger.info(f"   ✅ Cloudinary saved: {actual_public_id}")
            
            optimized_url = cloudinary.CloudinaryVideo(result['public_id']).build_url(
                **CloudinaryService.VIDEO_TRANSFORMATION
            )
            
            logger.info(f"✅ Subtopic video cover uploaded: {optimized_url}")
            
            return optimized_url
            
        except Exception as e:
            logger.error(f"❌ Failed to upload subtopic video cover {subtopic_id}: {e}")
            logger.exception(e)
            return None

    @staticmethod
    async def upload_answer_audio_from_url(
        answer_id: str,
        audio_normal_url: str,
        audio_slow_url: str
    ) -> Dict[str, Any]:
        """
        Upload an Answer's normal- and slow-speed audio from Airtable URLs to Cloudinary.
        Folder: tuje/audio/answers/{answer_id}_normal and {answer_id}_slow
        Audio uses resource_type="video" (Cloudinary handles audio under video).

        Returns:
          { "success": True, "audio_normal_url": str, "audio_slow_url": str, "execution_time": "1.23s" }
          or { "success": False, "audio_normal_url": None, "audio_slow_url": None,
               "execution_time": "1.23s", "error": str }   (no partial result returned)
        """
        start_time = time.time()
        clean_answer_id = answer_id.replace('-', '_')
        folder = CloudinaryService.ANSWER_AUDIO_FOLDER

        def _upload(source_url: str, suffix: str) -> str:
            logger.info(f"📤 Uploading answer audio ({suffix})")
            logger.info(f"   📁 Folder: {folder}")
            logger.info(f"   📄 Public ID: {clean_answer_id}_{suffix}")
            result = cloudinary.uploader.upload(
                source_url,
                resource_type="video",
                folder=folder,
                public_id=f"{clean_answer_id}_{suffix}",
                overwrite=True,
                use_filename=False,
                unique_filename=False,
                eager=[CloudinaryService.AUDIO_TRANSFORMATION],
                eager_async=False,
                invalidate=True,
                timeout=120
            )
            logger.info(f"   ✅ Cloudinary saved: {result.get('public_id', 'UNKNOWN')}")
            return cloudinary.CloudinaryVideo(result['public_id']).build_url(
                **CloudinaryService.AUDIO_TRANSFORMATION
            )

        try:
            normal_url = _upload(audio_normal_url, "normal")
            slow_url = _upload(audio_slow_url, "slow")
            elapsed = time.time() - start_time
            logger.info(f"✅ Answer audio uploaded in {elapsed:.2f}s")
            return {
                "success": True,
                "audio_normal_url": normal_url,
                "audio_slow_url": slow_url,
                "execution_time": f"{elapsed:.2f}s"
            }
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ Failed to upload answer audio {answer_id}: {e}")
            logger.exception(e)
            return {
                "success": False,
                "audio_normal_url": None,
                "audio_slow_url": None,
                "execution_time": f"{elapsed:.2f}s",
                "error": str(e)
            }

    @staticmethod
    async def upload_vocab_audio_from_url(
        vocab_id: str,
        audio_normal_url: str,
        audio_slow_url: str
    ) -> Dict[str, Any]:
        """
        Upload a Vocab's normal- and slow-speed audio from Airtable URLs to Cloudinary.
        Folder: tuje/audio/vocab/{vocab_id}_normal and {vocab_id}_slow
        Audio uses resource_type="video" (Cloudinary handles audio under video).

        Returns:
          { "success": True, "audio_normal_url": str, "audio_slow_url": str, "execution_time": "1.23s" }
          or { "success": False, "audio_normal_url": None, "audio_slow_url": None,
               "execution_time": "1.23s", "error": str }   (no partial result returned)
        """
        start_time = time.time()
        clean_vocab_id = vocab_id.replace('-', '_')
        folder = CloudinaryService.VOCAB_AUDIO_FOLDER

        def _upload(source_url: str, suffix: str) -> str:
            logger.info(f"📤 Uploading vocab audio ({suffix})")
            logger.info(f"   📁 Folder: {folder}")
            logger.info(f"   📄 Public ID: {clean_vocab_id}_{suffix}")
            result = cloudinary.uploader.upload(
                source_url,
                resource_type="video",
                folder=folder,
                public_id=f"{clean_vocab_id}_{suffix}",
                overwrite=True,
                use_filename=False,
                unique_filename=False,
                eager=[CloudinaryService.AUDIO_TRANSFORMATION],
                eager_async=False,
                invalidate=True,
                timeout=120
            )
            logger.info(f"   ✅ Cloudinary saved: {result.get('public_id', 'UNKNOWN')}")
            return cloudinary.CloudinaryVideo(result['public_id']).build_url(
                **CloudinaryService.AUDIO_TRANSFORMATION
            )

        try:
            normal_url = _upload(audio_normal_url, "normal")
            slow_url = _upload(audio_slow_url, "slow")
            elapsed = time.time() - start_time
            logger.info(f"✅ Vocab audio uploaded in {elapsed:.2f}s")
            return {
                "success": True,
                "audio_normal_url": normal_url,
                "audio_slow_url": slow_url,
                "execution_time": f"{elapsed:.2f}s"
            }
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ Failed to upload vocab audio {vocab_id}: {e}")
            logger.exception(e)
            return {
                "success": False,
                "audio_normal_url": None,
                "audio_slow_url": None,
                "execution_time": f"{elapsed:.2f}s",
                "error": str(e)
            }

    @staticmethod
    async def upload_vocab_image_from_url(
        airtable_url: str,
        vocab_id: str
    ) -> Optional[str]:
        """
        Upload vocab image from Airtable URL to Cloudinary

        Folder structure: tuje/images/vocab/{vocab_id}
        """
        try:
            clean_vocab_id = vocab_id.replace('-', '_')
            folder = CloudinaryService.VOCAB_IMAGE_FOLDER

            logger.info(f"📤 Uploading vocab image")
            logger.info(f"   📁 Folder: {folder}")
            logger.info(f"   📄 Public ID: {clean_vocab_id}")

            result = cloudinary.uploader.upload(
                airtable_url,
                resource_type="image",
                folder=folder,
                public_id=clean_vocab_id,
                overwrite=True,
                use_filename=False,
                unique_filename=False,
                eager=[CloudinaryService.ANSWER_IMAGE_TRANSFORMATION],
                eager_async=False,
                invalidate=True
            )

            actual_public_id = result.get('public_id', 'UNKNOWN')
            logger.info(f"   ✅ Cloudinary saved: {actual_public_id}")

            optimized_url = cloudinary.CloudinaryImage(result['public_id']).build_url(
                **CloudinaryService.ANSWER_IMAGE_TRANSFORMATION
            )

            logger.info(f"✅ Vocab image uploaded: {optimized_url}")
            return optimized_url

        except Exception as e:
            logger.error(f"❌ Failed to upload vocab image {vocab_id}: {e}")
            logger.exception(e)
            return None

    @staticmethod
    async def upload_subtopic_icon_from_url(
        airtable_url: str,
        subtopic_id: str
    ) -> Optional[str]:
        """
        Upload subtopic icon image from Airtable URL to Cloudinary
        
        Folder structure: tuje/images/subtopics/{subtopic_id}
        
        Args:
            airtable_url: URL of image in Airtable
            subtopic_id: Unique subtopic ID
            
        Returns:
            Cloudinary URL with transformations or None if failed
        """
        try:
            clean_subtopic_id = subtopic_id.replace('-', '_')
            folder = CloudinaryService.SUBTOPIC_ICON_FOLDER
            
            logger.info(f"📤 Uploading subtopic icon")
            logger.info(f"   📁 Folder: {folder}")
            logger.info(f"   📄 Public ID: {clean_subtopic_id}")
            
            result = cloudinary.uploader.upload(
                airtable_url,
                resource_type="image",
                folder=folder,
                public_id=clean_subtopic_id,
                overwrite=True,
                use_filename=False,
                unique_filename=False,
                eager=[CloudinaryService.ICON_IMAGE_TRANSFORMATION],
                eager_async=False,
                invalidate=True
            )
            
            actual_public_id = result.get('public_id', 'UNKNOWN')
            logger.info(f"   ✅ Cloudinary saved: {actual_public_id}")
            
            optimized_url = cloudinary.CloudinaryImage(result['public_id']).build_url(
                **CloudinaryService.ICON_IMAGE_TRANSFORMATION
            )
            
            logger.info(f"✅ Subtopic icon uploaded: {optimized_url}")
            
            return optimized_url
            
        except Exception as e:
            logger.error(f"❌ Failed to upload subtopic icon {subtopic_id}: {e}")
            logger.exception(e)
            return None


# ============================================
# Utility functions for cost optimization
# (Outside the class)
# ============================================

def get_optimized_video_url(cloudinary_url: str, quality: str = "auto:low") -> str:
    """
    Get video URL with specific quality settings for cost optimization
    """
    return cloudinary_url.replace('q_auto:low', f'q_{quality}')


def get_thumbnail_url(video_url: str, width: int = 200) -> str:
    """
    Generate thumbnail URL from video
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
