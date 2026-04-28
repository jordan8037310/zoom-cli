"""Per-tier token-bucket rate limiting for the Zoom REST API (closes #49).

Zoom enforces per-account rate limits broken into four tiers (per
https://developers.zoom.us/docs/api/rate-limits/):

| Tier               | Per-second cap | Per-day cap |
|--------------------|----------------|-------------|
| Light              | 80             | —           |
| Medium             | 60             | —           |
| Heavy              | 40             | 60,000      |
| Resource-intensive | 20             | 60,000      |

This module provides:

  - :class:`Tier` — enum of the four tiers.
  - :data:`TIER_LIMITS` — pinned table mapping tier → (per_sec, daily).
  - :data:`ENDPOINT_TIERS` — list of ``(method, regex, Tier)`` rules
    matched in order; tests pin every endpoint the CLI currently uses.
  - :func:`tier_for(method, path)` — classify a request.
  - :class:`TokenBucket` — pure token-bucket primitive with injectable
    clock + sleep so tests run deterministically.
  - :class:`DailyCounter` — UTC-day window counter with injectable clock.
    Raises :class:`DailyCapExhaustedError` when the cap is hit; we
    deliberately don't sleep until midnight (could be many hours).
  - :class:`RateLimiter` — composes per-tier buckets + daily counters.
    Pass an instance to :class:`~zoom_cli.api.client.ApiClient` to
    enable limiting; default is no limiting (the 429 retry from #16
    catches most single-shot use).

The 429/Retry-After backoff from #16 still runs *after* this limiter:
the limiter prevents most violations proactively; the 429 retry catches
anything the per-account state didn't predict (e.g., other clients on
the same account also hammering Zoom).
"""

from __future__ import annotations

import enum
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone


class Tier(enum.Enum):
    """Zoom's four rate-limit tiers, ordered roughly by burst budget."""

    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"
    RESOURCE_INTENSIVE = "resource_intensive"


@dataclass(frozen=True)
class TierLimit:
    """Per-tier caps. ``daily`` is ``None`` for tiers without a daily cap."""

    per_sec: int
    daily: int | None


#: Pinned by a test — bumping these requires updating the docstring at the
#: top of this file too.
TIER_LIMITS: dict[Tier, TierLimit] = {
    Tier.LIGHT: TierLimit(per_sec=80, daily=None),
    Tier.MEDIUM: TierLimit(per_sec=60, daily=None),
    Tier.HEAVY: TierLimit(per_sec=40, daily=60_000),
    Tier.RESOURCE_INTENSIVE: TierLimit(per_sec=20, daily=60_000),
}


# ---- endpoint → tier classification --------------------------------------
#
# Order matters: most-specific patterns first. Each rule is
# ``(method or "*", compiled regex, Tier)``. ``method == "*"`` matches
# any method. The regex is anchored with ^ and $ implicitly via fullmatch.

_TIER_RULES: list[tuple[str, re.Pattern[str], Tier]] = [
    # /users/me — single-resource read, the cheapest call.
    ("GET", re.compile(r"/users/me"), Tier.LIGHT),
    # GET /users — listing
    ("GET", re.compile(r"/users"), Tier.MEDIUM),
    # GET /users/<id>/settings — single-user metadata
    ("GET", re.compile(r"/users/[^/]+/settings"), Tier.LIGHT),
    # GET /users/<id>/meetings — listing for a user
    ("GET", re.compile(r"/users/[^/]+/meetings"), Tier.MEDIUM),
    # GET /users/<id>/recordings — listing recordings
    ("GET", re.compile(r"/users/[^/]+/recordings"), Tier.MEDIUM),
    # GET /users/<id> — single user
    ("GET", re.compile(r"/users/[^/]+"), Tier.LIGHT),
    # POST /users — create user
    ("POST", re.compile(r"/users"), Tier.HEAVY),
    # DELETE /users/<id> — disassociate / delete
    ("DELETE", re.compile(r"/users/[^/]+"), Tier.MEDIUM),
    # POST /users/<id>/meetings — create meeting
    ("POST", re.compile(r"/users/[^/]+/meetings"), Tier.HEAVY),
    # GET /meetings/<id>/recordings — single meeting's recordings
    ("GET", re.compile(r"/meetings/[^/]+/recordings"), Tier.LIGHT),
    # DELETE /meetings/<id>/recordings or .../recordings/<rid>
    ("DELETE", re.compile(r"/meetings/[^/]+/recordings(?:/[^/]+)?"), Tier.MEDIUM),
    # PUT /meetings/<id>/status — end meeting
    ("PUT", re.compile(r"/meetings/[^/]+/status"), Tier.MEDIUM),
    # GET /meetings/<id>
    ("GET", re.compile(r"/meetings/[^/]+"), Tier.LIGHT),
    # PATCH /meetings/<id> — update
    ("PATCH", re.compile(r"/meetings/[^/]+"), Tier.MEDIUM),
    # DELETE /meetings/<id>
    ("DELETE", re.compile(r"/meetings/[^/]+"), Tier.MEDIUM),
    # ---- Zoom Phone (#18) — listings are MEDIUM, single-resource is LIGHT
    ("GET", re.compile(r"/phone/users/[^/]+/call_logs"), Tier.MEDIUM),
    ("GET", re.compile(r"/phone/users/[^/]+/recordings"), Tier.MEDIUM),
    ("GET", re.compile(r"/phone/users/[^/]+"), Tier.LIGHT),
    ("GET", re.compile(r"/phone/users"), Tier.MEDIUM),
    ("GET", re.compile(r"/phone/call_logs"), Tier.MEDIUM),
    ("GET", re.compile(r"/phone/call_queues"), Tier.MEDIUM),
    ("GET", re.compile(r"/phone/recordings"), Tier.MEDIUM),
    # ---- Zoom Team Chat (#19)
    ("GET", re.compile(r"/chat/users/[^/]+/channels"), Tier.MEDIUM),
    ("POST", re.compile(r"/chat/users/[^/]+/messages"), Tier.MEDIUM),
]

