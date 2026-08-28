# TuJe — Video Delivery Migration (Cloudinary → Cloudflare R2) — Specification

**Status:** Design agreed, not started. Written for a small library (development stage) —
migration cost rises sharply once content scales, so this is the cheap window.
**Last updated:** Conversation of 12 August 2026.
**Scope:** Runtime delivery of interaction videos and answer images. Encoding ladder,
access control, key derivation, iOS caching, prefetch, and migration sequencing.

**Out of scope (noted, not specified here):** ad integration, subscription/StoreKit
mechanics, edge rate limiting on the FastAPI surface, Turnstile on anonymous user
creation. The last two are flagged in §9 as adjacent work with real cost exposure.

---

## 1. Why

### 1.1 The trigger

Current sample videos encode at ~1 MB/sec. At 5s per interaction that is ~5 MB/video,
roughly 8 Mbps — near-master quality for a clip that plays inside a phone-sized frame,
and an order of magnitude more than low-motion talking-head footage requires.

Projected at 1,000 MAU (≈5,100 sessions/month, 21 interactions each, ~1.5 plays per
interaction): **~800 GB/month**.

### 1.2 Two independent problems

**Cost.** ~800 GB on Cloudinary is ~$320/month, against ~$810/month net revenue at a
realistic 5% paid conversion. Video alone would be ~40% of net revenue, and almost all of
it spent serving free-tier users whose ad revenue is $72–145/month. The free tier is
loss-making at current encoding.

**Hard ceiling.** Cloudinary's Free/Plus/Advanced plans do not bill overage — they warn,
then disable the account. For an app where every interaction is a video fetch, hitting
that ceiling does not degrade the experience, it ends it. This is the more urgent of the
two problems.

### 1.3 Why Cloudinary is the wrong runtime dependency

Cloudinary is a transformation engine. TuJe does not transform at request time — videos
are pre-rendered, uploaded once via the Airtable script, and served identically to every
user. The delivery path pays ~$0.40/GB for a feature set it does not use.

### 1.4 Target

| Line | Now | After |
|---|---|---|
| Video delivery | ~$320 | ~$1–5 |
| Render | $50–85 | $50–85 |
| Whisper | $9 | $9 |
| GPT-4o-mini | ~$1 | ~$1 |
| **Total** | **~$380** | **~$65–100** |

The structural change matters more than the number. Today the dominant cost is variable
and scales with free-tier usage. After, the dominant cost is Render — fixed, and
amortizing as the user base grows.

---

## 2. Architecture decisions

### 2.1 R2 as delivery origin — DECIDED

Cloudflare R2: $0.015/GB storage, $0.00/GB egress at any volume. Storage for the full
library (10,000 videos × 2 renditions × ~750 KB ≈ 15 GB) is roughly $0.23/month.

The library is small and shared across all users, so edge cache hit rates will be near
perfect.

Answer images (`tuje/images/answers/{answer_ID}`) migrate to the same bucket under a
separate prefix. Same argument: static assets served identically to everyone.

### 2.2 Cloudinary removed from runtime entirely — DECIDED

Masters are retained on local hard drives and in Airtable, so Cloudinary is not needed as
a master store. It exits the architecture rather than being demoted to an authoring tool.

Encoding moves to a local ffmpeg pipeline (§3).

### 2.3 Cloudflare Stream rejected — DECIDED

Stream bills $5/1,000 minutes stored + $1/1,000 minutes delivered. At TuJe volumes
(~833 min stored, ~13,400 min delivered/month) that is ~$18–20/month versus near-zero on
R2. Survivable, but strictly worse.

The real objection is latency. Stream encodes into multiple quality levels for adaptive
bitrate delivery over HLS/DASH. ABR exists to handle bandwidth changes *during* playback;
TuJe clips are 5 seconds. Manifest fetch → rendition selection → segment fetch costs more
round trips than the video lasts. A single small MP4 from R2 is one GET.

**Stream is built for the opposite problem.**

### 2.4 D1 / KV / Durable Objects rejected — DECIDED

