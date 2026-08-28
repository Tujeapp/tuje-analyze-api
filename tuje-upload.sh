#!/bin/bash
#
# TuJe — upload the encode output tree to R2.
#
#   ./tuje-upload.sh [out-dir]
#
# Defaults to ./out — the tree tuje-encode.sh writes, which already mirrors the
# R2 keyspace, so this is a straight sync with no path construction.
#
# Two passes rather than one, because `aws s3 sync` applies a single
# --content-type to everything it copies. Videos and posters need different
# types, and a wrong content-type is a SILENT iOS playback failure.
#
# Requires: aws cli configured as profile `r2`, and $R2_ACCOUNT_ID set.

set -euo pipefail

OUT_DIR="${1:-out}"
BUCKET="tuje-media"
PROFILE="r2"
CACHE_CONTROL="public, max-age=31536000, immutable"

if [[ -z "${R2_ACCOUNT_ID:-}" ]]; then
  echo "error: R2_ACCOUNT_ID is not set." >&2
  echo "       add to ~/.zprofile:  export R2_ACCOUNT_ID=\"your-account-id\"" >&2
  exit 1
fi

if [[ ! -d "$OUT_DIR" ]]; then
  echo "error: output directory not found: $OUT_DIR" >&2
  echo "       run tuje-encode.sh first" >&2
  exit 1
fi

ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

FILE_COUNT=$(find "$OUT_DIR" -type f \( -name '*.mp4' -o -name '*.jpg' \) | wc -l | tr -d ' ')
if [[ "$FILE_COUNT" -eq 0 ]]; then
  echo "nothing to upload in $OUT_DIR"
  exit 0
fi

echo "uploading $FILE_COUNT file(s) from $OUT_DIR to s3://$BUCKET"
echo

# --- videos --------------------------------------------------------------------
echo "→ mp4 (video/mp4)"
aws s3 sync "$OUT_DIR/" "s3://${BUCKET}/" \
  --endpoint-url "$ENDPOINT" \
  --profile "$PROFILE" \
  --exclude "*" --include "*.mp4" \
  --content-type "video/mp4" \
  --cache-control "$CACHE_CONTROL" \
  --no-progress

# --- posters -------------------------------------------------------------------
echo "→ jpg (image/jpeg)"
aws s3 sync "$OUT_DIR/" "s3://${BUCKET}/" \
  --endpoint-url "$ENDPOINT" \
  --profile "$PROFILE" \
  --exclude "*" --include "*.jpg" \
  --content-type "image/jpeg" \
  --cache-control "$CACHE_CONTROL" \
  --no-progress

echo
echo "done."
echo
echo "NOTE: objects are uploaded with 'immutable' and a one-year max-age."
echo "      If you REPLACED an existing key (re-encode of the same interaction),"
echo "      edges and clients may serve the old file for up to a year."
echo "      Purge it in Cloudflare: Caching → Configuration → Purge Cache"
echo "      (purge by URL is enough — you don't need to purge everything)."
