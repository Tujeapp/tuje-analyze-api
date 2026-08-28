#!/usr/bin/env python3
"""
TuJe — verify that R2 contains the media the database expects.

Three modes:

    python3 tuje-verify.py INT202505100958,INT202505100959
        Check specific interactions. Fast — probes only the expected keys and
        never lists the bucket, so it stays instant at any library size.
        This is the everyday post-upload check.

    python3 tuje-verify.py --subtopic SUBT202505100899
        Check every live interaction in one subtopic.

    python3 tuje-verify.py --all [--verbose]
        Full audit across every live interaction. Summarised by default
        (counts plus the first 20 problems); --verbose lists everything.
        This is the drift check that replaces the "is video_url NULL?" signal
        we gave up by deriving keys instead of storing them. Run it before a
        release, not daily.

Interaction video is mandatory content, so a missing object is a content error
rather than a normal state.

Expected per interaction:
    videos/720/{subtopic_id}/int_{interaction_id}.mp4
    videos/1080/{subtopic_id}/int_{interaction_id}.mp4
    posters/{subtopic_id}/int_{interaction_id}.jpg

Requires DATABASE_URL and R2_ACCOUNT_ID (env or .env), and the `r2` aws profile.
"""
import argparse
import asyncio
import configparser
import os
import pathlib
import sys

import asyncpg
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

BUCKET = "tuje-media"
AWS_PROFILE = "r2"
SUMMARY_LIMIT = 20


# --------------------------------------------------------------------------- env

def _load_env_file():
    for candidate in (pathlib.Path(".env"),
                      pathlib.Path.home() / "Desktop" / "tuje-analyze-api" / ".env"):
        if candidate.is_file():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db_url() -> str:
    _load_env_file()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("error: DATABASE_URL not set (env or .env)")
    return url


def _r2_client():
    _load_env_file()
    account = os.environ.get("R2_ACCOUNT_ID")
    if not account:
        sys.exit("error: R2_ACCOUNT_ID not set — export it in ~/.zprofile")

    cred_path = pathlib.Path.home() / ".aws" / "credentials"
    cp = configparser.ConfigParser()
    cp.read(cred_path)
    if AWS_PROFILE not in cp:
        sys.exit(f"error: aws profile '{AWS_PROFILE}' not found in {cred_path}")

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=cp[AWS_PROFILE]["aws_access_key_id"],
        aws_secret_access_key=cp[AWS_PROFILE]["aws_secret_access_key"],
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


# -------------------------------------------------------------------------- keys

def expected_keys(interaction_id: str, subtopic_id: str):
    base = f"int_{interaction_id}"
    return [
        f"videos/720/{subtopic_id}/{base}.mp4",
        f"videos/1080/{subtopic_id}/{base}.mp4",
        f"posters/{subtopic_id}/{base}.jpg",
    ]


def probe(client, key):
    """Size in bytes, or None if absent. HEAD only — nothing is downloaded."""
    try:
        return client.head_object(Bucket=BUCKET, Key=key)["ContentLength"]
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return None
        raise


