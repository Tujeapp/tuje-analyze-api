# TuJe — Step 1 Results: R2 delivery verified, §4.4 RESOLVED

**Date:** 2026-08-28

## Setup completed
- Cloudflare account + R2 enabled; bucket **`tuje-media`** (Standard, Automatic location)
- Domain **tujeapp.com** purchased through Cloudflare Registrar (already on Cloudflare DNS — no nameserver wait)
- Custom domain connected: **`media.tujeapp.com`** → `tuje-media`
  - Initially connected to the root `tujeapp.com`, moved to the `media.` subdomain to keep the root free for the future marketing site
- R2 Account API token (Object Read & Write, scoped to `tuje-media`, 30-day TTL); AWS CLI configured as profile `r2` with `region = auto`
- Test object uploaded at the derived key: `videos/720/SUBT202505100899/int_INT202505100958.mp4`, `content-type: video/mp4`, `cache-control: public, max-age=31536000, immutable`

## Measurement 1 — plain custom-domain URL: CACHES ✓
```
request 1: cf-cache-status: MISS
request 2: cf-cache-status: HIT
```
Edge caching works over the custom domain with the cache-control header set at upload.

**⚠️ Methodology gotcha:** `curl -I` (HEAD) reports `cf-cache-status: DYNAMIC` even when GETs cache correctly. This sent us chasing a nonexistent config problem — we nearly added an unnecessary Cache Rule. **Always measure cache behaviour with GET** (`curl -s -o /dev/null -D -`), never `curl -I`.

## Measurement 2 — presigned URL: DOES NOT CACHE ✗
A presigned URL against `<account>.r2.cloudflarestorage.com` returned **no `cf-cache-status` header at all** on either request (only the stored `Cache-Control` came through).

The absence of the header is the finding: the S3 API endpoint serves objects directly from R2 storage and never touches Cloudflare's CDN caching layer. Presigned URLs therefore cannot benefit from edge caching.

## DECISION — §4.4 resolved: Worker + HMAC

Presigned URLs are ruled out for delivery. Every view would be a direct storage read (a Class B operation, no cache), rather than an edge-cached hit shared across all users.

**Architecture for Step 4:** requests go to `media.tujeapp.com` (CDN-fronted, caches), fronted by a Cloudflare Worker that validates a short-lived HMAC token minted by the FastAPI backend. This keeps access controlled *and* cacheable.

Open sub-question for Step 4: whether the HMAC token travels as a query parameter (simplest, but a varying query string can itself defeat caching unless the Worker normalises the cache key) or a header/cookie. The Worker must be written so the **cache key excludes the token**, otherwise every user gets a distinct cache entry and the caching benefit is lost.

## Encoding validated (Step 2)
Real master: 1080×1920, H.264, 25 fps, 2.52s, **14.4 Mbps**, 4.69 MB (~1.86 MB/sec — nearly double the spec's ~1 MB/sec estimate, so the cost case is stronger than argued).

| rendition | size (2.52s) | scaled to 5s | spec target |
|---|---|---|---|
| 720×1280 HEVC 700k + AAC 96k mono | 194–213 KB | ~423 KB | ~440 KB ✓ |
| 1080×1920 HEVC 1200k + AAC 96k mono | 298 KB | ~591 KB | ~750 KB ✓ |
| poster (from master, q4) | ~109 KB | — | — |

Both under target. Open question #2 (are the §3.1 targets right?) is **closed** — confirmed on device by Rémi, 720 legibility acceptable.

**`-tag:v hvc1` is mandatory.** Without it ffmpeg tags HEVC as `hev1`, which AVPlayer silently refuses to play while desktop players work fine.

Script: `tuje-encode.sh <master> <interaction-id> <subtopic-id>` — encodes both renditions + poster into an `out/` tree mirroring the R2 keyspace, so upload is a single `aws s3 sync out/ s3://tuje-media/`. Validates id prefixes (INT/SUBT) to catch swapped arguments.

## Workflow decisions settled
- **Cloudinary is bypassed entirely** — it was doing transformation (now local ffmpeg) and hosting (now R2). The four upload routers get deleted rather than rewritten.
- **Masters stay local** (drive + external backup). Not attached to Airtable. Note this makes the local masters the only copy of the source once Cloudinary is deleted.
- **Encoding is local**, one interaction at a time: `./tuje-encode.sh master.mp4 INT... SUBT...`. Batch mode deferred until volume makes it worthwhile.
- **Nothing is written back to Airtable.** URLs are derived at request time from `subtopic_id` + `interaction_id`, per §7. No sync change needed for media.
- **Media presence:** interaction video is mandatory in real content; everything else optional. Absence of a mandatory asset is a content error caught by Step 3's verification script, not a runtime condition to handle.

## Security note
A presigned URL was pasted into the conversation during testing — it embeds the Access Key ID in `X-Amz-Credential`. The token was rotated immediately. **Presigned URLs are credential-bearing and should never be shared.**

## Next
- **Step 3:** upload script (encode output → R2 with correct content-type and cache-control per file) + presence-verification script
- **Step 4:** the Cloudflare Worker (HMAC validation, cache key excluding the token) + backend URL construction, flag-gated
- **Step 5:** iOS cache layer + prefetch — ship separately from Step 4, per the spec
