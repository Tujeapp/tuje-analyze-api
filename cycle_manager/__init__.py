# ============================================================================
# cycle_manager/__init__.py - Cycle Manager Module
# ============================================================================

from .cycle_creation import (
    start_new_cycle,
    advance_to_next_interaction
)

from .cycle_completion import (
    complete_cycle,
    update_cycle_level_direction,
    get_cycle_summary
)

from .interaction_selection import (
    select_cycle_interactions,
    select_first_interaction_story,
    select_next_interaction
)

from .cycle_calculations import (
    calculate_cycle_level,
    calculate_cycle_boredom,
    calculate_cycle_goal,
    calculate_interaction_user_level
)

__all__ = [
    'start_new_cycle',
    'advance_to_next_interaction',
    'complete_cycle',
    'update_cycle_level_direction',
    'get_cycle_summary',
    'select_cycle_interactions',
    'select_first_interaction_story',
    'select_next_interaction',
    'calculate_cycle_level',
    'calculate_cycle_boredom',
    'calculate_cycle_goal',
    'calculate_interaction_user_level',
]