def list_all_keys(client) -> dict:
    """Every key in the bucket -> size. Paginated. Only used by --all."""
    keys, token = {}, None
    while True:
        kwargs = {"Bucket": BUCKET, "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            keys[obj["Key"]] = obj["Size"]
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return keys


# ---------------------------------------------------------------------------- db

async def fetch_interactions(ids=None, subtopic=None):
    conn = await asyncpg.connect(_db_url())
    try:
        base = """
            SELECT id, subtopic_id, transcription_fr
            FROM brain_interaction
            WHERE live = true AND COALESCE(archived, false) = false
        """
        if ids:
            return await conn.fetch(base + " AND id = ANY($1::text[]) ORDER BY id", ids)
        if subtopic:
            return await conn.fetch(base + " AND subtopic_id = $1 ORDER BY id", subtopic)
        return await conn.fetch(base + " ORDER BY subtopic_id, id")
    finally:
        await conn.close()


# ------------------------------------------------------------------------ report

def report(rows, problems, requested_ids=None, orphans=None, verbose=False):
    ok = len(rows) - len(problems)

    if requested_ids:
        found = {r["id"] for r in rows}
        unknown = [i for i in requested_ids if i not in found]
        if unknown:
            print("NOT IN DATABASE (typo, archived, or not live):")
            for i in unknown:
                print(f"      ? {i}")
            print()

    if problems:
        shown = problems if verbose else problems[:SUMMARY_LIMIT]
        print(f"INCOMPLETE — {len(problems)} interaction(s):")
        for iid, text, missing in shown:
            label = (text or "")[:48]
            print(f'\n  {iid}  "{label}"')
            for k in missing:
                print(f"      x {k}")
        if len(problems) > len(shown):
            print(f"\n  ... and {len(problems) - len(shown)} more (use --verbose to list all)")
        print()
    elif rows:
        print(f"OK - all {len(rows)} interaction(s) checked have their three objects\n")

    if orphans:
        shown = orphans if verbose else orphans[:SUMMARY_LIMIT]
        print(f"ORPHANS — {len(orphans)} object(s) no live interaction claims:")
        for k in shown:
            print(f"      ? {k}")
        if len(orphans) > len(shown):
            print(f"      ... and {len(orphans) - len(shown)} more (use --verbose)")
        print("  (usually an archived interaction or a changed key — check before deleting)\n")

    line = f"summary: {len(rows)} checked · {ok} complete · {len(problems)} incomplete"
    if orphans is not None:
        line += f" · {len(orphans)} orphan(s)"
    print(line)


# -------------------------------------------------------------------------- main

async def main():
    ap = argparse.ArgumentParser(
        description="Verify R2 contains the media the database expects."
    )
    ap.add_argument("ids", nargs="?", help="comma-separated interaction ids")
    ap.add_argument("--subtopic", help="check every live interaction in this subtopic")
    ap.add_argument("--all", action="store_true", help="full audit (summarised)")
    ap.add_argument("--verbose", action="store_true", help="list every problem")
    args = ap.parse_args()

    if not (args.ids or args.subtopic or args.all):
        ap.print_help()
        sys.exit(2)

    requested = None
    if args.ids:
        requested = [i.strip() for i in args.ids.split(",") if i.strip()]
        rows = await fetch_interactions(ids=requested)
    elif args.subtopic:
        rows = await fetch_interactions(subtopic=args.subtopic)
    else:
        rows = await fetch_interactions()

    if not rows and not requested:
        sys.exit("no matching live interactions")

    client = _r2_client()

    # --all lists the bucket once (cheaper than 3N probes, and it's what makes
    # orphan detection possible). Targeted modes probe only the keys they need.
    present = list_all_keys(client) if args.all else None
    if args.all:
        print(f"{len(rows)} live interaction(s) · {len(present)} object(s) in R2\n")

    problems, expected_all = [], set()
    for r in rows:
        iid, sub = r["id"], r["subtopic_id"]
        if not sub:
            problems.append((iid, r["transcription_fr"],
                             ["<no subtopic_id — cannot derive keys>"]))
            continue
        missing = []
        for key in expected_keys(iid, sub):
            expected_all.add(key)
            size = present.get(key) if args.all else probe(client, key)
            if size is None:
                missing.append(key)
            elif size == 0:
                missing.append(f"{key}  (ZERO BYTES — failed upload)")
        if missing:
            problems.append((iid, r["transcription_fr"], missing))

    orphans = None
    if args.all:
        orphans = sorted(
            k for k in present
            if k.startswith(("videos/", "posters/"))
            and not k.endswith("/")
            and k not in expected_all
        )

    report(rows, problems, requested_ids=requested, orphans=orphans, verbose=args.verbose)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    asyncio.run(main())
