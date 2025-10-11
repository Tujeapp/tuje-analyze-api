# session_management/bonus_malus_service.py
"""
Modular Bonus-Malus System
Each rule is independent and controlled from Airtable
"""
import asyncpg
import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class BonusMalusRule:
    """Represents a single bonus or malus rule"""
    
    def __init__(self, row: dict):
        self.id = row['id']
        self.name_en = row['name_en']
        self.rule_code = row['rule_code']
        self.bonus_malus_type = row['bonus_malus_type']
        self.value = row['value']
        self.priority = row['priority']
        self.level_from = row['level_from']
        self.level_to = row['level_to']
        self.conditions = row['conditions'] or {}
        self.live = row['live']
    
    def __repr__(self):
        return f"<BonusMalusRule {self.rule_code}: {self.value:+d}>"


class BonusMalusService:
    """
    Manages modular bonus-malus system
    All rules loaded from database (synced from Airtable)
    """
    
    def __init__(self):
        self.rules_cache = []
        self.cache_timestamp = None
        self.cache_ttl_seconds = 300  # 5 minutes
    
    async def load_rules(self, db_pool: asyncpg.Pool, force_refresh: bool = False):
        """
        Load all active bonus-malus rules from database
        
        Args:
            db_pool: Database connection pool
            force_refresh: Force reload even if cache valid
        """
        # Check cache validity
        if not force_refresh and self.cache_timestamp:
            age = (datetime.now() - self.cache_timestamp).seconds
            if age < self.cache_ttl_seconds:
                logger.debug(f"Using cached rules ({len(self.rules_cache)} rules)")
                return
        
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT *
                FROM brain_bonus_malus
                WHERE live = TRUE
                ORDER BY priority ASC
            """)
            
            self.rules_cache = [BonusMalusRule(dict(row)) for row in rows]
            self.cache_timestamp = datetime.now()
            
            logger.info(f"✅ Loaded {len(self.rules_cache)} bonus-malus rules")
    
    async def calculate_bonus_malus(
        self,
        user_id: str,
        interaction_id: str,
        user_level: int,
        db_pool: asyncpg.Pool
    ) -> Dict:
        """
        Calculate total bonus-malus for an interaction
        
        Args:
            user_id: User ID
            interaction_id: Current interaction ID
            user_level: User's current level
            db_pool: Database connection pool
            
        Returns:
            {
                "total": 5,
                "applied_rules": [
                    {"rule_code": "streak_bonus", "value": 5, "reason": "Good streaks"},
                    {"rule_code": "hint_malus", "value": -5, "reason": "Used 1 hint"}
                ]
            }
        """
        # Load rules
        await self.load_rules(db_pool)
        
        # Get user and interaction data
        context = await self._get_context(user_id, interaction_id, db_pool)
        
        total_bonus_malus = 0
        applied_rules = []
        
        # Apply each rule in priority order
        for rule in self.rules_cache:
            # Check if rule applies to user level
            if not (rule.level_from <= user_level <= rule.level_to):
                continue
            
            # Check if rule conditions are met
            should_apply, reason = await self._check_rule_conditions(
                rule, context, db_pool
            )
            
            if should_apply:
                # Apply the rule
                total_bonus_malus += rule.value
                
                applied_rules.append({
                    "rule_code": rule.rule_code,
                    "name": rule.name_en,
                    "value": rule.value,
                    "reason": reason
                })
                
                logger.info(f"✅ Applied {rule.rule_code}: {rule.value:+d} ({reason})")
        
        return {
            "total": total_bonus_malus,
            "applied_rules": applied_rules
        }
    
    async def _get_context(
        self,
        user_id: str,
        interaction_id: str,
        db_pool: asyncpg.Pool
    ) -> Dict:
        """
        Get all context data needed for rule evaluation
        
        Returns:
            {
                "user_id": "user_123",
                "streak7": 0.85,
                "streak30": 0.72,
                "hints_used": 1,
                "attempts_count": 2,
                ...
            }
        """
        async with db_pool.acquire() as conn:
            # Get user data
            user_data = await conn.fetchrow("""
                SELECT streak7, streak30, current_boredom
                FROM brain_user
                WHERE id = $1
            """, user_id)
            
            # Get interaction data
            interaction_data = await conn.fetchrow("""
                SELECT hints_used, attempts_count
                FROM session_interaction
                WHERE id = $1
            """, interaction_id)
            
            return {
                "user_id": user_id,
                "interaction_id": interaction_id,
                "streak7": float(user_data['streak7']) if user_data else 0,
                "streak30": float(user_data['streak30']) if user_data else 0,
                "hints_used": interaction_data['hints_used'] if interaction_data else 0,
                "attempts_count": interaction_data['attempts_count'] if interaction_data else 0,
            }
    
    async def _check_rule_conditions(
        self,
        rule: BonusMalusRule,
        context: Dict,
        db_pool: asyncpg.Pool
    ) -> tuple[bool, str]:
        """
        Check if a rule's conditions are met
        
        Returns:
            (should_apply: bool, reason: str)
        """
        # Route to specific rule handler based on rule_code
        if rule.rule_code == "streak_bonus":
            return await self._check_streak_bonus(rule, context)
        
        elif rule.rule_code == "hint_malus":
            return await self._check_hint_malus(rule, context)
        
        # Add more rule handlers here as you create new rules
        # elif rule.rule_code == "speed_bonus":
        #     return await self._check_speed_bonus(rule, context)
        
        else:
            logger.warning(f"Unknown rule_code: {rule.rule_code}")
            return (False, f"Unknown rule: {rule.rule_code}")
    
    # ========================================================================
    # RULE HANDLERS (Add new ones here as LEGO blocks)
    # ========================================================================
    
    async def _check_streak_bonus(
        self,
        rule: BonusMalusRule,
        context: Dict
    ) -> tuple[bool, str]:
        """
        Handler for streak_bonus rule
        
        Conditions from Airtable:
        {
            "streak7_min": 0.7,
            "streak30_min": 0.7
        }
        """
        conditions = rule.conditions
        streak7_min = conditions.get('streak7_min', 0.7)
        streak30_min = conditions.get('streak30_min', 0.7)
        
        user_streak7 = context.get('streak7', 0)
        user_streak30 = context.get('streak30', 0)
        
        if user_streak7 >= streak7_min and user_streak30 >= streak30_min:
            return (
                True,
                f"Good streaks (7d: {user_streak7:.2f}, 30d: {user_streak30:.2f})"
            )
        
        return (False, "Streaks not high enough")
    
    async def _check_hint_malus(
        self,
        rule: BonusMalusRule,
        context: Dict
    ) -> tuple[bool, str]:
        """
        Handler for hint_malus rule
        
        Conditions from Airtable:
        {
            "per_hint": true
        }
        
        This rule applies -5 per hint used
        """
        hints_used = context.get('hints_used', 0)
        
        if hints_used > 0:
            # Calculate malus: -5 per hint
            actual_value = rule.value * hints_used
            
            # Override rule value for this calculation
            rule.value = actual_value
            
            return (
                True,
                f"Used {hints_used} hint(s)"
            )
        
        return (False, "No hints used")
    
    # ========================================================================
    # ADD MORE RULE HANDLERS HERE AS YOU CREATE NEW RULES
    # ========================================================================
    
    # Example: Speed bonus (for future)
    async def _check_speed_bonus(
        self,
        rule: BonusMalusRule,
        context: Dict
    ) -> tuple[bool, str]:
        """
        Handler for speed_bonus rule (EXAMPLE for future)
        
        Conditions from Airtable:
        {
            "max_duration_seconds": 30
        }
        """
        # Get interaction duration
        duration = context.get('duration_seconds', 999)
        max_duration = rule.conditions.get('max_duration_seconds', 30)
        
        if duration <= max_duration:
            return (True, f"Fast answer ({duration}s)")
        
        return (False, "Too slow")


# Global service instance
bonus_malus_service = BonusMalusService()
