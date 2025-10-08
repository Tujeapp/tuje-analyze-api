# ============================================================================
# helpers.py - Utility Functions
# ============================================================================

import uuid
import asyncpg
import logging
from datetime import datetime
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


# ============================================================================
# ID GENERATION
# ============================================================================

def generate_id(prefix: str) -> str:
    """
    Generate unique ID with prefix and timestamp
    
    Args:
        prefix: Prefix for ID (e.g., "SESSION", "CYCLE", "INT")
    
    Returns:
        Unique ID in format: PREFIX20250108153045ABCD
    
    Examples:
        SESSION20250108153045A7F2
        CYCLE20250108153045B3E1
        INT20250108153045C9D4
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = str(uuid.uuid4())[:4].upper()
    return f"{prefix}{timestamp}{random_suffix}"


# ============================================================================
# SESSION TYPE MAPPING
# ============================================================================

def get_cycle_count(session_type: str) -> int:
    """
    Map session type to number of cycles
    
    Args:
        session_type: "short", "medium", or "long"
    
    Returns:
        Number of cycles (3, 5, or 7)
    """
    mapping = {
        "short": 3,    # 10-15 minutes
        "medium": 5,   # 20-25 minutes
        "long": 7      # 35-40 minutes
    }
    return mapping.get(session_type.lower(), 3)


def get_expected_total_score(session_type: str) -> int:
    """
    Calculate expected total score for session type
    
    Args:
        session_type: "short", "medium", or "long"
    
    Returns:
        Expected total score (cycles × 7 interactions × 100 max score)
    
    Examples:
        short: 3 × 7 × 100 = 2100
        medium: 5 × 7 × 100 = 3500
        long: 7 × 7 × 100 = 4900
    """
    cycles = get_cycle_count(session_type)
    return cycles * 7 * 100


# ============================================================================
# MOOD TO INTERACTION TYPE MAPPING
# ============================================================================

def get_mood_types(session_mood: str) -> List[str]:
    """
    Map session mood to compatible interaction types
    
    Args:
        session_mood: "effective", "playful", "cultural", "relax", "listening"
    
    Returns:
        List of compatible interaction type names
    """
    mood_type_mapping = {
        "effective": [
            "conversation",
            "quiz",
            "describe",
            "repeat",
            "ask-questions"
        ],
        "playful": [
            "first-person",
            "seek-and-find",
            "pet-a-pet",
            "guess-what",
            "make-a-wish"
        ],
        "cultural": [
            "conversation",
            "listen-and-touch",
            "third-person",
            "long-talk"
        ],
        "relax": [
            "listen-and-touch",
            "on-the-phone",
            "describe",
            "pet-a-pet"
        ],
        "listening": [
            "listen-and-touch",
            "third-person",
            "guess-what",
            "find-the-suspect"
        ]
    }
    
    types = mood_type_mapping.get(session_mood.lower(), ["conversation"])
    logger.debug(f"Mood '{session_mood}' mapped to types: {types}")
    return types


# ============================================================================
# LEVEL CONVERSION
# ============================================================================

def level_number_to_cefr(level: int) -> str:
    """
    Convert numeric level to CEFR level string
    
    Args:
        level: Numeric level (0-500)
    
    Returns:
        CEFR level string (e.g., "A1.0", "B2.1")
    """
    level_mapping = {
        0: "A0.0",
        50: "A0.1",
        100: "A1.0",
        150: "A1.1",
        200: "A2.0",
        250: "A2.1",
        300: "B1.0",
        350: "B1.1",
        400: "B2.0",
        450: "B2.1",
        500: "C1.0"
    }
    return level_mapping.get(level, f"Level {level}")


def cefr_to_level_number(cefr: str) -> int:
    """
    Convert CEFR level string to numeric level
    
    Args:
        cefr: CEFR level string (e.g., "A1.0", "B2.1")
    
    Returns:
        Numeric level (0-500)
    """
    cefr_mapping = {
        "A0.0": 0,
        "A0.1": 50,
        "A1.0": 100,
        "A1.1": 150,
        "A2.0": 200,
        "A2.1": 250,
        "B1.0": 300,
        "B1.1": 350,
        "B2.0": 400,
        "B2.1": 450,
        "C1.0": 500
    }
    return cefr_mapping.get(cefr.upper(), 0)

# ============================================================================
# BOREDOM CALCULATION
# ============================================================================

async def calculate_adaptive_boredom(
    user_id: str,
    history_days: int,
    db_pool: asyncpg.Pool
) -> float:
    """
    Calculate boredom based on available history window
    
    Args:
        user_id: User ID
        history_days: Number of days of history to consider
        db_pool: Database connection pool
    
    Returns:
        Boredom rate (0.0 - 1.0)
        
    Logic:
        - No history = 0.0 boredom
        - High scores = low boredom
        - Low scores = high boredom
    """
    if history_days == 0:
        return 0.0  # No boredom for new users
    
    async with db_pool.acquire() as conn:
        avg_score = await conn.fetchval(f"""
            SELECT AVG(session_score)
            FROM session
            WHERE user_id = $1
            AND status = 'completed'
            AND completed_at > NOW() - INTERVAL '{history_days} days'
        """, user_id)
        
        if avg_score is None:
            return 0.0
        
        # Inverse relationship: low scores → high boredom
        # Score 0-100 → Boredom 1.0-0.0
        boredom = 1.0 - (avg_score / 100.0)
        result = round(max(0.0, min(1.0, boredom)), 2)
        
        logger.debug(f"Calculated boredom: {result:.2f} (from avg_score: {avg_score:.2f}, {history_days}d)")
        return result


# ============================================================================
# VALIDATION HELPERS
# ============================================================================

def validate_session_type(session_type: str) -> bool:
    """Validate session type"""
    valid = session_type.lower() in ["short", "medium", "long"]
    if not valid:
        logger.warning(f"Invalid session type: {session_type}")
    return valid


def validate_session_mood(session_mood: str) -> bool:
    """Validate session mood"""
    valid = session_mood.lower() in ["effective", "playful", "cultural", "relax", "listening"]
    if not valid:
        logger.warning(f"Invalid session mood: {session_mood}")
    return valid


def validate_cycle_goal(cycle_goal: str) -> bool:
    """Validate cycle goal"""
    valid = cycle_goal.lower() in ["story", "notion", "intent"]
    if not valid:
        logger.warning(f"Invalid cycle goal: {cycle_goal}")
    return valid


def validate_level(level: int) -> bool:
    """Validate user/session/cycle level"""
    valid = 0 <= level <= 500 and level % 50 == 0
    if not valid:
        logger.warning(f"Invalid level: {level} (must be 0-500 in increments of 50)")
    return valid


def validate_boredom(boredom: float) -> bool:
    """Validate boredom rate"""
    valid = 0.0 <= boredom <= 1.0
    if not valid:
        logger.warning(f"Invalid boredom: {boredom} (must be 0.0-1.0)")
    return valid


def validate_score(score: int, max_score: int = 100) -> bool:
    """Validate score value"""
    valid = 0 <= score <= max_score
    if not valid:
        logger.warning(f"Invalid score: {score} (must be 0-{max_score})")
    return valid


# ============================================================================
# SCORE CALCULATIONS
# ============================================================================

def calculate_session_score(cycle_scores: List[int]) -> int:
    """
    Calculate total session score from cycle scores
    
    Args:
        cycle_scores: List of cycle scores (each 0-700)
    
    Returns:
        Total session score
    """
    total = sum(cycle_scores)
    logger.debug(f"Session score: {total} (from {len(cycle_scores)} cycles)")
    return total


def calculate_average_score(total_score: int, num_interactions: int) -> float:
    """
    Calculate average score per interaction
    
    Args:
        total_score: Total accumulated score
        num_interactions: Number of completed interactions
    
    Returns:
        Average score (0-100)
    """
    if num_interactions == 0:
        return 0.0
    avg = round(total_score / num_interactions, 2)
    logger.debug(f"Average score: {avg} (total: {total_score}, count: {num_interactions})")
    return avg


def calculate_session_rate(session_score: int, expected_score: int) -> float:
    """
    Calculate session completion rate
    
    Args:
        session_score: Actual session score
        expected_score: Expected total score based on session type
    
    Returns:
        Session rate (0.0 - 1.0)
    """
    if expected_score == 0:
        return 0.0
    rate = round(session_score / expected_score, 2)
    logger.debug(f"Session rate: {rate:.2f} (score: {session_score}/{expected_score})")
    return rate


def calculate_cycle_rate(cycle_score: int) -> float:
    """
    Calculate cycle rate
    
    Args:
        cycle_score: Cycle score (0-700)
    
    Returns:
        Cycle rate (0.0 - 1.0)
    """
    rate = round(cycle_score / 700.0, 2)
    logger.debug(f"Cycle rate: {rate:.2f} (score: {cycle_score}/700)")
    return rate


# ============================================================================
# TIME HELPERS
# ============================================================================

def format_duration(seconds: int) -> str:
    """
    Format duration in human-readable format
    
    Args:
        seconds: Duration in seconds
    
    Returns:
        Formatted string (e.g., "5m 30s", "1h 15m 30s")
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def calculate_expected_duration(session_type: str) -> Dict[str, int]:
    """
    Get expected duration range for session type
    
    Args:
        session_type: "short", "medium", or "long"
    
    Returns:
        Dict with min_seconds and max_seconds
    """
    duration_mapping = {
        "short": {"min_seconds": 600, "max_seconds": 900},      # 10-15 min
        "medium": {"min_seconds": 1200, "max_seconds": 1500},   # 20-25 min
        "long": {"min_seconds": 2100, "max_seconds": 3000}      # 35-50 min
    }
    return duration_mapping.get(session_type.lower(), {"min_seconds": 600, "max_seconds": 900})


