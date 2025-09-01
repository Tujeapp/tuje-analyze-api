# adjustement_intent_matcher.py
"""
SINGLE RESPONSIBILITY: Match vocabulary intents with interaction expected intents
"""
import logging
from typing import List, Set, Dict, Any
from adjustement_cache_manager import VocabularyCacheManager
from adjustement_types import VocabularyMatch

logger = logging.getLogger(__name__)

class IntentMatcher:
    """Handles intent matching between vocabulary and interaction expectations"""
    
    def __init__(self):
        pass
    
    async def find_intent_matches(
        self, 
        interaction_id: str,
        vocabulary_matches: List[VocabularyMatch],
        cache_manager: VocabularyCacheManager
    ) -> List[str]:
        """
        Find intent matches between vocabulary found and interaction expectations
        Returns: List of intent IDs that match
        """
        logger.info(f"🎯 Starting intent matching for interaction {interaction_id}")
        logger.info(f"📚 Analyzing {len(vocabulary_matches)} vocabulary entries")
        
        try:
            # Step 1: Get interaction expected intents
            interaction_expected_intents = await self._get_interaction_expected_intents(
                interaction_id, cache_manager
            )
            
            if not interaction_expected_intents:
                logger.info("⚠️ No expected intents found for interaction")
                return []
            
            logger.info(f"🎯 Interaction expects intents: {interaction_expected_intents}")
            
            # Step 2: Get vocabulary expected intents for all found vocabulary
            vocabulary_intent_sets = self._get_vocabulary_intent_sets(
                vocabulary_matches, cache_manager
            )
            
            # Step 3: Find intersections
            matched_intent_ids = self._find_intent_intersections(
                interaction_expected_intents, vocabulary_intent_sets
            )
            
            logger.info(f"✅ Found {len(matched_intent_ids)} intent matches: {matched_intent_ids}")
            return matched_intent_ids
            
        except Exception as e:
            logger.error(f"❌ Intent matching failed: {e}")
            return []  # Return empty list on error to not break the adjustment process
    
    async def _get_interaction_expected_intents(
        self, 
        interaction_id: str, 
        cache_manager: VocabularyCacheManager
    ) -> Set[str]:
        """Get expected intent IDs for the interaction"""
        try:
            # Use the cache manager's safe query method
            result = await cache_manager.execute_query_for_notion_matcher("""
                SELECT intents
                FROM brain_interaction
                WHERE id = $1 AND live = TRUE
            """, interaction_id)
            
            if result and result['intents']:
                intent_ids = result['intents']
                if isinstance(intent_ids, list):
                    return set(str(iid).strip() for iid in intent_ids if iid and str(iid).strip())
                elif isinstance(intent_ids, str):
                    return set(iid.strip() for iid in intent_ids.split(',') if iid.strip())
            
            return set()
                
        except Exception as e:
            logger.error(f"Failed to get interaction expected intents: {e}")
            return set()
    
    def _get_vocabulary_intent_sets(
        self, 
        vocabulary_matches: List[VocabularyMatch],
        cache_manager: VocabularyCacheManager
    ) -> Dict[str, Set[str]]:
        """Get expected intent IDs for each vocabulary entry"""
        vocab_intent_map = {}
        
        try:
            # Get all vocabulary from cache (now includes expected_intent_id)
            all_vocab = cache_manager.get_all_vocab()
            
            # Create a lookup map for efficiency
            vocab_lookup = {vocab['id']: vocab for vocab in all_vocab}
            
            for vocab_match in vocabulary_matches:
                vocab_id = vocab_match.id
                intent_ids = set()
                
                if vocab_id in vocab_lookup:
                    vocab_entry = vocab_lookup[vocab_id]
                    expected_intent_id = vocab_entry.get('expected_intent_id')
                    
                    if expected_intent_id:
                        if isinstance(expected_intent_id, list):
                            intent_ids = set(str(iid).strip() for iid in expected_intent_id if iid and str(iid).strip())
                        elif isinstance(expected_intent_id, str):
                            intent_ids = set(iid.strip() for iid in expected_intent_id.split(',') if iid.strip())
                
                vocab_intent_map[vocab_id] = intent_ids
                logger.debug(f"📝 Vocab {vocab_id} has intents: {intent_ids}")
            
            return vocab_intent_map
            
        except Exception as e:
            logger.error(f"Failed to get vocabulary intent sets: {e}")
            return {}
    
    def _find_intent_intersections(
        self, 
        interaction_expected: Set[str],
        vocabulary_intent_sets: Dict[str, Set[str]]
    ) -> List[str]:
        """Find intent IDs that appear in both interaction and vocabulary"""
        matched_intents = set()
        
        logger.info(f"🔍 Looking for intersections with interaction intents: {interaction_expected}")
        
        for vocab_id, vocab_intents in vocabulary_intent_sets.items():
            if vocab_intents:  # Only process if vocabulary has intent expectations
                intersection = interaction_expected.intersection(vocab_intents)
                if intersection:
                    logger.info(f"✅ Vocab {vocab_id} matches intents: {intersection}")
                    matched_intents.update(intersection)
                else:
                    logger.debug(f"❌ Vocab {vocab_id} intents {vocab_intents} - no intersection")
        
        return sorted(list(matched_intents))  # Return sorted list for consistency
