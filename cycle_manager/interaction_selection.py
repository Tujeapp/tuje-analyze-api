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
    elif cycle_goal == "notion":
        first = await select_first_interaction_notion(
            interactions=interactions,
            cycle_level=cycle_level,
            cycle_boredom=cycle_boredom
        )
    elif cycle_goal == "intent":
        first = await select_first_interaction_intent(
            interactions=interactions,
            cycle_level=cycle_level,
            cycle_boredom=cycle_boredom,
        )
    else:
        first = interactions[0]
    
    selected_ids.append(first.id)
    used_ids.add(first.id)
    used_subtopics: Set[str] = {first.subtopic_id}
    subtopic_counts: dict = {first.subtopic_id: 1}
    last_interaction = first

    # INTERACTIONS 2-7: Sequential selection
    for position in range(2, 8):
        if cycle_goal == "notion":
            next_interaction = await select_next_interaction_notion(
                interactions=interactions,
                used_ids=used_ids,
                used_subtopics=used_subtopics,
                last_interaction=last_interaction,
            )
        elif cycle_goal == "intent":
            next_interaction = await select_next_interaction_intent(
                interactions=interactions,
                used_ids=used_ids,
                subtopic_counts=subtopic_counts,
                last_interaction=last_interaction,
            )
        else:
            next_interaction = await select_next_interaction(
                interactions=interactions,
                used_ids=used_ids,
                last_interaction=last_interaction
            )

        selected_ids.append(next_interaction.id)
        used_ids.add(next_interaction.id)
        used_subtopics.add(next_interaction.subtopic_id)
        subtopic_counts[next_interaction.subtopic_id] = subtopic_counts.get(next_interaction.subtopic_id, 0) + 1
        last_interaction = next_interaction

        logger.debug(f"Selected interaction {position}: combination={next_interaction.combination}")
        
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


async def select_first_interaction_notion(
    interactions: List[InteractionCandidate],
    cycle_level: int,
    cycle_boredom: float,
) -> InteractionCandidate:
    """
    Select first interaction for a NOTION cycle (Part 4).
    - level_from within [cycle_level - 50, cycle_level] (cycle level or up to 50 below)
    - boredom closest to cycle_boredom
    - NO entry-point requirement (unlike story)
    Falls back to relaxing the level window if nothing matches.
    """
    in_window = [
        i for i in interactions
        if (cycle_level - 50) <= i.level_from <= cycle_level
    ]
    pool = in_window if in_window else interactions
    if not in_window:
        logger.warning("Notion first-interaction: no candidate in level window "
                       f"[{cycle_level - 50}, {cycle_level}]; relaxing level constraint.")

    # boredom closest to cycle_boredom
    best = min(pool, key=lambda i: abs(i.boredom_rate - cycle_boredom))
    logger.info(f"Notion first interaction: {best.id} "
                f"(level={best.level_from}, boredom={best.boredom_rate:.2f}, "
                f"combination={best.combination})")
    return best


async def select_first_interaction_intent(
    interactions: List[InteractionCandidate],
    cycle_level: int,
    cycle_boredom: float,
) -> InteractionCandidate:
    """
    Select first interaction for an INTENT cycle (Part 4).
    Same as notion's first: boredom-closest within [cycle_level - 50, cycle_level],
    no entry-point requirement. Separate function for intent independence.
    """
    in_window = [
        i for i in interactions
        if (cycle_level - 50) <= i.level_from <= cycle_level
    ]
    pool = in_window if in_window else interactions
    if not in_window:
        logger.warning("Intent first-interaction: no candidate in level window "
                       f"[{cycle_level - 50}, {cycle_level}]; relaxing level constraint.")
    best = min(pool, key=lambda i: abs(i.boredom_rate - cycle_boredom))
    logger.info(f"Intent first interaction: {best.id} "
                f"(level={best.level_from}, boredom={best.boredom_rate:.2f}, "
                f"combination={best.combination})")
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


async def select_next_interaction_notion(
    interactions: List[InteractionCandidate],
    used_ids: Set[str],
    used_subtopics: Set[str],
    last_interaction: InteractionCandidate,
) -> InteractionCandidate:
    """
    Select next interaction for a NOTION cycle (Part 5).
    - exclude used interactions
    - prefer interactions from a NOT-yet-used subtopic; if none, allow subtopic reuse
      (fallback, so the cycle can reach 7)
    - pick combination equal-or-closest to the last interaction's combination
    """
    available = [i for i in interactions if i.id not in used_ids]
    if not available:
        raise ValueError("No more available interactions in list")

    # Prefer interactions whose subtopic hasn't been used yet.
    fresh_subtopic = [i for i in available if i.subtopic_id not in used_subtopics]
    pool = fresh_subtopic if fresh_subtopic else available
    if not fresh_subtopic:
        logger.warning("Notion next-interaction: all remaining interactions are in "
                       "already-used subtopics; allowing subtopic reuse to fill the cycle.")

    target = last_interaction.combination

    # Exact combination match first (pool is pre-sorted by (combination, boredom)).
    same = [i for i in pool if i.combination == target]
    if same:
        return same[0]

    # Otherwise closest combination.
    pool.sort(key=lambda x: abs(x.combination - target))
    return pool[0]


async def select_next_interaction_intent(
    interactions: List[InteractionCandidate],
    used_ids: Set[str],
    subtopic_counts: dict,
    last_interaction: InteractionCandidate,
) -> InteractionCandidate:
    """
    Select next interaction for an INTENT cycle (Part 5).
    - exclude used interactions
    - MAX TWICE per subtopic: exclude any subtopic already used twice
    - PREFER continuing the last interaction's subtopic if it has been used only once
      (intent works around the same vocabulary)
    - pick combination equal-or-closest to the last interaction's combination
    - FALLBACK: if every subtopic is already at twice (eligible empty), allow exceeding
      the cap so the cycle can still reach 7
    """
    available = [i for i in interactions if i.id not in used_ids]
    if not available:
        raise ValueError("No more available interactions in list")

    # Eligible = interactions whose subtopic is below the twice cap.
    eligible = [i for i in available if subtopic_counts.get(i.subtopic_id, 0) < 2]
    if not eligible:
        logger.warning("Intent next-interaction: all subtopics already used twice; "
                       "allowing the cap to be exceeded to fill the cycle.")
        eligible = available

    last_sub = last_interaction.subtopic_id
    target = last_interaction.combination

    # If the last subtopic has been used only once, prefer continuing it (to reach twice).
    if subtopic_counts.get(last_sub, 0) == 1:
        same = [i for i in eligible if i.subtopic_id == last_sub]
        if same:
            same_exact = [i for i in same if i.combination == target]
            if same_exact:
                return same_exact[0]
            same.sort(key=lambda x: abs(x.combination - target))
            return same[0]

    # Otherwise (or no same-subtopic available): combination equal-or-closest among eligible.
    exact = [i for i in eligible if i.combination == target]
    if exact:
        return exact[0]
    eligible.sort(key=lambda x: abs(x.combination - target))
    return eligible[0]
