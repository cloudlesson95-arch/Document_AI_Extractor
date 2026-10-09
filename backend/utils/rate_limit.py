import threading
import time
from collections import deque


class RateLimiter:
    """At most max_calls per window_seconds for the whole process, shared by all clients."""

    def __init__(self, max_calls: int, window_seconds: float = 60.0, clock=time.monotonic):
        self._max_calls = max_calls
        self._window_seconds = window_seconds
        self._clock = clock
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Record a call if one is allowed.

        Returns:
            float: 0.0 if the call is allowed, otherwise seconds until a slot frees up.
        """
        with self._lock:
            now = self._clock()
            while self._calls and self._calls[0] <= now - self._window_seconds:
                self._calls.popleft()
            if len(self._calls) < self._max_calls:
                self._calls.append(now)
                return 0.0
            return self._calls[0] + self._window_seconds - now
