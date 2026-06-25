# Note — Double-Session Guard (force-close active session on new start)

**Status:** TODO, not built. Logged during the notion build (the NULL-marker model
rests on "one open session per user", currently unenforced).

## The requirement (Rémi)
When a user starts a new session, if they already have an `active` session, **forcibly
close the existing active session** (set it to `completed` or a dedicated abandoned
status) before creating the new one. A user must never have two `active` sessions.

## Why it matters
- The notion NULL-marker model assumes one open session: a session_notion row with
  `session_id IS NULL` unambiguously belongs to the about-to-start session. Two
  overlapping starts could create ambiguous NULL rows. (Orphan-cleanup mitigates the
  notion side, but the broader invariant should be enforced at session creation.)
- Two active sessions would break many session-level assumptions beyond notions.

## Where it goes
`start_session_endpoint` (`session_management_router.py` ~L119), at the very start of
session creation: check for an existing `active` session for the user; if found, close
it (status -> completed/abandoned, set completed_at) before proceeding.

## Open questions
- Close as `completed` or a distinct `abandoned`/`incomplete` status? (The session
  status CHECK allows: active, completed, incomplete, archived.) `incomplete` may be the
  honest label for a force-closed session.
- Should a force-closed session count toward session_rank / streaks / history? Probably
  treat it as not-fully-completed (so it doesn't pollute carry-forward's "last completed
  session" or streak math).
- Interaction with the notion carry-forward: carry-forward reads the "highest
  session_rank completed" session. A force-closed session should likely NOT be the one
  carry-forward reads (it has no meaningful end-state), so closing it as `incomplete`
  (not `completed`) keeps it out of carry-forward's selection.

## Encountered example
During the notion integration-run setup, the test user had a stale `active` session
(SESSION202606171328525723, rank 4, abandoned ~8 days). Manually set to completed to
clear it. With the guard, this would have been auto-closed on the next start.
