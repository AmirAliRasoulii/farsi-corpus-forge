"""
Thread-safe rate limiter and API call budget controller.
Supports requests per minute (RPM) throttling and strict MAX_API_CALLS limits.
"""
import time
import threading
from typing import Optional


class BudgetExceededError(Exception):
    """Raised when MAX_API_CALLS limit has been reached for the run."""
    pass


class RateLimiter:
    """
    Thread-safe rate limiter and invocation budget tracker.
    """
    def __init__(self, rpm: int = 0, max_calls: int = 0):
        self.rpm = rpm
        self.max_calls = max_calls
        self.call_count = 0
        self._lock = threading.Lock()
        self._timestamps = []

    def acquire(self) -> None:
        """
        Blocks if rate limit would be exceeded.
        Raises BudgetExceededError if max_calls budget has been reached.
        """
        with self._lock:
            # Check total calls budget
            if self.max_calls > 0 and self.call_count >= self.max_calls:
                raise BudgetExceededError(
                    f"MAX_API_CALLS limit ({self.max_calls}) reached. Stopping cleanly to preserve budget."
                )

            # Enforce RPM if configured
            if self.rpm > 0:
                now = time.monotonic()
                # Prune timestamps older than 60 seconds
                self._timestamps = [t for t in self._timestamps if now - t < 60.0]
                
                while len(self._timestamps) >= self.rpm:
                    sleep_time = 60.0 - (now - self._timestamps[0]) + 0.05
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    now = time.monotonic()
                    self._timestamps = [t for t in self._timestamps if now - t < 60.0]

                self._timestamps.append(time.monotonic())

            self.call_count += 1

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "total_api_calls_made": self.call_count,
                "max_calls_budget": self.max_calls,
                "rpm_limit": self.rpm
            }
