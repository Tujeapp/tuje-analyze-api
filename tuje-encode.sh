hui#!/bin/bash
#
# TuJe — encode one interaction master into the two delivery renditions + poster.
#
#   ./tuje-encode.sh <master-file> <interaction-id> <subtopic-id>
#
# Example:
#   ./tuje-encode.sh ~/Downloads/hotel.mp4 INT202505100958 SUBT202505100899
#
# Output goes to ./out/ mirroring the R2 key structure, so the upload step is a
# straight directory sync:
#
#   out/videos/720/{subtopic}/int_{interaction}.mp4
#   out/videos/1080/{subtopic}/int_{interaction}.mp4
#   out/posters/{subtopic}/int_{interaction}.jpg
#
# Encoding settings are fixed deliberately — see the migration spec §3.
# HEVC (iOS-only, hardware decode), AAC 96k mono (audio is the product),
# and -tag:v hvc1 which AVPlayer REQUIRES to play HEVC at all.

set -euo pipefail

MASTER="${1:-}"
INTERACTION_ID="${2:-}"
SUBTOPIC_ID="${3:-}"

if [[ -z "$MASTER" || -z "$INTERACTION_ID" || -z "$SUBTOPIC_ID" ]]; then
  echo "usage: $0 <master-file> <interaction-id> <subtopic-id>" >&2
  echo "  e.g. $0 ~/Downloads/hotel.mp4 INT202505100958 SUBT202505100899" >&2
  exit 1
fi

if [[ ! -f "$MASTER" ]]; then
  echo "error: master not found: $MASTER" >&2
  exit 1
fi

# Light sanity check on the ids — catches a swapped pair, which would otherwise
# upload a video to the wrong key silently.
if [[ ! "$INTERACTION_ID" =~ ^INT ]]; then
  echo "error: interaction id should start with INT — got '$INTERACTION_ID'" >&2
  echo "       (did you swap the interaction and subtopic arguments?)" >&2
  exit 1
fi
if [[ ! "$SUBTOPIC_ID" =~ ^SUBT ]]; then
  echo "error: subtopic id should start with SUBT — got '$SUBTOPIC_ID'" >&2
  exit 1
fi

OUT_720="out/videos/720/${SUBTOPIC_ID}"
OUT_1080="out/videos/1080/${SUBTOPIC_ID}"
OUT_POSTER="out/posters/${SUBTOPIC_ID}"
mkdir -p "$OUT_720" "$OUT_1080" "$OUT_POSTER"

BASENAME="int_${INTERACTION_ID}"

echo "master      : $MASTER"
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate,codec_name \
  -show_entries format=duration,size \
  -of default=noprint_wrappers=1 "$MASTER" | sed 's/^/              /'
echo "interaction : $INTERACTION_ID"
echo "subtopic    : $SUBTOPIC_ID"
echo

# --- 720 rendition (free tier) -------------------------------------------------
echo "encoding 720 ..."
ffmpeg -hide_banner -loglevel error -y -i "$MASTER" \
  -vf "scale=720:1280:flags=lanczos" \
  -c:v libx265 -preset slow -b:v 700k -maxrate 1000k -bufsize 1400k \
  -pix_fmt yuv420p -tag:v hvc1 \
  -c:a aac -b:a 96k -ac 1 -ar 48000 \
  -movflags +faststart \
  "${OUT_720}/${BASENAME}.mp4"

# --- 1080 rendition (paid tiers) -----------------------------------------------
echo "encoding 1080 ..."
ffmpeg -hide_banner -loglevel error -y -i "$MASTER" \
  -vf "scale=1080:1920:flags=lanczos" \
  -c:v libx265 -preset slow -b:v 1200k -maxrate 1700k -bufsize 2400k \
  -pix_fmt yuv420p -tag:v hvc1 \
  -c:a aac -b:a 96k -ac 1 -ar 48000 \
  -movflags +faststart \
  "${OUT_1080}/${BASENAME}.mp4"

# --- poster (from the MASTER, not a rendition) ---------------------------------
echo "extracting poster ..."
ffmpeg -hide_banner -loglevel error -y -i "$MASTER" \
  -vf "select=eq(n\,0),scale=1080:1920" -frames:v 1 -q:v 4 \
  "${OUT_POSTER}/${BASENAME}.jpg"

echo
echo "done:"
for f in "${OUT_720}/${BASENAME}.mp4" "${OUT_1080}/${BASENAME}.mp4" "${OUT_POSTER}/${BASENAME}.jpg"; do
  printf "  %-52s %8.1f KB\n" "$f" "$(echo "scale=1; $(stat -f%z "$f" 2>/dev/null || stat -c%s "$f") / 1024" | bc)"
done

# Warn if sizes drift well past the spec's targets (scaled by duration).
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$MASTER")
SZ720=$(stat -f%z "${OUT_720}/${BASENAME}.mp4" 2>/dev/null || stat -c%s "${OUT_720}/${BASENAME}.mp4")
EXPECTED=$(echo "$DUR * 100 * 1024" | bc | cut -d. -f1)
if (( SZ720 > EXPECTED )); then
  echo
  echo "  note: 720 is larger than ~100 KB/sec — high-motion footage, or the"
  echo "        bitrate target may need revisiting for this clip."
fi
