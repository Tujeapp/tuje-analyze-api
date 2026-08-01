# answer_selection_service.py
"""
Answer Selection Engine
Selects and filters answers for multipleButtons interactions.
Supports single and multiple selection modes.
Considers difficulty level based on rescue state and cycle_level_direction.
"""
import asyncpg
import logging
import random
from typing import List, Dict, Optional, Tuple

from button_realization import curate_quick_help, realize_template, find_frame_swap_distractors, find_entity_tokens

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION MATRICES
# ============================================================================

# Format: (required_types_list, difficulty)
# required_types_list = list of answer types needed in order
# difficulty = "easy", "medium", "hard"

SINGLE_SELECT_CONFIGS = {
    2: [
        (["good", "wrong"], "easy"),
        (["good", "false good"], "medium"),
    ],
    3: [
        (["good", "false good", "wrong"], "hard"),
        (["good", "false good", "false good"], "hard"),
        (["good", "wrong", "wrong"], "hard"),
    ],
    4: [
        (["perfect", "good", "false good", "wrong"], "easy"),
        (["perfect", "good", "good", "wrong"], "easy"),
        (["perfect", "good", "good", "false good"], "easy"),
        (["perfect", "good", "false good", "false good"], "medium"),
        (["perfect", "good", "wrong", "wrong"], "easy"),
        (["good", "false good", "false good", "wrong"], "hard"),
        (["good", "false good", "false good", "false good"], "hard"),
        (["good", "false good", "wrong", "wrong"], "hard"),
        (["good", "wrong", "wrong", "wrong"], "hard"),
    ]
}

MULTIPLE_SELECT_CONFIGS = {
    3: [
        (["good", "good", "wrong"], "easy"),
        (["good", "good", "false good"], "medium"),
    ],
    4: [
        (["good", "good", "wrong", "wrong"], "easy"),
        (["good", "good", "false good", "false good"], "hard"),
        (["good", "good", "false good", "wrong"], "medium"),
        (["good", "good", "good", "wrong"], "easy"),
        (["good", "good", "good", "false good"], "medium"),
    ]
}


# ============================================================================
# MAIN ENGINE
# ============================================================================