TuJe is server-authoritative with PostgreSQL as single source of truth. A second state
store at the edge would fragment that, and schema-vs-code drift is already a known open
concern. Do not add a second place for drift to happen.

### 2.5 Workers for application logic rejected — DECIDED

Backend is FastAPI on Render and works. Splitting session logic across two runtimes means
two deploy paths and two places to look when something breaks, for no cost saving.

Workers as *plumbing* (signature validation, path rewriting) remains open — see §4.4.

---

## 3. Encoding ladder

### 3.1 Two renditions — DECIDED

| Rendition | Target | ~Size (5s) | Served to |
|---|---|---|---|
| `720` | 720×1280, HEVC, ~700 kbps | ~440 KB | Free tier |
| `1080` | 1080×1920, HEVC, ~1.2 Mbps | ~750 KB | Listening+ and Premium |

iOS-only means HEVC with no H.264 fallback to maintain — hardware decode on every
supported device.

Storing both is noise (~$0.23/month total). The saving is on delivery: ~40% off the
largest free-tier cost line.

### 3.2 Audio floor — DECIDED

**Audio is the product; video is context.** AAC 96 kbps mono, ~60 KB per clip. Video
bitrate can be pushed hard; audio should not be.

### 3.3 Resolution floor — DECIDED

720p is the floor for free tier even though the bandwidth math keeps favouring lower.
TuJe teaches through lip movement as well as audio — this is pedagogy, not decoration.

### 3.4 Not a marketed difference — DECIDED

On a phone-sized frame, 720p and 1080p HEVC of a talking head are close to
indistinguishable. Rendition tiering is **internal cost control only**.

Rationale for not marketing it:
- Promises a difference users cannot perceive
- Creates a support category ("my videos look blurry") for a non-difference
- The paid tiers already have a clear story: no ads, and speaking

**Do not put "HD video" on the paywall.**

---

## 4. Access control

Security preferred over cost. Signed URLs with short TTL.

### 4.1 Two decisions, deliberately separated — DECIDED

Two things must happen before a video plays, and they are easy to conflate:

1. **Which rendition** — a *personalization* decision, needs tier, needs the DB
2. **Is this user allowed** — an *authorization* decision, needs only arithmetic

They have different information needs and different failure modes. One component should
not do both.

### 4.2 Tier resolution in FastAPI — DECIDED

Tier lives in Postgres. FastAPI already reads it in the same request that decides what to
teach next. Resolving rendition is one more read on a row already loaded.

Rejected alternatives:
- **Worker queries Postgres** — adds DB connections from an unpredictable number of edge
  locations. Connection churn on the one component that should stay stateless.
- **Tier as a JWT claim** — goes stale. User upgrades, keeps getting 720p until token
  refresh. Two sources of truth for entitlement that can disagree.

The second failure is exactly the class of bug the server-authoritative rule exists to
prevent. iOS never computes what to teach; the edge should not compute what a user is
entitled to.

### 4.3 Quality in the path — DECIDED

```
/v1/{quality}/{subtopic_id}/int_{interaction_id}.mp4
```

FastAPI resolves tier → picks quality → constructs path → signs → returns URL in the
interaction payload. The validating layer checks the signature and serves bytes. **It
never learns the user's tier, because it does not need to.**

Three properties this buys:

- **Clean edge caching.** Different renditions are different URLs, so Cloudflare cache
  keys work without customization. Dynamic rendition selection on a single URL would
  require custom cache keys to stop the edge serving 1080p bytes to a free user.
- **Tampering closed for free.** Signature covers the full path including `{quality}`, so
  editing `/720/` → `/1080/` invalidates it. No extra check. (Incentive to try is
  near-zero given §3.4, but it costs nothing to close.)
- **AVPlayer stays simple.** Header-based auth is awkward with `AVURLAsset`
  (`AVAssetResourceLoaderDelegate` territory). A signed URL is just a URL.

### 4.4 R2 presign vs. custom Worker HMAC — OPEN

| | Presign | Worker HMAC |
|---|---|---|
| Code | Less | More |
| Extensibility | Fixed | Logging, per-user rate limits, revocation |
| Edge cache behaviour | **Unverified** | Cacheable path, likely predictable |

