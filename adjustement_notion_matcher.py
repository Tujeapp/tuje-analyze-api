# adjustement_notion_matcher.py
"""
SINGLE RESPONSIBILITY: Match vocabulary notions with interaction expected notions
"""
import logging
from typing import List, Set, Dict, Any
from adjustement_cache_manager import VocabularyCacheManager
from adjustement_types import VocabularyMatch

logger = logging.getLogger(__name__)

class NotionMatcher:
    """Handles notion matching between vocabulary and interaction expectations"""
    
    def __init__(self):
        pass
    
    async def find_notion_matches(
        self, 
        interaction_id: str,
        vocabulary_matches: List[VocabularyMatch],
        cache_manager: VocabularyCacheManager
    ) -> List[str]:
        """
        Find notion matches between vocabulary found and interaction expectations
        Returns: List of notion IDs that match
        """
        logger.info(f"🎯 Starting notion matching for interaction {interaction_id}")
        logger.info(f"📚 Analyzing {len(vocabulary_matches)} vocabulary entries")
        
        try:
            # Step 1: Get interaction expected notions
            interaction_expected_notions = await self._get_interaction_expected_notions(
                interaction_id, cache_manager
            )
            
            if not interaction_expected_notions:
                logger.info("⚠️ No expected notions found for interaction")
                return []
            
            logger.info(f"🎯 Interaction expects notions: {interaction_expected_notions}")
            
            # Step 2: Get vocabulary expected notions for all found vocabulary
            vocabulary_notion_sets = await self._get_vocabulary_notion_sets(
                vocabulary_matches, cache_manager
            )
            
            # Step 3: Find intersections
            matched_notion_ids = self._find_notion_intersections(
                interaction_expected_notions, vocabulary_notion_sets
            )
            
            logger.info(f"✅ Found {len(matched_notion_ids)} notion matches: {matched_notion_ids}")
            return matched_notion_ids
            
        except Exception as e:
            logger.error(f"❌ Notion matching failed: {e}")
            return []  # Return empty list on error to not break the adjustment process
    
    async def _get_interaction_expected_notions(
        self, 
        interaction_id: str, 
        cache_manager: VocabularyCacheManager
    ) -> Set[str]:
        """Get expected notion IDs for the interaction"""
        try:
            # Use the existing database connection through cache manager
            pool = await cache_manager._get_database_pool()
            
            async with pool.acquire() as conn:
                result = await conn.fetchrow("""
                    SELECT expected_notion_id
                    FROM brain_interaction
                    WHERE id = $1 AND live = TRUE
                """, interaction_id)
                
                if result and result['expected_notion_id']:
                    notion_ids = result['expected_notion_id']
                    if isinstance(notion_ids, list):
                        return set(str(nid).strip() for nid in notion_ids if nid and str(nid).strip())
                    elif isinstance(notion_ids, str):
                        return set(nid.strip() for nid in notion_ids.split(',') if nid.strip())
                
                return set()
                
        except Exception as e:
            logger.error(f"Failed to get interaction expected notions: {e}")
            return set()
    
    async def _get_vocabulary_notion_sets(
        self, 
        vocabulary_matches: List[VocabularyMatch],
        cache_manager: VocabularyCacheManager
    ) -> Dict[str, Set[str]]:
        """Get expected notion IDs for each vocabulary entry"""
        vocab_notion_map = {}
        
        try:
            # Get all vocabulary from cache (already loaded)
            all_vocab = cache_manager.get_all_vocab()
            
            # Create a lookup map for efficiency
            vocab_lookup = {vocab['id']: vocab for vocab in all_vocab}
            
            for vocab_match in vocabulary_matches:
                vocab_id = vocab_match.id
                notion_ids = set()
                
                if vocab_id in vocab_lookup:
                    vocab_entry = vocab_lookup[vocab_id]
                    expected_notion_id = vocab_entry.get('expected_notion_id')
                    
                    if expected_notion_id:
                        if isinstance(expected_notion_id, list):
                            notion_ids = set(str(nid).strip() for nid in expected_notion_id if nid and str(nid).strip())
                        elif isinstance(expected_notion_id, str):
                            notion_ids = set(nid.strip() for nid in expected_notion_id.split(',') if nid.strip())
                
                vocab_notion_map[vocab_id] = notion_ids
                logger.debug(f"📝 Vocab {vocab_id} has notions: {notion_ids}")
            
            return vocab_notion_map
            
        except Exception as e:
            logger.error(f"Failed to get vocabulary notion sets: {e}")
            return {}
    
    def _find_notion_intersections(
        self, 
        interaction_expected: Set[str],
        vocabulary_notion_sets: Dict[str, Set[str]]
    ) -> List[str]:
        """Find notion IDs that appear in both interaction and vocabulary"""
        matched_notions = set()
        
        logger.info(f"🔍 Looking for intersections with interaction notions: {interaction_expected}")
        
        for vocab_id, vocab_notions in vocabulary_notion_sets.items():
            if vocab_notions:  # Only process if vocabulary has notion expectations
                intersection = interaction_expected.intersection(vocab_notions)
                if intersection:
                    logger.info(f"✅ Vocab {vocab_id} matches notions: {intersection}")
                    matched_notions.update(intersection)
                else:
                    logger.debug(f"❌ Vocab {vocab_id} notions {vocab_notions} - no intersection")
        
        return sorted(list(matched_notions))  # Return sorted list for consistency