#: Default tier for unmapped endpoints. MEDIUM matches Zoom's most-common
#: tier for read+listing endpoints, so it's the safe default.
_DEFAULT_TIER = Tier.MEDIUM


def tier_for(method: str, path: str) -> Tier:
    """Classify a request into a :class:`Tier`.

    ``path`` should be the URL path (no query string, no leading host).
    A leading API-version prefix (``/v1``, ``/v2``, ...) is stripped
    before matching, so callers can pass either the relative path
    (``/users/me``) or the full path (``/v2/users/me``). Trailing
    slashes are stripped. Unknown endpoints fall back to
    :data:`_DEFAULT_TIER` (MEDIUM).
    """
    method_u = method.upper()
    path_no_query = path.split("?", 1)[0]
    # Strip a leading version prefix like /v1, /v2, /v33.
    path_norm = re.sub(r"^/v\d+", "", path_no_query).rstrip("/") or "/"
    for rule_method, regex, tier in _TIER_RULES:
        if rule_method != "*" and rule_method != method_u:
            continue
        if regex.fullmatch(path_norm):
            return tier
    return _DEFAULT_TIER


# ---- primitives ---------------------------------------------------------


class DailyCapExhaustedError(RuntimeError):
    """Daily cap for a tier is exhausted.

    Sleeping until UTC midnight could be many hours; we surface this as
    an exception so the caller can decide (defer the job, alert, etc.)
    rather than silently blocking.
    """

    def __init__(self, tier: Tier, cap: int) -> None:
        super().__init__(
            f"Daily cap of {cap} requests for tier {tier.value} is exhausted; "
            "retry after UTC midnight"
        )
        self.tier = tier
        self.cap = cap


class TokenBucket:
    """Classic token-bucket primitive.

    Constructor:
      capacity:  max tokens the bucket holds
      rate:      tokens added per second
      clock:     callable returning monotonic seconds (default time.monotonic)
      sleep:     callable taking seconds (default time.sleep)

    ``acquire(n=1.0)`` returns the number of seconds slept (0.0 on a hit).
    """

    def __init__(
        self,
        capacity: float,
        rate: float,
        *,
        clock=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        self.capacity = float(capacity)
        self.rate = float(rate)
        self._tokens = float(capacity)
        self._last = clock()
        self._clock = clock
        self._sleep = sleep

    def _refill(self) -> None:
        now = self._clock()
        delta = now - self._last
        if delta > 0:
            self._tokens = min(self.capacity, self._tokens + delta * self.rate)
            self._last = now

    def acquire(self, n: float = 1.0) -> float:
        self._refill()
        if self._tokens >= n:
            self._tokens -= n
            return 0.0
        deficit = n - self._tokens
        wait = deficit / self.rate
        self._sleep(wait)
        # Advance internal clock + drain the bucket; we consumed our share.
        self._last = self._clock()
        self._tokens = 0.0
        return wait


class DailyCounter:
    """UTC-day window counter; raises when the cap is hit.

    Constructor takes ``daily_cap`` and an optional ``clock`` returning a
    timezone-aware ``datetime`` (default ``datetime.now(timezone.utc)``).
    The window resets when the UTC date changes.
    """

    def __init__(
        self,
        daily_cap: int,
        *,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._cap = daily_cap
        self._clock = clock
        self._count = 0
        self._day: date = clock().date()

    def acquire(self, tier: Tier) -> None:
        today = self._clock().date()
        if today != self._day:
            self._day = today
            self._count = 0
        if self._count >= self._cap:
            raise DailyCapExhaustedError(tier, self._cap)
        self._count += 1


# ---- composed limiter --------------------------------------------------


class RateLimiter:
    """Composes a per-tier :class:`TokenBucket` + (where applicable) a
    :class:`DailyCounter`.

    Default per-tier capacities and refill rates come from
    :data:`TIER_LIMITS`. Inject ``clock`` / ``sleep`` / ``day_clock`` to
    drive deterministic tests.
    """

    def __init__(
        self,
        *,
        clock=time.monotonic,
        sleep=time.sleep,
        day_clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._buckets: dict[Tier, TokenBucket] = {}
        self._daily: dict[Tier, DailyCounter] = {}
        for tier, limit in TIER_LIMITS.items():
            self._buckets[tier] = TokenBucket(
                capacity=limit.per_sec,
                rate=limit.per_sec,
                clock=clock,
                sleep=sleep,
            )
            if limit.daily is not None:
                self._daily[tier] = DailyCounter(limit.daily, clock=day_clock)

    def acquire(self, method: str, path: str) -> Tier:
        """Block until a slot is available for ``(method, path)``.

        Returns the tier the request was classified as (useful for
        logging / metrics). Raises :class:`DailyCapExhaustedError` if
        the tier's daily cap is hit.
        """
        tier = tier_for(method, path)
        # Daily counter first — if exhausted, no point in waiting on the
        # per-second bucket.
        if tier in self._daily:
            self._daily[tier].acquire(tier)
        self._buckets[tier].acquire()
        return tier
