import time
from collections import defaultdict


class BruteForceManager:
    """In-memory brute force protection tracker.

    Tracks failed authentication attempts by IP address and username.
    When the failure threshold is exceeded within the configured window,
    the source is blocked for the configured duration.
    """

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._blocks: dict[str, float] = {}

    def _cleanup(self, key: str) -> None:
        now = time.time()
        if key in self._failures:
            self._failures[key] = [t for t in self._failures[key] if now - t < 3600]
            if not self._failures[key]:
                del self._failures[key]

    def is_blocked(self, key: str) -> bool:
        now = time.time()
        if key in self._blocks:
            if now < self._blocks[key]:
                return True
            del self._blocks[key]
        return False

    def record_failure(self, key: str, window_seconds: int, max_failures: int, block_seconds: int) -> None:
        now = time.time()
        cutoff = now - window_seconds
        self._failures[key] = [t for t in self._failures[key] if t > cutoff]
        self._failures[key].append(now)

        if len(self._failures[key]) >= max_failures:
            self._blocks[key] = now + block_seconds
            self._failures[key] = []

    def record_success(self, key: str) -> None:
        if key in self._failures:
            del self._failures[key]
        if key in self._blocks:
            del self._blocks[key]

    def clear(self) -> None:
        self._failures.clear()
        self._blocks.clear()


_brute_force_manager: BruteForceManager | None = None


def get_brute_force_manager() -> BruteForceManager:
    global _brute_force_manager
    if _brute_force_manager is None:
        _brute_force_manager = BruteForceManager()
    return _brute_force_manager
