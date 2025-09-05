# gdpr_rights_service.py

import asyncpg
from datetime import datetime
from typing import Dict, Any
import uuid

class GDPRRightsService:
    """Dedicated service for GDPR user rights management"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool = None
    
    async def get_pool(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        return self.pool
    
    async def exercise_right_to_erasure(self, user_id: str) -> Dict[str, Any]:
        """Handle Right to be Forgotten"""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT handle_user_erasure($1)
            """, uuid.UUID(user_id))
            
            return {
                "request_type": "right_to_erasure",
                "status": "completed",
                "result": result,
                "processing_time": "immediate"
            }
    
    async def exercise_right_to_portability(self, user_id: str) -> Dict[str, Any]:
        """Handle Right to Data Portability"""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            # Get user profile data
            user_data = await conn.fetchrow("""
                SELECT created_at, learning_level, total_sessions, 
                       total_interactions, current_streak_days
                FROM brain_user WHERE id = $1
            """, uuid.UUID(user_id))
            
            # Get learning progress
            progress_data = await conn.fetch("""
                SELECT vocabulary_id, mastery_level, confidence_score, 
                       times_seen, times_correct
                FROM user_learning_progress WHERE user_id = $1
            """, uuid.UUID(user_id))
            
            return {
                "request_type": "right_to_portability",
                "status": "completed",
                "data": {
                    "user_profile": dict(user_data) if user_data else {},
                    "learning_progress": [dict(row) for row in progress_data],
                    "export_date": datetime.now().isoformat(),
                    "includes_audio": False
                }
            }
    
    async def get_user_data_inventory(self, user_id: str) -> Dict[str, Any]:
        """Get comprehensive user data inventory"""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            inventory = await conn.fetchrow("""
                SELECT 
                    bu.created_at as user_since,
                    bu.total_sessions,
                    bu.total_interactions,
                    bu.current_streak_days,
                    
                    -- AI Training Data
                    atc.consent_granted as ai_consent_active,
                    atc.granted_at as ai_consent_granted_at,
                    uati.total_recordings_contributed,
                    uati.current_active_recordings,
                    uati.next_scheduled_deletion as next_ai_deletion,
                    
                    -- Recent activity
                    (SELECT COUNT(*) FROM session_answer 
                     WHERE user_id = bu.id AND submitted_at > NOW() - INTERVAL '30 days') as recent_answers
                    
                FROM brain_user bu
                LEFT JOIN ai_training_consent atc ON bu.id = atc.user_id
                LEFT JOIN user_ai_training_inventory uati ON bu.id = uati.user_id
                WHERE bu.id = $1
            """, uuid.UUID(user_id))
            
            return dict(inventory) if inventory else {}
