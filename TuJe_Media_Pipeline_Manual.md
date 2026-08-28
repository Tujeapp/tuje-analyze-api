# TuJe — Media Pipeline: How to Use It

Everything you need to add a video to the app. Written for someone who doesn't live in a terminal.

**Where the scripts live:** `~/Desktop/tuje-analyze-api/`
**Where masters live:** external drive, e.g. `/Volumes/YourDrive/tuje-masters/`
**Where the media ends up:** Cloudflare R2 bucket `tuje-media`, served from `https://media.tujeapp.com`

---

## The everyday loop

Three commands. Adding one video:

```bash
cd ~/Desktop/tuje-analyze-api
source venv/bin/activate

./tuje-encode.sh /Volumes/YourDrive/tuje-masters/hotel.mp4 INT202505100958 SUBT202505100899
./tuje-upload.sh
python3 tuje-verify.py INT202505100958
```

Encode, upload, confirm. If verify says everything is present, you're done — the app will serve it.

**Several videos at once:** run `tuje-encode.sh` once per video, then a single `./tuje-upload.sh` at the end (it syncs the whole `out/` tree), then verify with comma-separated ids:

```bash
./tuje-encode.sh /Volumes/.../a.mp4 INT...958 SUBT...899
./tuje-encode.sh /Volumes/.../b.mp4 INT...959 SUBT...899
./tuje-encode.sh /Volumes/.../c.mp4 INT...960 SUBT...899
./tuje-upload.sh
python3 tuje-verify.py INT...958,INT...959,INT...960
```

---

## Terminal basics (if you need them)

| What you want | Command |
|---|---|
| Go to the scripts folder | `cd ~/Desktop/tuje-analyze-api` |
| See where you are | `pwd` |
| List files | `ls` (or `ls -la` for details) |
| See your external drives | `ls /Volumes/` |
| Get a file's exact path | type the command, then **drag the file from Finder into Terminal** |
| Stop a running command | `Ctrl + C` |
| Repeat the last command | press ↑ |

**`~` means your home folder** (`/Users/remisimonet`). So `~/Downloads` is your Downloads folder.

**Paths with spaces need quotes:** `"/Volumes/My Drive/video.mp4"`. Dragging from Finder handles this automatically.

---

## One-time setup (already done, here for reference)

If you ever set this up on a new machine:

```bash
# tools
brew install ffmpeg awscli
pip install boto3 asyncpg          # inside the venv

# make the scripts runnable (downloads strip this)
cd ~/Desktop/tuje-analyze-api
chmod +x tuje-encode.sh tuje-upload.sh

# R2 credentials
aws configure --profile r2
#   Access Key ID     → from Cloudflare
#   Secret Access Key → from Cloudflare
#   region            → auto          ← must be exactly this
#   output            → json

# account id, so you don't paste the endpoint every time
echo 'export R2_ACCOUNT_ID="your-account-id"' >> ~/.zprofile
source ~/.zprofile
```

---

## Renewing the R2 token (every 30 days)

The API token expires. **Only uploads break — video playback in the app is unaffected**, because delivery goes over the public domain and doesn't use this token.

You'll know it expired when an upload fails with `InvalidAccessKeyId` or `AccessDenied`.

1. **dash.cloudflare.com** → **R2 Object Storage** → **Manage R2 API Tokens**
2. Delete the old token (optional but tidy)
3. **Create API token**:
   - Type: **Account API token**
   - Permissions: **Object Read & Write**
   - Buckets: **Apply to specific buckets** → `tuje-media`
   - TTL: 30 days (or longer if the renewal gets annoying)
4. Copy the **Access Key ID** and **Secret Access Key** — the secret shows once only
5. Re-run:
   ```bash
   aws configure --profile r2
   ```
   Paste the new values. Region stays `auto`.
6. Test:
   ```bash
   aws s3 ls s3://tuje-media/ --recursive \
     --endpoint-url "https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com" \
     --profile r2
   ```

⚠️ **Never paste these keys into a chat, a commit, or a shared terminal.** Same care as the OpenAI and Airtable keys.

---

## Encoding

