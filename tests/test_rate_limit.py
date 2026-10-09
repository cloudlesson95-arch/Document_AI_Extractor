import pytest

from backend.utils.rate_limit import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_rate_limiter_allows_max_calls_per_window():
    """Verify calls over the limit are refused with the wait time, and slots free up as the window slides."""
    clock = FakeClock()
    limiter = RateLimiter(max_calls=2, window_seconds=60, clock=clock)

    assert limiter.acquire() == 0.0
    assert limiter.acquire() == 0.0
    assert limiter.acquire() == pytest.approx(60)
    clock.now = 30
    assert limiter.acquire() == pytest.approx(30)
    clock.now = 60
    assert limiter.acquire() == 0.0