**Blocking unknown:** whether R2 presigned URLs bypass the Cloudflare edge cache and hit
R2 directly. If they do, every cold fetch is an origin request and the CDN benefit is
lost.

**This is the empirical question that Step 1 of the migration exists to answer.** Do not
choose until measured.

### 4.5 TTL — DECIDED (provisional value)

**~2 hours.** A session is 21 interactions, plus backgrounding, plus the user putting the
phone down. A URL signed early must still be valid when the last interaction plays.

Long enough that expiry never bites a real user; short enough that a leaked link is
worthless by the time it is shared. Because the iOS cache keys on interaction ID rather
than URL (§5.1), a short TTL costs nothing in re-downloads.

---

## 5. iOS caching

### 5.1 Cache key: `interactionId|quality` — DECIDED

```
"INT202505123|720"
```

**The conflict this resolves:** signed URLs and replay caching fight each other. A
short-lived signature produces a different URL string every time it is issued. iOS
`URLCache` keys on URL, so a re-signed URL for the same video looks like a new resource
and re-downloads. That would mean paying full bandwidth for every replay — exactly what
caching was meant to prevent.

Keying the local cache on interaction ID instead of URL decouples the two: signature
rotates freely, local copy stays valid. Tight TTL **and** free replays.

**Why quality is in the key:** on upgrade, a cache keyed on interaction ID alone would
keep serving the stale 720p file until eviction. With quality in the key, upgraded users
fetch fresh under a new key and old files age out naturally.

Same shape as the existing `displayKey` pattern — a composite key separating what a thing
*is* from which variant is held.

### 5.2 Eviction — DECIDED

Size-capped LRU. Bounded disk usage.

### 5.3 Downgrade behaviour — DECIDED

**Let cached 1080p files age out.** No active eviction on downgrade. Evicting is punitive
for no real saving and adds state to manage. §5.1's key structure makes upgrade and
downgrade behave symmetrically without special-casing either.

### 5.4 Implementation note

Custom cache layer, not `URLCache`. More code than relying on the system cache, but it is
the only design that delivers both agreed requirements.

---

## 6. Prefetch — one-interaction lookahead

### 6.1 Full cycle prefetch is not possible — CORRECTED

An earlier proposal assumed the persisted candidate pool (Option B) *was* the seven
interactions that play. It is not — the pool is larger, and the seven are selected from it
based on performance. Video URLs for a whole cycle are not knowable at cycle open.

### 6.2 What works instead — DECIDED

Option α means the orchestrator determines the next interaction inside the submit-answer
response. At the moment the user submits interaction N, the backend knows N+1 and its
video URL is already in the payload.

**iOS starts fetching the instant that response lands** — while the user is still reading
their score — so the video is warm before they tap to continue.

No API change beyond what is already returned. This is the cheap 80% of full prefetch.

### 6.3 Why it matters beyond cost

A stalled video mid-session breaks the learning loop in a way a slow API call does not.
The replay is a comprehension action, not a convenience.

---

## 7. Key derivation — derive, do not store

### 7.1 Decision

The backend constructs R2 keys from data it already has. **No new URL column on
`brain_interaction`.**

Current Cloudinary path is already deterministic:
`tuje/videos/interactions/{subtopic_id}/int_{interaction_id}.mp4`

R2 equivalent: `videos/{quality}/{subtopic_id}/int_{interaction_id}.mp4`

### 7.2 Rationale

`brain_interaction` is Airtable-synced. A new URL column means teaching the sync script to
populate it, and it means the URL becomes one more field that can drift between Airtable
and the DB. A derived key sidesteps this entirely — nothing new to sync, nothing new to
drift.

### 7.3 Trade-off accepted

A missing file fails at runtime rather than being caught by a null check. With a library
this small, verifying presence before cutover is cheap (Step 3).

---

## 8. Migration sequence

Sequenced so each step is independently verifiable and nothing ships two risky changes
together.

### Step 1 — R2 bucket + access control, one hardcoded video
Prove playback end to end in iOS. No DB or backend changes.
**This is where §4.4 gets settled empirically** — measure whether presigned requests hit
the edge cache or fall through to origin.
*Verify:* video plays; cache hit/miss headers confirm edge behaviour.