def seconds_to_minutes(seconds: int) -> float:
    """Convert seconds to minutes (rounded to 1 decimal)"""
    return round(seconds / 60.0, 1)


def minutes_to_seconds(minutes: float) -> int:
    """Convert minutes to seconds"""
    return int(minutes * 60)

# ============================================================================
# LOGGING HELPERS
# ============================================================================

def log_session_summary(session_data: Dict[str, Any]):
    """
    Log formatted session summary
    
    Args:
        session_data: Session data dictionary
    """
    logger.info(f"""
    ═══════════════════════════════════════════════════════════
    SESSION SUMMARY
    ═══════════════════════════════════════════════════════════
    Session ID: {session_data.get('session_id', 'N/A')}
    User ID: {session_data.get('user_id', 'N/A')}
    Type: {session_data.get('session_type', 'N/A')}
    Mood: {session_data.get('session_mood', 'N/A')}
    Level: {session_data.get('session_level', 0)} ({level_number_to_cefr(session_data.get('session_level', 0))})
    Streak7: {session_data.get('streak7', 0):.2f}
    Streak30: {session_data.get('streak30', 0):.2f}
    Boredom: {session_data.get('session_boredom', 0):.2f}
    User State: {session_data.get('user_state', 'N/A')}
    ═══════════════════════════════════════════════════════════
    """)


