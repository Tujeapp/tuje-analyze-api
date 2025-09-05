# ai_training_service.py

import asyncpg
import logging
import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class AITrainingService:
    """Dedicated service for AI training data management"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool = None
    
    async def get_pool(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(self.database_url, min_size=2, max_size=10)
        return self.pool
    
    async def check_user_consent(self, user_id: str) -> Dict[str, Any]:
        """Check if user has active AI training consent"""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            consent_record = await conn.fetchrow("""
                SELECT id, consent_granted, granted_at
                FROM ai_training_consent 
                WHERE user_id = $1 AND consent_granted = true
            """, uuid.UUID(user_id))
            
            return {
                "has_consent": bool(consent_record),
                "consent_id": str(consent_record["id"]) if consent_record else None,
                "granted_at": consent_record["granted_at"] if consent_record else None
            }
    
    async def store_training_data(self, user_id: str, audio_metadata: Dict,
                                 processing_results: Dict, consent_metadata: Dict) -> Dict[str, Any]:
        """Store audio data for AI training with full GDPR compliance"""
        consent_info = await self.check_user_consent(user_id)
        if not consent_info["has_consent"]:
            return {"stored": False, "reason": "no_active_consent"}
        
        pool = await self.get_pool()
        training_record_id = uuid.uuid4()
        deletion_date = datetime.now() + timedelta(days=30)
        
        try:
            async with pool.acquire() as conn:
                # Generate secure identifiers
                audio_file_hash = hashlib.sha256(
                    f"{user_id}_{training_record_id}_{datetime.now()}".encode()
                ).hexdigest()
                encryption_key_id = str(uuid.uuid4())
                
                await conn.execute("""
                    INSERT INTO ai_training_data (
                        id, user_id, consent_record_id, audio_file_hash,
                        audio_file_path_encrypted, audio_duration_ms, audio_quality_score,
                        user_level, interaction_id, vocabulary_found, entities_found,
                        training_value_score, scheduled_deletion_at, encryption_key_id
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                """, 
                    training_record_id, uuid.UUID(user_id), uuid.UUID(consent_info["consent_id"]),
                    audio_file_hash, f"encrypted://eu-training-vault/{audio_file_hash}",
                    audio_metadata.get('duration_ms'), audio_metadata.get('confidence', 0.0),
                    audio_metadata.get('user_level'), audio_metadata.get('interaction_id'),
                    processing_results.get("vocabulary_found", []),
                    processing_results.get("entities_found", []),
                    85.0, deletion_date, encryption_key_id
                )
                
                # Update user inventory
                await self._update_user_inventory(user_id, conn)
                
                logger.info(f"✅ AI training data stored: {training_record_id}")
                
                return {
                    "stored": True,
                    "record_id": str(training_record_id),
                    "deletion_date": deletion_date.isoformat(),
                    "retention_days": 30
                }
                
        except Exception as e:
            logger.error(f"❌ AI training storage failed: {e}")
            return {"stored": False, "reason": f"storage_error: {str(e)}"}
    
    async def withdraw_consent(self, user_id: str) -> Dict[str, Any]:
        """Withdraw AI training consent and delete all data"""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT withdraw_ai_training_consent($1)
            """, uuid.UUID(user_id))
            
            return result
    
    async def get_user_inventory(self, user_id: str) -> Dict[str, Any]:
        """Get user's AI training data inventory"""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            inventory = await conn.fetchrow("""
                SELECT 
                    consent_granted,
                    granted_at,
                    total_recordings_contributed,
                    current_active_recordings,
                    next_scheduled_deletion
                FROM ai_training_consent atc
                LEFT JOIN user_ai_training_inventory uati ON atc.user_id = uati.user_id
                WHERE atc.user_id = $1
            """, uuid.UUID(user_id))
            
            return dict(inventory) if inventory else {}
    
    async def _update_user_inventory(self, user_id: str, conn):
        """Update user's training data inventory"""
        await conn.execute("""
            INSERT INTO user_ai_training_inventory (
                user_id, total_recordings_contributed, current_active_recordings
            ) VALUES ($1, 1, 1)
            ON CONFLICT (user_id) DO UPDATE SET
            total_recordings_contributed = user_ai_training_inventory.total_recordings_contributed + 1,
            current_active_recordings = user_ai_training_inventory.current_active_recordings + 1,
            updated_at = NOW()
        """, uuid.UUID(user_id))
