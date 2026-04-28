"""Tests for zoom_cli.api.rate_limit — per-tier token-bucket limiter."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from zoom_cli.api.rate_limit import (
    TIER_LIMITS,
    DailyCapExhaustedError,
    DailyCounter,
    RateLimiter,
    Tier,
    TokenBucket,
    tier_for,
)

# ---- TokenBucket -------------------------------------------------------


class _FakeClock:
    """Manually-advanceable clock + sleep pair for deterministic tests."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_token_bucket_allows_initial_burst_up_to_capacity() -> None:
    """Bucket starts full; the first ``capacity`` acquires don't sleep."""
    clock = _FakeClock()
    bucket = TokenBucket(capacity=5, rate=5, clock=clock, sleep=clock.sleep)
    for _ in range(5):
        assert bucket.acquire() == 0.0
    assert clock.sleeps == []


def test_token_bucket_blocks_when_empty() -> None:
    """The 6th request when capacity=5 must sleep (1/rate seconds)."""
    clock = _FakeClock()
    bucket = TokenBucket(capacity=5, rate=5, clock=clock, sleep=clock.sleep)
    for _ in range(5):
        bucket.acquire()
    wait = bucket.acquire()
    # Slept ~0.2s for one token at rate 5/s.
    assert wait == pytest.approx(0.2)
    assert clock.sleeps == [pytest.approx(0.2)]


def test_token_bucket_refills_over_time() -> None:
    clock = _FakeClock()
    bucket = TokenBucket(capacity=5, rate=10, clock=clock, sleep=clock.sleep)
    for _ in range(5):
        bucket.acquire()
    # Drain done; advance clock 1 second → 10 tokens generated, capped at 5.
    clock.now += 1.0
    for _ in range(5):
        # All five within the new bucket should be free.
        assert bucket.acquire() == 0.0
    assert clock.sleeps == []


def test_token_bucket_does_not_overfill_past_capacity() -> None:
    """A long idle period doesn't accumulate more than ``capacity`` tokens."""
    clock = _FakeClock()
    bucket = TokenBucket(capacity=3, rate=10, clock=clock, sleep=clock.sleep)
    # Drain.
    for _ in range(3):
        bucket.acquire()
    # Idle for an hour — way more refill time than capacity holds.
    clock.now += 3600.0
    for _ in range(3):
        assert bucket.acquire() == 0.0
    # The 4th call must sleep (capped at 3).
    wait = bucket.acquire()
    assert wait > 0.0


# ---- DailyCounter ------------------------------------------------------


class _FakeDayClock:
    def __init__(self, *, year: int = 2026, month: int = 4, day: int = 27) -> None:
        self._dt = datetime(year, month, day, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self._dt

    def advance_to(self, *, year: int, month: int, day: int) -> None:
        self._dt = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)


def test_daily_counter_allows_up_to_cap() -> None:
    clock = _FakeDayClock()
    c = DailyCounter(daily_cap=3, clock=clock)
    for _ in range(3):
        c.acquire(Tier.HEAVY)


def test_daily_counter_raises_at_cap() -> None:
    clock = _FakeDayClock()
    c = DailyCounter(daily_cap=3, clock=clock)
    for _ in range(3):
        c.acquire(Tier.HEAVY)
    with pytest.raises(DailyCapExhaustedError) as excinfo:
        c.acquire(Tier.HEAVY)
    assert excinfo.value.tier == Tier.HEAVY
    assert excinfo.value.cap == 3
    assert "UTC midnight" in str(excinfo.value)


def test_daily_counter_resets_at_utc_midnight() -> None:
    clock = _FakeDayClock(year=2026, month=4, day=27)
    c = DailyCounter(daily_cap=2, clock=clock)
    c.acquire(Tier.HEAVY)
    c.acquire(Tier.HEAVY)
    # Roll over to next UTC day.
    clock.advance_to(year=2026, month=4, day=28)
    # Cap resets — two more allowed.
    c.acquire(Tier.HEAVY)
    c.acquire(Tier.HEAVY)


# ---- tier_for classification ------------------------------------------