def log_cycle_summary(cycle_data: Dict[str, Any]):
    """
    Log formatted cycle summary
    
    Args:
        cycle_data: Cycle data dictionary
    """
    logger.info(f"""
    ───────────────────────────────────────────────────────────
    CYCLE SUMMARY
    ───────────────────────────────────────────────────────────
    Cycle ID: {cycle_data.get('cycle_id', 'N/A')}
    Number: {cycle_data.get('cycle_number', 'N/A')}
    Goal: {cycle_data.get('cycle_goal', 'N/A')}
    Subtopic: {cycle_data.get('subtopic_id', 'N/A')}
    Level: {cycle_data.get('cycle_level', 0)}
    Boredom: {cycle_data.get('cycle_boredom', 0):.2f}
    Score: {cycle_data.get('cycle_score', 0)}/700
    Rate: {cycle_data.get('cycle_rate', 0):.2f}
    Duration: {format_duration(cycle_data.get('total_duration_seconds', 0))}
    ───────────────────────────────────────────────────────────
    """)


def log_interaction_summary(interaction_data: Dict[str, Any]):
    """
    Log formatted interaction summary
    
    Args:
        interaction_data: Interaction data dictionary
    """
    logger.info(f"""
    • Interaction {interaction_data.get('interaction_number', 'N/A')}:
      Score: {interaction_data.get('interaction_score', 0)}/100
      Attempts: {interaction_data.get('attempts_count', 0)}
      Duration: {format_duration(interaction_data.get('duration_seconds', 0))}
    """)


