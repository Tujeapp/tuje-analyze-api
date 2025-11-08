"""
Updated Airtable Sync Routes with Cloudinary Integration
Add these functions to your existing airtable_routes.py
"""

import logging
from fastapi import BackgroundTasks, HTTPException
from typing import Dict, Optional
from uuid import UUID
from cloudinary_service import CloudinaryService
import asyncpg

logger = logging.getLogger(__name__)

# ================================================
# Enhanced sync function with Cloudinary upload
# ================================================

async def sync_interaction_with_cloudinary(
    entry_data: Dict,
    conn: asyncpg.Connection,
    background_tasks: BackgroundTasks
) -> None:
    """
    Sync interaction to database AND upload video to Cloudinary
    
    This replaces the current interaction sync logic
    """
    
    # 1. First, insert/update the interaction in database with pending status
    columns = [
        'id', 'airtable_record_id', 'last_modified_time_ref',
        'answer_ids', 'hint_ids', 'interaction_type_id',
        'interaction_optimum_level', 'name_fr', 'name_en',
        'level_owned', 'level_from', 'level_to',
        'session_mood_ids', 'subtopic_id', 'interaction_vocab_id',
        'expected_entities_id', 'expected_vocab_id', 'expected_notion_id',
        'video_fr', 'video_upload_status',  # Add new status field
        'created_at', 'last_modified'
    ]
    
    placeholders = ', '.join([f'${i+1}' for i in range(len(columns))])
    update_columns = [col for col in columns if col != 'id']
    update_set = ', '.join([f'{col} = EXCLUDED.{col}' for col in update_columns])
    
    query = f"""
        INSERT INTO brain_interaction ({', '.join(columns)})
        VALUES ({placeholders})
        ON CONFLICT (id) DO UPDATE SET {update_set}
        RETURNING id, subtopic_id, level_owned, name_fr, video_fr;
    """
    
    # Prepare values
    values = []
    for col in columns:
        if col == 'video_upload_status':
            # Set to 'uploading' if we have a video, otherwise 'pending'
            video_url = entry_data.get('video_fr')
            values.append('uploading' if video_url else 'pending')
        elif col in ['answer_ids', 'hint_ids', 'session_mood_ids', 'interaction_vocab_id',
                     'expected_entities_id', 'expected_vocab_id', 'expected_notion_id']:
            values.append(entry_data.get(col, []))
        else:
            values.append(entry_data.get(col))
    
    # Execute insert/update
    result = await conn.fetchrow(query, *values)
    
    # 2. If video exists, queue Cloudinary upload in background
    video_url = entry_data.get('video_fr')
    if video_url and video_url.strip():
        background_tasks.add_task(
            upload_video_to_cloudinary_and_update_db,
            interaction_id=result['id'],
            airtable_video_url=video_url,
            subtopic_id=result['subtopic_id'],
            level=result['level_owned'],
            subtopic_name=result['name_fr'] or 'unknown'
        )
        logger.info(f"✅ Queued Cloudinary upload for interaction {result['id']}")
    
    logger.info(f"✅ Interaction synced: {result['id']}")