@pytest.mark.parametrize(
    "method,path,expected",
    [
        # Light: single-resource reads.
        ("GET", "/users/me", Tier.LIGHT),
        ("GET", "/users/u-123", Tier.LIGHT),
        ("GET", "/users/u-123/settings", Tier.LIGHT),
        ("GET", "/meetings/12345", Tier.LIGHT),
        ("GET", "/meetings/12345/recordings", Tier.LIGHT),
        # Medium: listings + writes.
        ("GET", "/users", Tier.MEDIUM),
        ("GET", "/users/u-123/meetings", Tier.MEDIUM),
        ("GET", "/users/u-123/recordings", Tier.MEDIUM),
        ("PATCH", "/meetings/12345", Tier.MEDIUM),
        ("DELETE", "/meetings/12345", Tier.MEDIUM),
        ("DELETE", "/users/u-123", Tier.MEDIUM),
        ("DELETE", "/meetings/12345/recordings", Tier.MEDIUM),
        ("DELETE", "/meetings/12345/recordings/rec-abc", Tier.MEDIUM),
        ("PUT", "/meetings/12345/status", Tier.MEDIUM),
        # Heavy: creates.
        ("POST", "/users", Tier.HEAVY),
        ("POST", "/users/u-123/meetings", Tier.HEAVY),
        # Unknown endpoint → MEDIUM default.
        ("GET", "/some/unknown/path", Tier.MEDIUM),
        ("POST", "/another/endpoint", Tier.MEDIUM),
    ],
)
def test_tier_for_classifies_known_endpoints(method: str, path: str, expected: Tier) -> None:
    assert tier_for(method, path) == expected


def test_tier_for_strips_query_string() -> None:
    assert tier_for("GET", "/users/me?page_size=10") == Tier.LIGHT


def test_tier_for_strips_trailing_slash() -> None:
    assert tier_for("GET", "/users/me/") == Tier.LIGHT


def test_tier_for_is_method_sensitive() -> None:
    """GET /users vs POST /users land on different tiers."""
    assert tier_for("GET", "/users") == Tier.MEDIUM
    assert tier_for("POST", "/users") == Tier.HEAVY


# ---- RateLimiter integration ------------------------------------------


def test_rate_limiter_acquire_returns_tier() -> None:
    """``acquire`` returns the classified tier — useful for metrics/logging."""
    clock = _FakeClock()
    day_clock = _FakeDayClock()
    rl = RateLimiter(clock=clock, sleep=clock.sleep, day_clock=day_clock)
    assert rl.acquire("GET", "/users/me") == Tier.LIGHT
    assert rl.acquire("POST", "/users/u-1/meetings") == Tier.HEAVY


def test_rate_limiter_does_not_sleep_on_first_request() -> None:
    clock = _FakeClock()
    day_clock = _FakeDayClock()
    rl = RateLimiter(clock=clock, sleep=clock.sleep, day_clock=day_clock)
    rl.acquire("GET", "/users/me")
    assert clock.sleeps == []


def test_rate_limiter_blocks_after_per_sec_cap_exhausted() -> None:
    """Exhaust the LIGHT bucket (80) then the next acquire sleeps."""
    clock = _FakeClock()
    day_clock = _FakeDayClock()
    rl = RateLimiter(clock=clock, sleep=clock.sleep, day_clock=day_clock)
    for _ in range(80):
        rl.acquire("GET", "/users/me")
    rl.acquire("GET", "/users/me")
    assert len(clock.sleeps) == 1
    assert clock.sleeps[0] > 0.0


def test_rate_limiter_daily_cap_raises_on_heavy() -> None:
    """HEAVY has daily=60_000. Stub the daily cap by reaching into the
    counter directly; that's the cleanest deterministic test."""
    clock = _FakeClock()
    day_clock = _FakeDayClock()
    rl = RateLimiter(clock=clock, sleep=clock.sleep, day_clock=day_clock)
    # Pre-fill the heavy daily counter to one below the cap.
    rl._daily[Tier.HEAVY]._count = TIER_LIMITS[Tier.HEAVY].daily - 1
    rl.acquire("POST", "/users/u-1/meetings")  # last allowed
    with pytest.raises(DailyCapExhaustedError):
        rl.acquire("POST", "/users/u-1/meetings")


def test_rate_limiter_light_has_no_daily_cap() -> None:
    """LIGHT in TIER_LIMITS has daily=None — _daily must omit it."""
    rl = RateLimiter()
    assert Tier.LIGHT not in rl._daily
    assert Tier.MEDIUM not in rl._daily
    assert Tier.HEAVY in rl._daily
    assert Tier.RESOURCE_INTENSIVE in rl._daily


# ---- TIER_LIMITS pinned -----------------------------------------------


def test_tier_limits_match_zoom_published_caps() -> None:
    """Pinned by docs: a future bump should be a deliberate, reviewed change.
    Reference: https://developers.zoom.us/docs/api/rate-limits/"""
    assert TIER_LIMITS[Tier.LIGHT].per_sec == 80
    assert TIER_LIMITS[Tier.LIGHT].daily is None
    assert TIER_LIMITS[Tier.MEDIUM].per_sec == 60
    assert TIER_LIMITS[Tier.MEDIUM].daily is None
    assert TIER_LIMITS[Tier.HEAVY].per_sec == 40
    assert TIER_LIMITS[Tier.HEAVY].daily == 60_000
    assert TIER_LIMITS[Tier.RESOURCE_INTENSIVE].per_sec == 20
    assert TIER_LIMITS[Tier.RESOURCE_INTENSIVE].daily == 60_000