def log_fallback_attempt(attempt: int, strategy: str, details: str):
    """
    Log fallback attempt during interaction search
    
    Args:
        attempt: Attempt number
        strategy: Strategy being used (e.g., "new_only", "boredom_reduction")
        details: Additional details about the attempt
    """
    logger.warning(f"""
    ⚠️  Fallback Attempt #{attempt}
    Strategy: {strategy}
    Details: {details}
    """)


def log_error_with_context(error: Exception, context: Dict[str, Any]):
    """
    Log error with contextual information
    
    Args:
        error: Exception that occurred
        context: Contextual data (user_id, session_id, etc.)
    """
    logger.error(f"""
    ❌ ERROR OCCURRED
    ═══════════════════════════════════════════════════════════
    Error Type: {type(error).__name__}
    Error Message: {str(error)}
    Context:
    {format_dict_for_logging(context)}
    ═══════════════════════════════════════════════════════════
    """)


# ============================================================================
# DATA FORMATTING HELPERS
# ============================================================================

def format_dict_for_logging(data: Dict[str, Any], indent: int = 2) -> str:
    """
    Format dictionary for readable logging
    
    Args:
        data: Dictionary to format
        indent: Number of spaces for indentation
    
    Returns:
        Formatted string
    """
    lines = []
    prefix = " " * indent
    
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(format_dict_for_logging(value, indent + 2))
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}: [{len(value)} items]")
        else:
            lines.append(f"{prefix}{key}: {value}")
    
    return "\n".join(lines)


def format_user_message(user_state: str, user_data: Dict[str, Any]) -> str:
    """
    Format welcome message for user based on their state
    
    Args:
        user_state: User state ("brand_new", "early_user", "active_user", "returning_user")
        user_data: User data dictionary
    
    Returns:
        Formatted welcome message
    """
    messages = {
        "brand_new": "Welcome to TuJe! Let's start your French journey! 🇫🇷",
        "early_user": f"Great to see you again! Day {user_data.get('history_days', 0)} - Keep it up! 💪",
        "active_user": "Welcome back! Ready for your session? 🎯",
        "returning_user": f"Welcome back! We've adjusted to level {user_data.get('user_level', 0)}. Let's refresh! 🎉"
    }
    
    return messages.get(user_state, "Welcome to TuJe! 🇫🇷")


