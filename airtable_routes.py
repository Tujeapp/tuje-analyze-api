import os
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
import asyncpg
from pydantic import BaseModel, validator
from datetime import datetime
from typing import List, Optional, Dict, Any
import time
import logging
from contextlib import asynccontextmanager

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load env vars
DATABASE_URL = os.getenv("DATABASE_URL")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")

# Safety checks
for var_name, var_value in [("DATABASE_URL", DATABASE_URL), ("AIRTABLE_API_KEY", AIRTABLE_API_KEY), ("AIRTABLE_BASE_ID", AIRTABLE_BASE_ID)]:
    if not var_value:
        raise RuntimeError(f"Missing required environment variable: {var_name}")

# Setup router
router = APIRouter()

# Airtable config
AIRTABLE_BASE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"
HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json"
}

# Connection pool for better performance
class DatabasePool:
    def __init__(self):
        self._pool = None
    
    async def get_pool(self):
        if self._pool is None:
            self._pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        return self._pool
    
    @asynccontextmanager
    async def get_connection(self):
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            yield conn

# Global pool instance
db_pool = DatabasePool()

# Enhanced Pydantic Models with validation
class BaseEntry(BaseModel):
    id: str
    airtableRecordId: str
    lastModifiedTimeRef: int
    createdAt: int
    live: bool = True
    
    @validator('id')
    def validate_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('ID cannot be empty')
        return v.strip()
    
    @validator('lastModifiedTimeRef', 'createdAt')
    def validate_timestamps(cls, v):
        if v <= 0:
            raise ValueError('Timestamp must be positive')
        # Check if timestamp is reasonable (allow 5 years range)
        current_time = int(datetime.now().timestamp() * 1000)
        five_years_ms = 5 * 365 * 24 * 60 * 60 * 1000
        if abs(v - current_time) > five_years_ms:
            raise ValueError('Timestamp seems unrealistic')
        return v

class AnswerEntry(BaseEntry):
    transcriptionFr: str
    transcriptionEn: str
    transcriptionAdjusted: str
    answerOptimumLevel: Optional[int] = None