class AnswerSelectionService:

    async def select_answers(
        self,
        interaction_id: str,
        user_level: int,
        db_pool: asyncpg.Pool,
        rescue_triggered: bool = False,
        cycle_level_direction: int = 0,  # -1, 0, +1
        selection_mode: str = "single",
        session_interaction_id: Optional[str] = None
    ) -> Dict:
        """
        Main entry point for answer selection.

        Returns:
        {
            "answers": [...],
            "selection_mode": "single" | "multiple",
            "correct_count": int,  # how many must be selected
            "config": [...],       # the selected configuration
            "difficulty": str
        }
        """
        logger.info(f"🎯 Answer selection — interaction: {interaction_id}, "
                   f"rescue: {rescue_triggered}, direction: {cycle_level_direction}")

        # Step 1 — Determine difficulty
        difficulty = self._determine_difficulty(rescue_triggered, cycle_level_direction)
        logger.info(f"📊 Difficulty: {difficulty}")

        # Rescue quick-help: templates are is_button=FALSE so the normal path
        # (which filters is_button=TRUE) returns nothing for template-only
        # interactions. Route rescue through the generation engine instead, which
        # realizes templates into legible buttons. Maps output to the exact 5-key
        # answer shape the client already parses.
        if rescue_triggered:
            async with db_pool.acquire() as conn:
                # Level is DB-authoritative for rescue: the client-sent user_level
                # here is the frustration floor (often 0), which would exclude all
                # vocab via level_own gating. Read the real cycle level instead.
                real_level = 100  # safe default
                if session_interaction_id:
                    row = await conn.fetchrow("""
                        SELECT sc.cycle_level
                        FROM session_interaction si
                        JOIN session_cycle sc ON si.cycle_id = sc.id
                        WHERE si.id = $1
                    """, session_interaction_id)
                    if row and row["cycle_level"] is not None:
                        real_level = int(row["cycle_level"])
                buttons = await curate_quick_help(
                    conn, interaction_id, real_level, count=4
                )
            answers = [
                {
                    "id": b["id"],
                    "transcription_fr": b["transcription_fr"],
                    "transcription_en": b["transcription_en"],
                    "image_url": b["image_url"],
                    "answer_type": b["answer_type"],
                }
                for b in buttons
            ]
            correct_count = sum(
                1 for b in buttons if b["answer_type"] in ("perfect", "good")
            )
            return {
                "answers": answers,
                "selection_mode": "single",  # quick-help is always single-select (one correct to spot)
                "correct_count": correct_count,
                "config": [],
                "difficulty": "quick_help",
            }

        # Step 2 — Fetch available answers by type
        available = await self._fetch_available_answers(interaction_id, user_level, db_pool)
        logger.info(f"📊 Available answers by type: { {k: len(v) for k, v in available.items()} }")

        # Step 3 — Select configuration
        config_matrix = SINGLE_SELECT_CONFIGS if selection_mode == "single" else MULTIPLE_SELECT_CONFIGS
        selected_config, difficulty_used = self._select_configuration(
            available, config_matrix, difficulty
        )

        if not selected_config:
            logger.warning("⚠️ No valid configuration found — falling back to all available answers")
            return await self._fallback(interaction_id, db_pool)

        logger.info(f"📊 Selected config: {selected_config} ({difficulty_used})")

        # Step 4 — Pick answers for each slot
        answers = self._pick_answers(selected_config, available)

        # Shuffle so correct answer isn't always first
        random.shuffle(answers)

        # Count correct answers (perfect + good)
        correct_count = sum(
            1 for a in answers
            if a['answer_type'] in ['perfect', 'good']
        )

        return {
            "answers": answers,
            "selection_mode": selection_mode,
            "correct_count": correct_count,
            "config": selected_config,
            "difficulty": difficulty_used
        }

    # ============================================================================
    # STEP 1 — Difficulty
    # ============================================================================

    def _determine_difficulty(
        self,
        rescue_triggered: bool,
        cycle_level_direction: int
    ) -> str:
        if rescue_triggered:
            return "easy"
        if cycle_level_direction == 1:
            return "hard"
        if cycle_level_direction == -1:
            return "easy"
        return "medium"

    # ============================================================================
    # STEP 2 — Fetch available answers by type
    # ============================================================================

    async def _fetch_available_answers(
        self,
        interaction_id: str,
        user_level: int,
        db_pool: asyncpg.Pool
    ) -> Dict[str, List[Dict]]:
        """
        Fetch all display-ready answers for this interaction grouped by type.
        Ordered by closeness to user_level.
        """
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    ba.id,
                    ba.transcription_fr,
                    ba.transcription_en,
                    ba.image_url,
                    ba.answer_optimum_level,
                    ba.is_button,
                    bia.answer_type,
                    ABS(COALESCE(ba.answer_optimum_level, 100) - $2) AS level_distance
                FROM brain_interaction_answer bia
                JOIN brain_answer ba ON bia.answer_id = ba.id
                WHERE bia.interaction_id = $1
                  AND ba.live = TRUE
                  AND ba.is_button = TRUE
                  AND bia.answer_type IS NOT NULL
                ORDER BY level_distance ASC
            """, interaction_id, user_level)

        # Group by type
        available: Dict[str, List[Dict]] = {
            "perfect": [],
            "good": [],
            "false good": [],
            "wrong": []
        }

        for row in rows:
            answer_type = row['answer_type']
            if answer_type in available:
                available[answer_type].append(dict(row))

        return available

    # ============================================================================
    # STEP 3 — Select configuration
    # ============================================================================

    def _select_configuration(
        self,
        available: Dict[str, List[Dict]],
        config_matrix: Dict,
        difficulty: str
    ) -> Tuple[Optional[List[str]], str]:
        """
        Find all valid configurations matching difficulty
        that can be satisfied by available answers.
        Pick one at random.
        Falls back to easier difficulty if no match found.
        """
        difficulty_order = {
            "hard": ["hard", "medium", "easy"],
            "medium": ["medium", "easy", "hard"],
            "easy": ["easy", "medium", "hard"]
        }

        for diff in difficulty_order[difficulty]:
            valid_configs = []

            for button_count in sorted(config_matrix.keys(), reverse=True):
                for config, config_diff in config_matrix[button_count]:
                    if config_diff != diff:
                        continue
                    if self._can_satisfy(config, available):
                        valid_configs.append((config, diff))

            if valid_configs:
                chosen = random.choice(valid_configs)
                return chosen[0], chosen[1]

        return None, difficulty

    def _can_satisfy(
        self,
        config: List[str],
        available: Dict[str, List[Dict]]
    ) -> bool:
        """
        Check if available answers can satisfy a configuration.
        Counts required slots per type and checks if enough exist.
        """
        needed: Dict[str, int] = {}
        for answer_type in config:
            needed[answer_type] = needed.get(answer_type, 0) + 1

        for answer_type, count in needed.items():
            if len(available.get(answer_type, [])) < count:
                return False
        return True

    # ============================================================================
    # STEP 4 — Pick answers
    # ============================================================================

    def _pick_answers(
        self,
        config: List[str],
        available: Dict[str, List[Dict]]
    ) -> List[Dict]:
        """
        Pick one answer per slot in the config.
        Closest to user_level wins (already sorted).
        Never reuses the same answer.
        """
        used_ids = set()
        picked = []

        # Track position within each type
        type_index: Dict[str, int] = {}

        for answer_type in config:
            idx = type_index.get(answer_type, 0)
            candidates = available[answer_type]

            # Find next unused answer of this type
            while idx < len(candidates):
                candidate = candidates[idx]
                idx += 1
                if candidate['id'] not in used_ids:
                    used_ids.add(candidate['id'])
                    picked.append({
                        "id": candidate['id'],
                        "transcription_fr": candidate['transcription_fr'],
                        "transcription_en": candidate['transcription_en'],
                        "image_url": candidate['image_url'],
                        "answer_type": answer_type
                    })
                    break

            type_index[answer_type] = idx

        return picked

    # ============================================================================
    # FALLBACK
    # ============================================================================

    async def _fallback(
        self,
        interaction_id: str,
        db_pool: asyncpg.Pool
    ) -> Dict:
        """
        Last resort — return up to 4 display-ready answers
        when no valid configuration can be built.
        """
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    ba.id,
                    ba.transcription_fr,
                    ba.transcription_en,
                    ba.image_url,
                    bia.answer_type
                FROM brain_interaction_answer bia
                JOIN brain_answer ba ON bia.answer_id = ba.id
                WHERE bia.interaction_id = $1
                  AND ba.live = TRUE
                  AND ba.is_button = TRUE
                ORDER BY ba.created_at ASC
                LIMIT 4
            """, interaction_id)

        return {
            "answers": [dict(row) for row in rows],
            "selection_mode": "single",
            "correct_count": 1,
            "config": [],
            "difficulty": "fallback"
        }

    # ============================================================================
    # VOCAB REVIEW — reuses the config engine over pre-realized template buckets
    # ============================================================================

    async def _fetch_answers_for_vocab_review(
        self,
        interaction_id: str,
        user_level: int,
        db_pool: asyncpg.Pool,
        count: int = 4
    ) -> Dict[str, List[Dict]]:
        """
        Vocab-review fetch: includes TEMPLATES (drops is_button filter) and
        pre-realizes them here (while conn is open) so the sync config engine
        can consume realized rows. One template expands into up to `count`
        realized rows, each carrying the template's id + realized text + the
        template's answer_type. Literals pass through. Non-realizable templates
        (no vocab at this level) are excluded. Same bucket shape as
        _fetch_available_answers so _select_configuration/_can_satisfy work unchanged.
        """
        from button_realization import find_entity_tokens
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    ba.id,
                    ba.transcription_fr,
                    ba.transcription_en,
                    ba.image_url,
                    ba.answer_optimum_level,
                    ba.attribute_ids,
                    bia.answer_type,
                    ABS(COALESCE(ba.answer_optimum_level, 100) - $2) AS level_distance
                FROM brain_interaction_answer bia
                JOIN brain_answer ba ON bia.answer_id = ba.id
                WHERE bia.interaction_id = $1
                  AND ba.live = TRUE
                  AND bia.answer_type IS NOT NULL
                  AND COALESCE(bia.never_a_button, FALSE) = FALSE
                ORDER BY level_distance ASC
            """, interaction_id, user_level)

            available: Dict[str, List[Dict]] = {
                "perfect": [], "good": [], "false good": [], "wrong": []
            }
            # Frame sources (valid perfect/good templates) whose frames seed the
            # frame-swap distractors; used_ids excludes THIS interaction's own
            # answers so they can't be borrowed back as distractors.
            valid_template_frames: List[str] = []
            used_ids = set()
            for row in rows:
                answer_type = row['answer_type']
                if answer_type not in available:
                    continue
                used_ids.add(row['id'])
                fr = row['transcription_fr']
                is_template = bool(fr and find_entity_tokens(fr))
                # Frame source: perfect/good templates (the FRAME is what's reused,
                # regardless of whether this row itself realizes).
                if is_template and answer_type in ("perfect", "good"):
                    valid_template_frames.append(fr)
                # Wrong bucket is NOT from authored wrongs — filled by frame-swap below.
                if answer_type == "wrong":
                    continue
                if is_template:
                    # Template: realize up to `count` fills at this level.
                    realized = await realize_template(
                        conn, fr, row['attribute_ids'], user_level, max_fills=count
                    )
                    for text in realized:
                        available[answer_type].append({
                            "id": row['id'],                 # template id (Option A)
                            "transcription_fr": text,        # realized display
                            "transcription_en": row['transcription_en'],
                            "image_url": row['image_url'],
                            "answer_type": answer_type,
                        })
                    # non-realizable → contributes nothing (excluded)
                elif fr:
                    # Literal: use as-is.
                    available[answer_type].append({
                        "id": row['id'],
                        "transcription_fr": fr,
                        "transcription_en": row['transcription_en'],
                        "image_url": row['image_url'],
                        "answer_type": answer_type,
                    })
                # null fr → skipped (client requires non-null)

            # WRONG bucket = same-frame, different-vocab distractors generated from
            # this interaction's valid template frames. Deduped on text across
            # frames, capped at `count`.
            wrong_seen = set()
            for frame_fr in dict.fromkeys(valid_template_frames):
                if len(available["wrong"]) >= count:
                    break
                swaps = await find_frame_swap_distractors(
                    conn, frame_fr, user_level, count=count, exclude_answer_ids=used_ids
                )
                for d in swaps:
                    if d["transcription_fr"] in wrong_seen:
                        continue
                    wrong_seen.add(d["transcription_fr"])
                    available["wrong"].append(d)
                    if len(available["wrong"]) >= count:
                        break
        return available

    def _pick_vocab_answers(
        self,
        config: List[str],
        available: Dict[str, List[Dict]]
    ) -> List[Dict]:
        """
        Like _pick_answers but dedups on transcription_fr, not id — vocab-review
        deliberately produces multiple realized rows sharing one template id
        (j'ai un chien / un chat), and all should be pickable.
        """
        used_texts = set()
        picked = []
        type_index: Dict[str, int] = {}
        for answer_type in config:
            idx = type_index.get(answer_type, 0)
            candidates = available.get(answer_type, [])
            while idx < len(candidates):
                candidate = candidates[idx]
                idx += 1
                if candidate['transcription_fr'] not in used_texts:
                    used_texts.add(candidate['transcription_fr'])
                    picked.append({
                        "id": candidate['id'],
                        "transcription_fr": candidate['transcription_fr'],
                        "transcription_en": candidate['transcription_en'],
                        "image_url": candidate['image_url'],
                        "answer_type": answer_type,
                    })
                    break
            type_index[answer_type] = idx
        return picked

    async def curate_vocab_review(
        self,
        interaction_id: str,
        user_level: int,
        db_pool: asyncpg.Pool,
        cycle_level_direction: int = 0,
        selection_mode: str = "single",
        count: int = 4
    ) -> Dict:
        """
        Vocab-review purpose: a difficulty-scaled, level-gated set of REALIZED
        vocab answers. Reuses the config engine (answer-type composition by
        difficulty) over pre-realized template buckets. Difficulty from cycle
        direction for now (session_mood added later).
        """
        difficulty = self._determine_difficulty(False, cycle_level_direction)
        available = await self._fetch_answers_for_vocab_review(
            interaction_id, user_level, db_pool, count=count
        )
        config_matrix = (
            MULTIPLE_SELECT_CONFIGS if selection_mode == "multiple"
            else SINGLE_SELECT_CONFIGS
        )
        selected_config, difficulty_used = self._select_configuration(
            available, config_matrix, difficulty
        )
        if not selected_config:
            # No realizable config — return empty; caller decides fallback.
            return {
                "answers": [], "selection_mode": selection_mode,
                "correct_count": 0, "config": [], "difficulty": "vocab_review_empty"
            }
        answers = self._pick_vocab_answers(selected_config, available)
        random.shuffle(answers)
        correct_count = sum(1 for t in selected_config if t in ("perfect", "good"))
        return {
            "answers": answers,
            "selection_mode": selection_mode,
            "correct_count": correct_count,
            "config": selected_config,
            "difficulty": difficulty_used,
        }


# Global instance
answer_selection_service = AnswerSelectionService()
