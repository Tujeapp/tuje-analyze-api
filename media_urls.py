"""
TuJe — media URL construction and signing.

Keys are DERIVED, never stored. Nothing in the database or Airtable holds a media
URL; the path is built from ids the interaction row already carries. That removes
a whole class of drift (and is why 11 of the 12 old Cloudinary `video_url` values
could be malformed without anyone noticing).

Videos are signed. The signature covers the FULL object key, which is what
enforces tiers: a free user cannot swap /720/ for /1080/ because the token they
were given doesn't validate against the other key.

Posters are unsigned — low value, and it keeps the client simple.

The token format is mirrored exactly by the Cloudflare Worker
(tuje-media/src/index.js). Both sides were verified to produce identical
signatures. If you change the scheme here, change it there in the same deploy,
or every outstanding URL breaks.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

SCHEME = "v1"
MEDIA_BASE = os.getenv("MEDIA_BASE_URL", "https://media.tujeapp.com")
TOKEN_TTL_SECONDS = 3600  # 1 hour — comfortably longer than a session, short
                          # enough that a shared URL dies quickly.

def r2_enabled() -> bool:
    """Feature flag. Off by default, so deploying this code changes nothing until
    USE_R2_MEDIA is set in the environment. Flip it back to fall straight back to
    the stored Cloudinary columns — no redeploy needed."""
    return os.getenv("USE_R2_MEDIA", "false").strip().lower() in ("1", "true", "yes")


# Quality per plan. Free and basic get 720; pro gets 1080.
_QUALITY_BY_PLAN = {
    "free": "720",
    "basic": "720",
    "pro": "1080",
}
_DEFAULT_QUALITY = "720"


def quality_for_plan(plan: Optional[str]) -> str:
    """Map a subscription tier to a video rendition. Unknown plans get the
    cheaper one — failing closed costs a user some sharpness, never money."""
    return _QUALITY_BY_PLAN.get((plan or "").strip().lower(), _DEFAULT_QUALITY)


def video_key(interaction_id: str, subtopic_id: str, quality: str) -> str:
    return f"videos/{quality}/{subtopic_id}/int_{interaction_id}.mp4"


def poster_key(interaction_id: str, subtopic_id: str) -> str:
    return f"posters/{subtopic_id}/int_{interaction_id}.jpg"


def _sign(key: str, expiry: int, secret: str) -> str:
    data = f"{SCHEME}:{key}:{expiry}".encode()
    sig = hmac.new(secret.encode(), data, hashlib.sha256).digest()
    b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{SCHEME}.{expiry}.{b64}"


def signed_video_url(
    interaction_id: str,
    subtopic_id: str,
    plan: Optional[str],
    ttl: int = TOKEN_TTL_SECONDS,
) -> Optional[str]:
    """Signed, tier-appropriate video URL. None if signing isn't configured —
    the caller decides whether to fall back or fail."""
    secret = os.getenv("MEDIA_SIGNING_SECRET")
    if not secret:
        logger.error("MEDIA_SIGNING_SECRET is not set — cannot sign media URLs")
        return None
    if not interaction_id or not subtopic_id:
        logger.warning(
            "cannot derive video key: interaction=%s subtopic=%s",
            interaction_id, subtopic_id,
        )
        return None

    key = video_key(interaction_id, subtopic_id, quality_for_plan(plan))
    token = _sign(key, int(time.time()) + ttl, secret)
    return f"{MEDIA_BASE}/{key}?t={token}"


def poster_url(interaction_id: str, subtopic_id: str) -> Optional[str]:
    """Unsigned poster URL."""
    if not interaction_id or not subtopic_id:
        return None
    return f"{MEDIA_BASE}/{poster_key(interaction_id, subtopic_id)}"


def media_for_interaction(
    interaction_id: str,
    subtopic_id: Optional[str],
    plan: Optional[str],
    stored_video_url: Optional[str] = None,
    stored_poster_url: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Resolve (video_url, poster_url) for one interaction.

    Returns the stored Cloudinary values untouched while the flag is off, so this
    can be called unconditionally at every call site and the flag is the only
    thing that changes behaviour.
    """
    if not r2_enabled():
        return stored_video_url, stored_poster_url

    video = signed_video_url(interaction_id, subtopic_id, plan)
    poster = poster_url(interaction_id, subtopic_id)

    # Fail back rather than serve nothing if the key can't be derived (missing
    # subtopic_id) or signing isn't configured.
    if video is None:
        logger.warning("R2 video URL unavailable for %s — falling back to stored",
                       interaction_id)
        video = stored_video_url
    if poster is None:
        poster = stored_poster_url

    return video, poster