async def sync_subtopic_with_cloudinary(
    entry_data: Dict,
    conn: asyncpg.Connection,
    background_tasks: BackgroundTasks
) -> None:
    """
    Sync subtopic to database AND upload image to Cloudinary
    """
    
    columns = [
        'id', 'airtable_record_id', 'last_modified_time_ref',
        'name_fr', 'name_en', 'description_fr', 'description_en',
        'interaction_ids', 'image_fr', 'image_upload_status',
        'created_at', 'last_modified'
    ]
    
    placeholders = ', '.join([f'${i+1}' for i in range(len(columns))])
    update_columns = [col for col in columns if col != 'id']
    update_set = ', '.join([f'{col} = EXCLUDED.{col}' for col in update_columns])
    
    query = f"""
        INSERT INTO brain_subtopic ({', '.join(columns)})
        VALUES ({placeholders})
        ON CONFLICT (id) DO UPDATE SET {update_set}
        RETURNING id, name_fr, image_fr;
    """
    
    # Prepare values
    values = []
    for col in columns:
        if col == 'image_upload_status':
            image_url = entry_data.get('image_fr')
            values.append('uploading' if image_url else 'pending')
        elif col == 'interaction_ids':
            values.append(entry_data.get(col, []))
        else:
            values.append(entry_data.get(col))
    
    result = await conn.fetchrow(query, *values)
    
    # Queue Cloudinary upload
    image_url = entry_data.get('image_fr')
    if image_url and image_url.strip():
        background_tasks.add_task(
            upload_image_to_cloudinary_and_update_db,
            subtopic_id=result['id'],
            airtable_image_url=image_url,
            subtopic_name=result['name_fr'] or 'unknown'
        )
        logger.info(f"✅ Queued Cloudinary upload for subtopic {result['id']}")
    
    logger.info(f"✅ Subtopic synced: {result['id']}")


# ================================================
# Background tasks for Cloudinary uploads
# ================================================

async def upload_video_to_cloudinary_and_update_db(
    interaction_id: UUID,
    airtable_video_url: str,
    subtopic_id: Optional[UUID],
    level: int,
    subtopic_name: str
) -> None:
    """
    Background task: Upload video to Cloudinary and update database
    
    This runs asynchronously after the API response is sent
    """
    try:
        logger.info(f"🎥 Starting Cloudinary upload for interaction {interaction_id}")
        
        # Upload to Cloudinary
        cloudinary_url = await CloudinaryService.upload_video_from_url(
            airtable_url=airtable_video_url,
            interaction_id=str(interaction_id),
            subtopic_name=subtopic_name,
            level=level
        )
        
        if not cloudinary_url:
            raise Exception("Cloudinary upload returned None")
        
        # Generate poster URL
        poster_url = CloudinaryService.get_video_poster_url(cloudinary_url, frame_offset=2.0)
        
        # Update database
        async with db_pool.get_connection() as conn:
            await conn.execute("""
                UPDATE brain_interaction
                SET video_cloudinary_url = $1,
                    video_poster_url = $2,
                    video_upload_status = 'completed',
                    video_uploaded_at = NOW()
                WHERE id = $3
            """, cloudinary_url, poster_url, interaction_id)
            
            # Track in cloudinary_uploads table
            await conn.execute("""
                INSERT INTO cloudinary_uploads (
                    entity_type, entity_id, airtable_record_id,
                    original_url, cloudinary_public_id, cloudinary_url,
                    resource_type, upload_status, uploaded_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                ON CONFLICT (cloudinary_public_id) DO UPDATE
                SET cloudinary_url = EXCLUDED.cloudinary_url,
                    upload_status = 'completed',
                    uploaded_at = NOW()
            """, 
                'interaction', interaction_id, None,
                airtable_video_url, 
                cloudinary_url.split('/')[-1].split('.')[0],  # Extract public_id
                cloudinary_url,
                'video', 'completed'
            )
        
        logger.info(f"✅ Video uploaded successfully for interaction {interaction_id}")
        logger.info(f"   Cloudinary URL: {cloudinary_url}")
        logger.info(f"   Poster URL: {poster_url}")
        
    except Exception as e:
        logger.error(f"❌ Failed to upload video for interaction {interaction_id}: {e}")
        
        # Update status to failed
        try:
            async with db_pool.get_connection() as conn:
                await conn.execute("""
                    UPDATE brain_interaction
                    SET video_upload_status = 'failed'
                    WHERE id = $1
                """, interaction_id)
                
                # Track failure
                await conn.execute("""
                    INSERT INTO cloudinary_uploads (
                        entity_type, entity_id, original_url,
                        cloudinary_public_id, cloudinary_url, resource_type,
                        upload_status, error_message, upload_attempts,
                        last_attempt_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                    ON CONFLICT (cloudinary_public_id) DO UPDATE
                    SET upload_status = 'failed',
                        error_message = EXCLUDED.error_message,
                        upload_attempts = cloudinary_uploads.upload_attempts + 1,
                        last_attempt_at = NOW()
                """,
                    'interaction', interaction_id, airtable_video_url,
                    f"int_{interaction_id}", '', 'video',
                    'failed', str(e), 1
                )
        except Exception as db_error:
            logger.error(f"❌ Failed to update failure status: {db_error}")