def format_session_complete_message(session_data: Dict[str, Any]) -> str:
    """
    Format completion message for user
    
    Args:
        session_data: Session data dictionary
    
    Returns:
        Formatted completion message
    """
    score = session_data.get('session_score', 0)
    level = session_data.get('session_level', 0)
    level_cefr = level_number_to_cefr(level)
    cycles_completed = session_data.get('completed_cycles', 0)
    
    if score >= 80:
        performance = "Excellent work"
        emoji = "🌟"
    elif score >= 60:
        performance = "Great job"
        emoji = "👏"
    elif score >= 40:
        performance = "Good effort"
        emoji = "👍"
    else:
        performance = "Keep practicing"
        emoji = "💪"
    
    return f"""
{emoji} {performance}!

Session Complete:
- Score: {score}/100
- Level: {level_cefr}
- Cycles: {cycles_completed}

Keep up the great work! 🇫🇷
    """.strip()


# ============================================================================
# DATA TRANSFORMATION HELPERS
# ============================================================================

def sanitize_user_input(text: str) -> str:
    """
    Sanitize user input text
    
    Args:
        text: User input text
    
    Returns:
        Sanitized text
    """
    if not text:
        return ""
    
    # Remove excessive whitespace
    text = " ".join(text.split())
    
    # Trim to reasonable length
    max_length = 500
    if len(text) > max_length:
        text = text[:max_length]
        logger.warning(f"User input truncated to {max_length} characters")
    
    return text.strip()


def round_to_nearest_50(value: int) -> int:
    """
    Round value to nearest 50
    
    Args:
        value: Integer value
    
    Returns:
        Value rounded to nearest 50
    """
    return round(value / 50) * 50


def clamp_value(value: float, min_val: float, max_val: float) -> float:
    """
    Clamp value between min and max
    
    Args:
        value: Value to clamp
        min_val: Minimum value
        max_val: Maximum value
    
    Returns:
        Clamped value
    """
    return max(min_val, min(max_val, value))


# ============================================================================
# PROGRESS CALCULATION HELPERS
# ============================================================================

def calculate_progress_percentage(current: int, total: int) -> float:
    """
    Calculate progress percentage
    
    Args:
        current: Current value
        total: Total value
    
    Returns:
        Percentage (0.0 - 100.0)
    """
    if total == 0:
        return 0.0
    return round((current / total) * 100, 1)


def calculate_completion_estimate(
    completed_interactions: int,
    avg_duration_seconds: int
) -> Dict[str, Any]:
    """
    Estimate remaining time for session
    
    Args:
        completed_interactions: Number of completed interactions
        avg_duration_seconds: Average duration per interaction
    
    Returns:
        Dict with estimated_remaining_seconds and estimated_total_seconds
    """
    # Assuming 7 interactions per cycle
    remaining_interactions = 7 - (completed_interactions % 7)
    estimated_remaining = remaining_interactions * avg_duration_seconds
    
    return {
        "estimated_remaining_seconds": estimated_remaining,
        "estimated_remaining_formatted": format_duration(estimated_remaining),
        "avg_duration_per_interaction": avg_duration_seconds
    }


# ============================================================================
# STATISTICS HELPERS
# ============================================================================

def calculate_performance_trend(scores: List[int]) -> str:
    """
    Calculate performance trend from score history
    
    Args:
        scores: List of scores (most recent last)
    
    Returns:
        Trend: "improving", "stable", or "declining"
    """
    if len(scores) < 3:
        return "stable"
    
    # Compare last 3 scores
    recent = scores[-3:]
    
    # Calculate simple trend
    if recent[-1] > recent[0] + 10:
        return "improving"
    elif recent[-1] < recent[0] - 10:
        return "declining"
    else:
        return "stable"


def calculate_consistency_score(values: List[float]) -> float:
    """
    Calculate consistency score (lower variance = higher consistency)
    
    Args:
        values: List of values
    
    Returns:
        Consistency score (0.0 - 1.0)
    """
    if len(values) < 2:
        return 1.0
    
    # Calculate variance
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    
    # Convert to consistency score (inverse of normalized variance)
    # Lower variance = higher consistency
    max_variance = 100  # Assume max variance of 100
    consistency = 1.0 - min(variance / max_variance, 1.0)
    
    return round(consistency, 2)