```bash
./tuje-encode.sh <master-file> <interaction-id> <subtopic-id>
```

Produces three files into `out/`, mirroring the R2 key structure:

```
out/videos/720/{subtopic}/int_{interaction}.mp4     free tier
out/videos/1080/{subtopic}/int_{interaction}.mp4    paid tiers
out/posters/{subtopic}/int_{interaction}.jpg        first frame
```

**Both ids are required and are checked.** If you swap them (subtopic where interaction goes), the script stops rather than encoding to a wrong key.

**Expected sizes** for a ~3 second clip: roughly 200 KB (720) and 300 KB (1080). Much larger means unusually high-motion footage — the script prints a note if it exceeds ~100 KB/sec at 720.

Encoding takes 10–30 seconds per video. That's `-preset slow` doing its job; the resulting files are smaller for it.

---

## Uploading

```bash
./tuje-upload.sh
```

Syncs everything in `out/` to R2. Only uploads what changed, so re-running is cheap and safe.

It runs two passes — one for `.mp4`, one for `.jpg` — because each needs a different content type. **A wrong content type makes iOS silently refuse to play the video**, which is why this isn't left to guesswork.

**If you re-encoded an existing video** (same interaction id), the files are cached at the edge for a year with `immutable`. You must purge:

> Cloudflare dashboard → **tujeapp.com** → **Caching** → **Configuration** → **Purge Cache** → **Custom Purge** → paste the URL

Otherwise learners keep getting the old version.

---

## Verifying

```bash
# after uploading — the everyday check
python3 tuje-verify.py INT202505100958

# several at once
python3 tuje-verify.py INT202505100958,INT202505100959

# a whole subtopic
python3 tuje-verify.py --subtopic SUBT202505100899

# full audit before a release
python3 tuje-verify.py --all
python3 tuje-verify.py --all --verbose      # list every problem
```

It compares what the database expects against what's actually in R2 and reports:

- **Missing** objects, with the interaction's French text so you can see which content is incomplete
- **Zero-byte** objects — a failed upload that looks present but isn't
- **Not in database** — if you typo an id
- **Orphans** (`--all` only) — objects no live interaction claims, usually from an archived interaction

**Why the full audit matters:** nothing in the database records whether an interaction has media. URLs are derived from ids, so there's no empty field to spot. `--all` is the only way to catch a video that never got uploaded. Run it before a release, not daily.

---

## Common problems

| Symptom | Cause | Fix |
|---|---|---|
| `permission denied` running a script | Download stripped the execute bit | `chmod +x tuje-encode.sh tuje-upload.sh` |
| `No module named 'asyncpg'` | venv not active | `source venv/bin/activate` |
| `command not found: ffmpeg` | Homebrew not on PATH | Open a new terminal, or `source ~/.zprofile` |
| `R2_ACCOUNT_ID is not set` | Shell doesn't have it | `source ~/.zprofile` |
| `InvalidAccessKeyId` / `AccessDenied` | Token expired or wrong | Renew the token (above) |
| `SignatureDoesNotMatch` | Region isn't `auto` | `aws configure --profile r2`, set region to `auto` |
| `master not found` | Wrong path, or drive unplugged | `ls /Volumes/` to check the drive; drag the file into Terminal |
| Video won't play on iOS | Wrong content type, or missing `-tag:v hvc1` | Re-upload via `tuje-upload.sh` (sets both correctly) |
| Old video still playing after re-encode | Edge cache | Purge the URL in Cloudflare |

---

## Things worth remembering

**Your masters are the only source copy.** Once Cloudinary is deleted, R2 holds only the encoded renditions, which can't be re-encoded to different settings. If the external drive fails, re-filming is the recovery path. Keep a second copy somewhere.

**Nothing is written back to Airtable.** The app derives the video URL from the interaction and subtopic ids at request time. There's no URL field to fill in, and nothing to keep in sync.

**Interaction video is mandatory content.** There's no "this interaction has no video" state — a missing file is an error the verify script catches, not a condition the app handles.

**`immutable` means content at a key never changes.** Replacing a file requires a cache purge. If you find yourself replacing videos often, that's worth revisiting.
