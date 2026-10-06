"""
Thread-safe Circuit Breaker for monitoring error rates and halting execution.
Detects spikes in technical errors, model refusals, or quality failures,
allowing in-flight requests to complete while halting new scheduling.
"""
import threading
from typing import Dict, Any, List


class CircuitBreakerTripped(Exception):
    """Raised when error/failure threshold is exceeded and circuit breaker trips."""
    pass


class PipelineCircuitBreaker:
    """
    Monitors operations and trips if failure rate exceeds threshold over a minimum observation window.
    """
    def __init__(
        self,
        max_failure_rate: float = 0.50,
        min_observations: int = 10,
        enabled: bool = True
    ):
        self.max_failure_rate = max_failure_rate
        self.min_observations = min_observations
        self.enabled = enabled
        self.is_tripped = False
        self.trip_reason = ""
        self._lock = threading.Lock()
        
        self.total_observations = 0
        self.technical_errors = 0
        self.model_refusals = 0
        self.quality_failures = 0

    def record_result(
        self,
        is_tech_error: bool = False,
        is_refusal: bool = False,
        is_quality_failure: bool = False
    ) -> None:
        """Records the outcome of a processed record/step."""
        if not self.enabled:
            return

        with self._lock:
            self.total_observations += 1
            if is_tech_error:
                self.technical_errors += 1
            if is_refusal:
                self.model_refusals += 1
            if is_quality_failure:
                self.quality_failures += 1

            total_failures = self.technical_errors + self.model_refusals + self.quality_failures
            if self.total_observations >= self.min_observations:
                failure_rate = total_failures / self.total_observations
                if failure_rate >= self.max_failure_rate:
                    self.is_tripped = True
                    self.trip_reason = (
                        f"CIRCUIT BREAKER TRIPPED: Failure rate {failure_rate:.1%} "
                        f"exceeded threshold {self.max_failure_rate:.1%} "
                        f"({total_failures}/{self.total_observations} failures: "
                        f"{self.technical_errors} tech errors, {self.model_refusals} refusals, "
                        f"{self.quality_failures} quality failures)."
                    )

    def check_healthy(self) -> None:
        """Raises CircuitBreakerTripped if circuit breaker is tripped."""
        with self._lock:
            if self.is_tripped:
                raise CircuitBreakerTripped(self.trip_reason)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "is_tripped": self.is_tripped,
                "trip_reason": self.trip_reason,
                "total_observations": self.total_observations,
                "technical_errors": self.technical_errors,
                "model_refusals": self.model_refusals,
                "quality_failures": self.quality_failures,
                "failure_rate": (
                    (self.technical_errors + self.model_refusals + self.quality_failures) / self.total_observations
                    if self.total_observations > 0 else 0.0
                )
            }
