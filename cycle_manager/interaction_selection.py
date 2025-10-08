# ============================================================================
# cycle_manager/interaction_selection.py - Interaction Selection Logic
# ============================================================================

import logging
from typing import List, Set
from models import InteractionCandidate

logger = logging.getLogger(__name__)


async def select_cycle_interactions(
    interactions: List[InteractionCandidate],
    cycle_level: int,
    cycle_boredom: float,
    cycle_goal: str
) -> List[str]:
    """
    Select ordered sequence of 7 interactions for the cycle
    
    Args:
        interactions: List of candidate interactions (already sorted by combination)
        cycle_level: Cycle level
        cycle_boredom: Cycle boredom rate
        cycle_goal: Cycle goal ("story", "notion", "intent")
    
    Returns:
        List of 7 interaction IDs in order
    """
    
    selected_ids = []
    used_ids: Set[str] = set()
    
    # INTERACTION 1: Special handling based on cycle goal
    if cycle_goal == "story":
        # Story cycles require entry point for first interaction
        first = await select_first_interaction_story(
            interactions=interactions,
            cycle_level=cycle_level,
            cycle_boredom=cycle_boredom
        )
    else:
        # Notion/Intent cycles: just pick first from sorted list
        first = interactions[0]
    
    selected_ids.append(first.id)
    used_ids.add(first.id)
    last_interaction = first
    
    # INTERACTIONS 2-7: Sequential selection
    for position in range(2, 8):
        next_interaction = await select_next_interaction(
            interactions=interactions,
            used_ids=used_ids,
            last_interaction=last_interaction
        )
        
        selected_ids.append(next_interaction.id)
        used_ids.add(next_interaction.id)
        last_interaction = next_interaction
        
        logger.debug(f"Selected interaction {position}: combination={next_interaction.combination}")
    
    return selected_ids


async def select_first_interaction_story(
    interactions: List[InteractionCandidate],
    cycle_level: int,
    cycle_boredom: float
) -> InteractionCandidate:
    """
    Select first interaction for story cycle (must be entry point)
    
    Falls back to any interaction if no entry points available
    """
    
    # Filter to only entry points
    entry_points = [i for i in interactions if i.is_entry_point]
    
    if not entry_points:
        logger.error(f"""
        ❌ CONTENT ISSUE: No entry point interactions found!
        - Subtopic: {interactions[0].subtopic_id if interactions else 'N/A'}
        - Total interactions: {len(interactions)}
        - Action: Add entry point interactions for this subtopic
        """)
        # Graceful fallback for user
        entry_points = interactions
    
    # Find best match based on level and boredom
    best = None
    best_score = float('inf')
    
    for interaction in entry_points:
        # Level constraint: prefer cycle_level or lower by 50
        if interaction.level_from > cycle_level:
            continue
        if interaction.level_from < cycle_level - 50:
            continue
        
        # Calculate "distance" from ideal boredom
        boredom_distance = abs(interaction.boredom_rate - cycle_boredom)
        
        if boredom_distance < best_score:
            best_score = boredom_distance
            best = interaction
    
    if not best:
        # Fallback: relax level constraint
        best = entry_points[0]
        logger.warning(f"Level constraint relaxed for first interaction")
    
    logger.info(f"First interaction selected: entry_point={best.is_entry_point}, combination={best.combination}")
    return best


async def select_next_interaction(
    interactions: List[InteractionCandidate],
    used_ids: Set[str],
    last_interaction: InteractionCandidate
) -> InteractionCandidate:
    """
    Select next interaction in sequence
    
    Rules:
    - Exclude already used interactions
    - Prefer same or closest combination to last interaction
    - All from same subtopic (already guaranteed by search)
    """
    
    # Filter out used interactions
    available = [i for i in interactions if i.id not in used_ids]
    
    if not available:
        raise ValueError("No more available interactions in list")
    
    # Find interaction with same or closest combination
    target_combination = last_interaction.combination
    
    # Try exact match first
    same_combination = [i for i in available if i.combination == target_combination]
    if same_combination:
        return same_combination[0]  # Already sorted by boredom
    
    # Otherwise, find closest combination
    available.sort(key=lambda x: abs(x.combination - target_combination))
    return available[0]