### Step 2 — Encode pipeline against masters
Produce both renditions from hard-drive masters. Check file sizes against §3.1 targets and
eyeball quality on a real device. No app changes.
*Verify:* sizes within target; 720p legible for lip movement on device.

### Step 3 — Full library upload + presence verification
Every interaction has both renditions present at the derived key. Cloudinary still serving.
*Verify:* script confirms 2 × N objects exist and are non-zero.

### Step 4 — Backend URL construction behind a feature flag
FastAPI resolves tier, builds path, signs, returns URL.
**Rollback is flipping the flag, not reverting a deploy.**
*Verify:* signed URLs for both tiers; tampered path rejected; expired signature rejected.

### Step 5 — iOS cache layer keyed by `interactionId|quality`
Plus one-interaction lookahead prefetch.
*Verify:* replays hit local cache (no network); upgrade fetches new rendition; LRU evicts
at cap.

### Step 6 — Observe one week, then remove Cloudinary from runtime

**Steps 4 and 5 are the two that can break a live session. Separate them with a
verification pass — do not ship together.**

---

## 9. Adjacent work (not in this spec, flagged for sequencing)

### 9.1 Edge rate limiting on the FastAPI surface

The Whisper endpoint costs money on every call, sits on a public URL, and has no ceiling.
A script pointed at it makes the OpenAI bill the attack surface. Application-level quota
enforcement (3/day free, 7/day Listening+) still costs a Render request and a DB round
trip per rejected call.

Cloudflare in front of the API rejects before it reaches the backend.

### 9.2 Turnstile on anonymous user creation

Onboarding issues a JWT before an account exists — correct product decision, but it makes
free Whisper attempts farmable: delete app, reinstall, new anonymous identity, three more
attempts.

Adjacent to the already-fixed `anon_token` resurrection bug — same shape, different
direction. Turnstile is free and invisible in the common case. Gate anonymous user
*creation*, not the session.

Cheaper to design in now, while onboarding is fresh, than to retrofit after the bill
arrives.

### 9.3 Transcription cost — parked

GPT-4o-mini-transcribe is ~$0.003/min against Whisper's ~$0.006/min. Same vendor, no new
integration. Cloudflare Workers AI also runs Whisper, pricing model unverified.

Not worth effort at $9/month. Revisit if voice usage grows ~10×. Either switch requires
testing against held-out real user audio — accented, hesitant, mid-sentence learner French
is not the distribution these models are benchmarked on.

---

## 10. Open questions

| # | Question | Resolved by |
|---|---|---|
| 1 | R2 presign vs. Worker HMAC (§4.4) | Step 1 measurement |
| 2 | Exact bitrate targets — do §3.1 numbers hold on real footage? | Step 2 |
| 3 | Is ~2h TTL right once real session durations are observed? | Post Step 6 |
| 4 | Answer-image migration — same steps or folded into Step 3? | Before Step 3 |

---

## 11. Decisions log

| Decision | Status |
|---|---|
| R2 as delivery origin | DECIDED |
| Cloudinary removed from runtime entirely | DECIDED |
| Cloudflare Stream rejected (latency, not cost) | DECIDED |
| D1/KV/Durable Objects rejected | DECIDED |
| Workers for application logic rejected | DECIDED |
| Two renditions, 720 free / 1080 paid | DECIDED |
| Rendition tiering NOT marketed | DECIDED |
| Audio floor: AAC 96 kbps mono | DECIDED |
| Resolution floor: 720p | DECIDED |
| Tier resolution in FastAPI, not the edge | DECIDED |
| Quality in the signed path | DECIDED |
| iOS cache key `interactionId\|quality` | DECIDED |
| Cached files age out on downgrade | DECIDED |
| One-interaction lookahead prefetch | DECIDED |
| Derive R2 keys, no new DB column | DECIDED |
| Sequential migration, flag-gated at Step 4 | DECIDED |
| Presign vs. Worker HMAC | OPEN — Step 1 |
| TTL exact value | PROVISIONAL — 2h |