async def upload_image_to_cloudinary_and_update_db(
    subtopic_id: UUID,
    airtable_image_url: str,
    subtopic_name: str
) -> None:
    """
    Background task: Upload image to Cloudinary and update database
    """
    try:
        logger.info(f"🖼️ Starting Cloudinary upload for subtopic {subtopic_id}")
        
        # Upload to Cloudinary
        cloudinary_url = await CloudinaryService.upload_image_from_url(
            airtable_url=airtable_image_url,
            subtopic_id=str(subtopic_id),
            subtopic_name=subtopic_name,
            image_type="subtopic"
        )
        
        if not cloudinary_url:
            raise Exception("Cloudinary upload returned None")
        
        # Update database
        async with db_pool.get_connection() as conn:
            await conn.execute("""
                UPDATE brain_subtopic
                SET image_cloudinary_url = $1,
                    image_upload_status = 'completed',
                    image_uploaded_at = NOW()
                WHERE id = $2
            """, cloudinary_url, subtopic_id)
            
            # Track in cloudinary_uploads table
            await conn.execute("""
                INSERT INTO cloudinary_uploads (
                    entity_type, entity_id, original_url,
                    cloudinary_public_id, cloudinary_url, resource_type,
                    upload_status, uploaded_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                ON CONFLICT (cloudinary_public_id) DO UPDATE
                SET cloudinary_url = EXCLUDED.cloudinary_url,
                    upload_status = 'completed',
                    uploaded_at = NOW()
            """,
                'subtopic', subtopic_id, airtable_image_url,
                cloudinary_url.split('/')[-1].split('.')[0],
                cloudinary_url, 'image', 'completed'
            )
        
        logger.info(f"✅ Image uploaded successfully for subtopic {subtopic_id}")
        logger.info(f"   Cloudinary URL: {cloudinary_url}")
        
    except Exception as e:
        logger.error(f"❌ Failed to upload image for subtopic {subtopic_id}: {e}")
        
        # Update status to failed
        try:
            async with db_pool.get_connection() as conn:
                await conn.execute("""
                    UPDATE brain_subtopic
                    SET image_upload_status = 'failed'
                    WHERE id = $1
                """, subtopic_id)
                
                # Track failure
                await conn.execute("""
                    INSERT INTO cloudinary_uploads (
                        entity_type, entity_id, original_url,
                        cloudinary_public_id, cloudinary_url, resource_type,
                        upload_status, error_message, upload_attempts,
                        last_attempt_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                    ON CONFLICT (cloudinary_public_id) DO UPDATE
                    SET upload_status = 'failed',
                        error_message = EXCLUDED.error_message,
                        upload_attempts = cloudinary_uploads.upload_attempts + 1,
                        last_attempt_at = NOW()
                """,
                    'subtopic', subtopic_id, airtable_image_url,
                    f"sub_{subtopic_id}", '', 'image',
                    'failed', str(e), 1
                )
        except Exception as db_error:
            logger.error(f"❌ Failed to update failure status: {db_error}")


# ================================================
# New endpoint: Retry failed uploads
# ================================================

