#!/usr/bin/env python3
# ============================================================================
# test_notion_steps_db.py - Read-only DB probe for the notion-step engine
# ============================================================================
# Needs DATABASE_URL (env, or .env fallback — same as test_realization.py).
# Runs everything on ONE connection inside a READ-ONLY transaction that is
# rolled back, and calls build_notion_cycle(dry_run=True): writes NOTHING.
#
# RUN: cd ~/Desktop/tuje-analyze-api ; source venv/bin/activate ;
#      python test_notion_steps_db.py <user_id> [cycle_level=0]
# ============================================================================

import asyncio
import json
import logging
import os
import sys

import asyncpg

from notion_steps.engine import build_notion_cycle
from notion_steps.repository import (
    load_candidates,
    load_evidence,
    load_seen,
    load_steps,
    pick_notion_ids,
)

DRY_RUN = True


def _db_url() -> str:
    """Same source the app uses (os.getenv DATABASE_URL); fall back to .env for
    local runs where the var isn't exported into the shell."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    for line in open(".env"):
        line = line.strip()
        if line.startswith("DATABASE_URL"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("DATABASE_URL not found in env or .env")


def show(label, value):
    print(f"\n--- {label} ---")
    print(json.dumps(value, indent=2, default=str))


async def main():
    if len(sys.argv) < 2:
        print("usage: python test_notion_steps_db.py <user_id> [cycle_level=0]")
        sys.exit(1)
    user_id = sys.argv[1]
    cycle_level = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    assert DRY_RUN, "this probe must never write"

    conn = await asyncpg.connect(_db_url())
    tr = conn.transaction(readonly=True)
    await tr.start()
    try:
        print("=" * 60); print(f"NOTION STEPS PROBE — user={user_id} level={cycle_level}"); print("=" * 60)

        notion_ids = await pick_notion_ids(conn, user_id, cycle_level)
        show("pick_notion_ids", notion_ids)

        if notion_ids:
            nid = notion_ids[0]
            steps, warnings = await load_steps(conn, nid)
            show(f"steps for {nid}", [{"id": s.id, "purpose": s.purpose, "rank": s.rank} for s in steps])
            show("load_steps warnings", warnings)
            candidates = await load_candidates(conn, steps, cycle_level)
            show(f"candidates ({len(candidates)})", candidates)
            show("evidence", await load_evidence(conn, user_id, nid))
            show("seen", sorted(await load_seen(conn, user_id, candidates.keys())))

        result = await build_notion_cycle(conn, user_id, cycle_level, dry_run=DRY_RUN)
        show("build_notion_cycle(dry_run=True)", result)
    finally:
        await tr.rollback()
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