class BonusMalusEntry(BaseEntry):
    nameFr: str
    nameEn: str
    description: str
    levelFrom: int
    levelTo: int
    
    @validator('nameFr', 'nameEn', 'description')
    def validate_text_fields(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Text fields cannot be empty')
        return v.strip()
    
    @validator('levelFrom', 'levelTo')
    def validate_level_fields(cls, v):
        if v < 0 or v > 500:  # Adjust range as needed
            raise ValueError('Level must be between 0 and 100')
        return v
    
    @validator('levelTo')
    def validate_level_range(cls, v, values):
        if 'levelFrom' in values and v < values['levelFrom']:
            raise ValueError('levelTo must be greater than or equal to levelFrom')
        return v

class InteractionEntry(BaseEntry):
    transcriptionFr: str
    transcriptionEn: str
    intents: List[str] = []
    subtopicId: Optional[str] = None
    expectedEntitiesIds: Optional[List[str]] = []
    expectedVocabIds: Optional[List[str]] = []
    expectedNotionIds: Optional[List[str]] = []
    interactionVocabIds: Optional[List[str]] = []  # NEW: Add interaction vocab IDs
    
    @validator('expectedEntitiesIds')
    def clean_expected_entities_ids(cls, v):
        """Clean expected entities list"""
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        cleaned = [str(entity_id).strip() for entity_id in v if entity_id and str(entity_id).strip()]
        return cleaned
    
    @validator('expectedVocabIds')
    def clean_expected_vocab_ids(cls, v):
        """Clean expected vocab IDs list"""
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        cleaned = [str(vocab_id).strip() for vocab_id in v if vocab_id and str(vocab_id).strip()]
        return cleaned

    @validator('expectedNotionIds')
    def clean_expected_notion_ids(cls, v):
        """Clean expected notion IDs list"""
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        cleaned = [str(notion_id).strip() for notion_id in v if notion_id and str(notion_id).strip()]
        return cleaned

    @validator('interactionVocabIds')
    def clean_interaction_vocab_ids(cls, v):
        """Clean interaction vocab IDs list"""
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        cleaned = [str(vocab_id).strip() for vocab_id in v if vocab_id and str(vocab_id).strip()]
        return cleaned

class NotionEntry(BaseEntry):
    nameFr: str
    nameEn: str
    description: str
    rank: int
    score: float
    levelFrom: int
    levelOwned: int
    
    @validator('nameFr', 'nameEn', 'description')
    def validate_text_fields(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Text fields cannot be empty')
        return v.strip()
    
    @validator('rank', 'levelFrom', 'levelOwned')
    def validate_numeric_fields(cls, v):
        if v < 0:
            raise ValueError('Numeric fields must be non-negative')
        return v
    
    @validator('score')
    def validate_score(cls, v):
        if v < 0:
            raise ValueError('Score must be non-negative')
        return v

class VocabEntry(BaseEntry):
    transcriptionFr: str
    transcriptionEn: str
    transcriptionAdjusted: str
    entityTypeId: Optional[str] = None
    expectedNotionIds: Optional[List[str]] = []
    expectedIntentIds: Optional[List[str]] = []  # NEW: Add expected intent IDs
    
    @validator('entityTypeId')
    def clean_entity_type_id(cls, v):
        """Clean entity type ID - handle empty strings"""
        if v is not None:
            v = str(v).strip()
            if len(v) == 0:
                return None
        return v
    
    @validator('expectedNotionIds')
    def clean_expected_notion_ids(cls, v):
        """Clean expected notion IDs list"""
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        cleaned = [str(notion_id).strip() for notion_id in v if notion_id and str(notion_id).strip()]
        return cleaned
    
    @validator('expectedIntentIds')  # NEW: Add validator for intent IDs
    def clean_expected_intent_ids(cls, v):
        """Clean expected intent IDs list"""
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        cleaned = [str(intent_id).strip() for intent_id in v if intent_id and str(intent_id).strip()]
        return cleaned

class IntentEntry(BaseEntry):
    name: str
    description: str

class SubtopicEntry(BaseEntry):
    nameFr: str
    nameEn: str

class InteractionAnswerEntry(BaseEntry):
    interaction_id: str
    answer_id: str
    
    @validator('interaction_id', 'answer_id')
    def validate_ids(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Interaction ID and Answer ID cannot be empty')
        return v.strip()

class EntityEntry(BaseEntry):
    name: str
    description: str
    priority: int  # numeric type in your schema
    
    @validator('name')
    def validate_name(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Entity name cannot be empty')
        return v.strip()
    
    @validator('priority')
    def validate_priority(cls, v):
        if v < 0 or v > 1000:  # Reasonable priority range
            raise ValueError('Priority must be between 0 and 1000')
        return v

# Generic sync configuration
SYNC_CONFIGS = {
    "answer": {
        "table_name": "brain_answer",
        "airtable_table": "Answer",
        "columns": ["id", "transcription_fr", "transcription_en", "transcription_adjusted",
                   "answer_optimum_level",  # NEW: Add this line
                   "airtable_record_id", "last_modified_time_ref", "created_at", "update_at", "live"]
    },
    "interaction": {
        "table_name": "brain_interaction",
        "airtable_table": "Interaction",
        "columns": ["id", "transcription_fr", "transcription_en", "airtable_record_id",
                   "last_modified_time_ref", "created_at", "update_at", "live", 
                   "intents", "subtopic_id", "expected_entities_id", "expected_vocab_id", 
                   "expected_notion_id", "interaction_vocab_id"]  # NEW: Add interaction_vocab_id
    },
    "vocab": {
        "table_name": "brain_vocab",
        "airtable_table": "Vocab",
        "columns": ["id", "transcription_fr", "transcription_en", "transcription_adjusted",
                   "entity_type_id", "expected_notion_id", "expected_intent_id",  # NEW: Add expected_intent_id
                   "airtable_record_id", "last_modified_time_ref", 
                   "created_at", "update_at", "live"]
    },
    "intent": {
        "table_name": "brain_intent",
        "airtable_table": "Intent",
        "columns": ["id", "name", "description", "airtable_record_id",
                   "last_modified_time_ref", "created_at", "update_at", "live"]
    },
        "notion": {
        "table_name": "brain_notion",
        "airtable_table": "Notion",
        "columns": ["id", "name_fr", "name_en", "description", "rank", "live", 
                   "score", "level_from", "level_owned", "airtable_record_id", 
                   "last_modified_time_ref", "created_at", "update_at"]
    },
    "subtopic": {
        "table_name": "brain_subtopic",
        "airtable_table": "Subtopic",
        "columns": ["id", "name_fr", "name_en", "airtable_record_id",
                   "last_modified_time_ref", "created_at", "update_at", "live"]
    },
    "interaction_answer": {
        "table_name": "brain_interaction_answer",
        "airtable_table": "Interaction-Answer",
        "columns": ["id", "interaction_id", "answer_id", "airtable_record_id",
                   "last_modified_time_ref", "created_at", "update_at", "live"]
    },
    "entity": {
        "table_name": "brain_entity",
        "airtable_table": "Entity",
        "columns": ["id", "name", "description", "priority", 
                   "created_at", "update_at", "airtable_record_id", 
                   "last_modified_time_ref", "live"]
    },
    "bonus_malus": {
        "table_name": "brain_bonus_malus",
        "airtable_table": "Bonus-Malus",
        "columns": ["id", "name_fr", "name_en", "description", "level_from", "level_to",
                   "airtable_record_id", "last_modified_time_ref", 
                   "created_at", "update_at", "live"]
    }
}

# Utility functions
def convert_timestamps(entry_data: Dict) -> Dict:
    """Convert timestamp fields from milliseconds to datetime"""
    result = entry_data.copy()
    if 'createdAt' in result:
        result['created_at'] = datetime.utcfromtimestamp(result.pop('createdAt') / 1000)
    if 'lastModifiedTimeRef' in result:
        timestamp = result.pop('lastModifiedTimeRef')
        result['last_modified_time_ref'] = timestamp
        result['update_at'] = datetime.utcfromtimestamp(timestamp / 1000)  # ✅ Now matches your schema
    return result

def convert_timestamps(entry_data: Dict) -> Dict:
    """Convert timestamp fields from milliseconds to datetime"""
    result = entry_data.copy()
    if 'createdAt' in result:
        result['created_at'] = datetime.utcfromtimestamp(result.pop('createdAt') / 1000)
    if 'lastModifiedTimeRef' in result:
        timestamp = result.pop('lastModifiedTimeRef')
        result['last_modified_time_ref'] = timestamp
        result['update_at'] = datetime.utcfromtimestamp(timestamp / 1000)
    return result

def prepare_entry_data(entry: BaseEntry, entity_type: str) -> Dict:
    """Convert Pydantic model to database-ready dict"""
    data = entry.dict()
    
    # Convert field names for database
    field_mappings = {
        "transcriptionFr": "transcription_fr",
        "transcriptionEn": "transcription_en", 
        "transcriptionAdjusted": "transcription_adjusted",
        "answerOptimumLevel": "answer_optimum_level",
        "entityTypeId": "entity_type_id",
        "expectedNotionIds": "expected_notion_id",
        "expectedIntentIds": "expected_intent_id",  # NEW: Add intent mapping
        "expectedEntitiesIds": "expected_entities_id",
        "expectedVocabIds": "expected_vocab_id",
        "interactionVocabIds": "interaction_vocab_id",
        "airtableRecordId": "airtable_record_id",
        "nameFr": "name_fr",
        "nameEn": "name_en",
        "levelFrom": "level_from",
        "levelOwned": "level_owned",
        "levelTo": "level_to",
        "subtopicId": "subtopic_id"
    }
    
    for old_key, new_key in field_mappings.items():
        if old_key in data:
            data[new_key] = data.pop(old_key)
    
    return convert_timestamps(data)

# Enhanced Airtable update with retry logic
async def update_airtable_status(record_id: str, fields: dict, table_name: str, max_retries: int = 2):
    """Update Airtable with retry logic"""
    url = f"{AIRTABLE_BASE_URL}/{table_name}/{record_id}"
    payload = {"fields": fields}
    
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.patch(url, json=payload, headers=HEADERS)
                response.raise_for_status()
                logger.info(f"Airtable updated: {table_name}/{record_id}")
                return
                
        except httpx.TimeoutException:
            if attempt < max_retries:
                logger.warning(f"Airtable timeout, retrying {attempt + 1}/{max_retries}")
                await asyncio.sleep(1)
                continue
            logger.error(f"Airtable update failed after {max_retries} retries")
            raise HTTPException(status_code=408, detail="Airtable update timeout")
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Airtable API error: {e.response.status_code}")
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)

# Generic sync function
async def sync_entity_to_database(entry_data: Dict, config: Dict) -> None:
    """Generic function to sync any entity to database with array handling"""
    async with db_pool.get_connection() as conn:
        async with conn.transaction():
            
            # Build dynamic query
            columns = config["columns"]
            placeholders = ', '.join([f'${i+1}' for i in range(len(columns))])
            update_columns = [col for col in columns if col != 'id']
            update_set = ', '.join([f'{col} = EXCLUDED.{col}' for col in update_columns])
            
            query = f"""
                INSERT INTO {config["table_name"]} ({', '.join(columns)})
                VALUES ({placeholders})
                ON CONFLICT (id) DO UPDATE SET {update_set};
            """
            
            # Handle special cases (arrays, etc.)
            values = []
            for col in columns:
                value = entry_data.get(col)
                # CHANGE 1: Add 'expected_intent_id' to this list (just add it to the existing list)
                if col in ['intents', 'expected_entities_id', 'expected_vocab_id', 'expected_notion_id', 'expected_intent_id', 'interaction_vocab_id'] and isinstance(value, list):
                    values.append(value)  # PostgreSQL will handle the array
                else:
                    values.append(value)
            
            await conn.execute(query, *values)
            
            # Enhanced logging for vocab syncing
            if config["table_name"] == "brain_vocab":
                # CHANGE 2: Add expected_intent_id to the logging (just add it to the existing log)
                logger.info(f"Vocab synced: id={entry_data.get('id')}, "
                           f"entity_type_id={entry_data.get('entity_type_id')}, "
                           f"expected_notion_id={entry_data.get('expected_notion_id')}, "
                           f"expected_intent_id={entry_data.get('expected_intent_id')}")
            elif config["table_name"] == "brain_interaction":
                logger.info(f"Interaction synced: id={entry_data.get('id')}, "
                           f"expected_entities_id={entry_data.get('expected_entities_id')}, "
                           f"expected_vocab_id={entry_data.get('expected_vocab_id')}, "
                           f"expected_notion_id={entry_data.get('expected_notion_id')}, "
                           f"interaction_vocab_id={entry_data.get('interaction_vocab_id')}")

# Background task for Airtable updates
async def background_airtable_update(record_id: str, timestamp: int, table_name: str):
    """Background task to update Airtable without blocking the response"""
    try:
        await update_airtable_status(
            record_id=record_id,
            fields={"LastModifiedSaved": timestamp},
            table_name=table_name
        )
    except Exception as e:
        logger.error(f"Background Airtable update failed: {e}")

# Generic webhook endpoint
async def generic_sync_webhook(entry: BaseEntry, entity_type: str, background_tasks: BackgroundTasks):
    """Generic webhook handler for all entity types"""
    start_time = time.time()
    
    try:
        logger.info(f"Starting {entity_type} sync for {entry.id}")
        
        config = SYNC_CONFIGS[entity_type]
        entry_data = prepare_entry_data(entry, entity_type)
        
        # Sync to database
        await sync_entity_to_database(entry_data, config)
        
        # Queue background Airtable update
        background_tasks.add_task(
            background_airtable_update,
            entry.airtableRecordId,
            entry.lastModifiedTimeRef,
            config["airtable_table"]
        )
        
        elapsed = time.time() - start_time
        logger.info(f"{entity_type.title()} sync completed in {elapsed:.2f}s")
        
        return {
            "message": f"{entity_type.title()} synced successfully",
            "entry_id": entry.id,
            "airtable_record_id": entry.airtableRecordId,
            "last_modified_time_ref": entry.lastModifiedTimeRef,
            "execution_time": f"{elapsed:.2f}s"
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"{entity_type.title()} sync failed after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Specific webhook endpoints using the generic function
@router.post("/webhook-sync-answer")
async def webhook_sync_answer(entry: AnswerEntry, background_tasks: BackgroundTasks):
    return await generic_sync_webhook(entry, "answer", background_tasks)

@router.post("/webhook-sync-interaction")
async def webhook_sync_interaction(entry: InteractionEntry, background_tasks: BackgroundTasks):
    return await generic_sync_webhook(entry, "interaction", background_tasks)

@router.post("/webhook-sync-vocab")
async def webhook_sync_vocab(entry: VocabEntry, background_tasks: BackgroundTasks):
    return await generic_sync_webhook(entry, "vocab", background_tasks)

@router.post("/webhook-sync-intent")
async def webhook_sync_intent(entry: IntentEntry, background_tasks: BackgroundTasks):
    return await generic_sync_webhook(entry, "intent", background_tasks)

@router.post("/webhook-sync-subtopic")
async def webhook_sync_subtopic(entry: SubtopicEntry, background_tasks: BackgroundTasks):
    return await generic_sync_webhook(entry, "subtopic", background_tasks)

@router.post("/webhook-sync-interaction-answer")
async def webhook_sync_interaction_answer(entry: InteractionAnswerEntry, background_tasks: BackgroundTasks):
    return await generic_sync_webhook(entry, "interaction_answer", background_tasks)

@router.post("/webhook-sync-entity")
async def webhook_sync_entity(entry: EntityEntry, background_tasks: BackgroundTasks):
    return await generic_sync_webhook(entry, "entity", background_tasks)

@router.post("/webhook-sync-notion")
async def webhook_sync_notion(entry: NotionEntry, background_tasks: BackgroundTasks):
    """Webhook endpoint to sync notion data from Airtable"""
    return await generic_sync_webhook(entry, "notion", background_tasks)

@router.post("/webhook-sync-bonus-malus")
async def webhook_sync_bonus_malus(entry: BonusMalusEntry, background_tasks: BackgroundTasks):
    """Webhook endpoint to sync bonus-malus data from Airtable"""
    return await generic_sync_webhook(entry, "bonus_malus", background_tasks)

# Health check endpoint
@router.get("/sync-health")
async def sync_health():
    """Health check for sync services"""
    try:
        # Test database connection
        async with db_pool.get_connection() as conn:
            await conn.fetchval("SELECT 1")
        
        # Test Airtable connection
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{AIRTABLE_BASE_URL}/Answer", headers=HEADERS, params={"maxRecords": 1})
            response.raise_for_status()
        
        return {"status": "healthy", "database": "ok", "airtable": "ok"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}
        