@router.post("/retry-failed-uploads")
async def retry_failed_uploads(background_tasks: BackgroundTasks):
    """
    Retry all failed Cloudinary uploads
    """
    try:
        async with db_pool.get_connection() as conn:
            # Get failed uploads
            failed_uploads = await conn.fetch("""
                SELECT entity_type, entity_id, original_url
                FROM cloudinary_uploads
                WHERE upload_status = 'failed' 
                AND upload_attempts < 3
                ORDER BY last_attempt_at ASC
                LIMIT 50
            """)
            
            if not failed_uploads:
                return {
                    "message": "No failed uploads to retry",
                    "count": 0
                }
            
            # Queue retry tasks
            for upload in failed_uploads:
                if upload['entity_type'] == 'interaction':
                    # Get interaction details
                    interaction = await conn.fetchrow("""
                        SELECT id, subtopic_id, level_owned, name_fr
                        FROM brain_interaction
                        WHERE id = $1
                    """, upload['entity_id'])
                    
                    if interaction:
                        background_tasks.add_task(
                            upload_video_to_cloudinary_and_update_db,
                            interaction_id=interaction['id'],
                            airtable_video_url=upload['original_url'],
                            subtopic_id=interaction['subtopic_id'],
                            level=interaction['level_owned'],
                            subtopic_name=interaction['name_fr'] or 'unknown'
                        )
                
                elif upload['entity_type'] == 'subtopic':
                    # Get subtopic details
                    subtopic = await conn.fetchrow("""
                        SELECT id, name_fr
                        FROM brain_subtopic
                        WHERE id = $1
                    """, upload['entity_id'])
                    
                    if subtopic:
                        background_tasks.add_task(
                            upload_image_to_cloudinary_and_update_db,
                            subtopic_id=subtopic['id'],
                            airtable_image_url=upload['original_url'],
                            subtopic_name=subtopic['name_fr'] or 'unknown'
                        )
            
            return {
                "message": f"Queued {len(failed_uploads)} uploads for retry",
                "count": len(failed_uploads)
            }
            
    except Exception as e:
        logger.error(f"❌ Failed to retry uploads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================
# New endpoint: Get upload statistics
# ================================================

@router.get("/upload-stats")
async def get_upload_stats():
    """
    Get statistics about Cloudinary uploads
    """
    try:
        async with db_pool.get_connection() as conn:
            # Interaction stats
            interaction_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE video_cloudinary_url IS NOT NULL) as migrated,
                    COUNT(*) FILTER (WHERE video_upload_status = 'pending') as pending,
                    COUNT(*) FILTER (WHERE video_upload_status = 'failed') as failed
                FROM brain_interaction
                WHERE video_fr IS NOT NULL
            """)
            
            # Subtopic stats
            subtopic_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE image_cloudinary_url IS NOT NULL) as migrated,
                    COUNT(*) FILTER (WHERE image_upload_status = 'pending') as pending,
                    COUNT(*) FILTER (WHERE image_upload_status = 'failed') as failed
                FROM brain_subtopic
                WHERE image_fr IS NOT NULL
            """)
            
            # Storage stats from cloudinary_uploads
            storage_stats = await conn.fetchrow("""
                SELECT 
                    SUM(file_size_bytes) / 1024.0 / 1024.0 as total_mb,
                    COUNT(*) FILTER (WHERE resource_type = 'video') as video_count,
                    COUNT(*) FILTER (WHERE resource_type = 'image') as image_count
                FROM cloudinary_uploads
                WHERE upload_status = 'completed'
            """)
            
            return {
                "interactions": {
                    "total": interaction_stats['total'],
                    "migrated": interaction_stats['migrated'],
                    "pending": interaction_stats['pending'],
                    "failed": interaction_stats['failed'],
                    "progress_percent": round(
                        (interaction_stats['migrated'] / interaction_stats['total'] * 100) 
                        if interaction_stats['total'] > 0 else 0, 
                        2
                    )
                },
                "subtopics": {
                    "total": subtopic_stats['total'],
                    "migrated": subtopic_stats['migrated'],
                    "pending": subtopic_stats['pending'],
                    "failed": subtopic_stats['failed'],
                    "progress_percent": round(
                        (subtopic_stats['migrated'] / subtopic_stats['total'] * 100) 
                        if subtopic_stats['total'] > 0 else 0, 
                        2
                    )
                },
                "storage": {
                    "total_mb": round(storage_stats['total_mb'] or 0, 2),
                    "video_count": storage_stats['video_count'],
                    "image_count": storage_stats['image_count']
                }
            }
            
    except Exception as e:
        logger.error(f"❌ Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
