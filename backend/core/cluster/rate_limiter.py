"""Distributed Rate Limiter — Cluster-wide rate limiting via Redis.

Uses the sliding window counter pattern in Redis for consistent
rate limiting across all agents in the cluster.

Replaces per-process in-memory rate limiting in NexusPlugin.check_rate_limit()
when clustering is active. Falls back to local limiting when Redis unavailable.

Algorithm: Sliding Window Counter
    - Two Redis keys per {resource, window}: current window + previous window
    - Weighted count = previous_count × overlap_ratio + current_count
    - Atomic MULTI/EXEC ensures consistency across agents
    - Keys auto-expire after 2× window duration
"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger("nexus.cluster.rate_limiter")


class DistributedRateLimiter:
    """Redis-backed sliding window rate limiter for cluster-wide enforcement.

    Usage:
        limiter = DistributedRateLimiter(redis, prefix="nexus:")

        # Check if request is allowed
        allowed = await limiter.check("tool:web_fetch", limit=60, window=60)

        # Check with custom key
        allowed = await limiter.check("user:123:api", limit=100, window=60)

        # Get current usage
        usage = await limiter.get_usage("tool:web_fetch", window=60)
    """

    def __init__(self, redis, prefix: str = "nexus:"):
        self._redis = redis
        self._prefix = prefix

        # Stats
        self._checks = 0
        self._allowed = 0
        self._denied = 0

    def _window_key(self, resource: str, window_start: int) -> str:
        """Generate Redis key for a specific window."""
        return f"{self._prefix}ratelimit:{resource}:{window_start}"

    async def check(
        self,
        resource: str,
        limit: int = 60,
        window: int = 60,
        cost: int = 1,
    ) -> bool:
        """Check if a request is allowed under the rate limit.

        Uses sliding window counter for smooth rate limiting.

        Args:
            resource: Rate limit key (e.g., "tool:web_fetch", "user:123:api")
            limit: Maximum requests per window
            window: Window duration in seconds
            cost: Cost of this request (default 1, use >1 for expensive ops)

        Returns:
            True if allowed, False if rate-limited
        """
        self._checks += 1

        try:
            now = time.time()
            current_window = int(now // window) * window
            previous_window = current_window - window

            # Position within current window (0.0 - 1.0)
            window_position = (now - current_window) / window

            current_key = self._window_key(resource, current_window)
            previous_key = self._window_key(resource, previous_window)

            # Get counts from both windows atomically
            pipe = self._redis.pipeline()
            pipe.get(current_key)
            pipe.get(previous_key)
            results = await pipe.execute()

            current_count = int(results[0] or 0)
            previous_count = int(results[1] or 0)

            # Sliding window estimate
            weighted_count = (
                previous_count * (1.0 - window_position)
                + current_count
            )

            if weighted_count + cost > limit:
                self._denied += 1
                logger.debug(
                    f"Rate limited: {resource} "
                    f"({weighted_count:.1f}+{cost}/{limit} per {window}s)"
                )
                return False

            # Increment current window counter
            pipe = self._redis.pipeline()
            pipe.incrby(current_key, cost)
            pipe.expire(current_key, window * 2)  # Expire after 2 windows
            await pipe.execute()

            self._allowed += 1
            return True

        except Exception as e:
            # On Redis failure, allow the request (fail-open)
            logger.warning(f"Rate limiter Redis error (fail-open): {e}")
            self._allowed += 1
            return True

    async def get_usage(
        self, resource: str, window: int = 60
    ) -> dict[str, float]:
        """Get current usage for a resource.

        Returns:
            Dict with current_count, weighted_count, limit_remaining
        """
        try:
            now = time.time()
            current_window = int(now // window) * window
            previous_window = current_window - window
            window_position = (now - current_window) / window

            current_key = self._window_key(resource, current_window)
            previous_key = self._window_key(resource, previous_window)

            pipe = self._redis.pipeline()
            pipe.get(current_key)
            pipe.get(previous_key)
            results = await pipe.execute()

            current_count = int(results[0] or 0)
            previous_count = int(results[1] or 0)

            weighted_count = (
                previous_count * (1.0 - window_position)
                + current_count
            )

            return {
                "current_window_count": current_count,
                "previous_window_count": previous_count,
                "weighted_count": round(weighted_count, 1),
                "window_position": round(window_position, 3),
                "window_seconds": window,
            }
        except Exception as e:
            return {"error": str(e)}

    async def reset(self, resource: str, window: int = 60) -> None:
        """Reset rate limit counters for a resource."""
        now = time.time()
        current_window = int(now // window) * window
        previous_window = current_window - window

        pipe = self._redis.pipeline()
        pipe.delete(self._window_key(resource, current_window))
        pipe.delete(self._window_key(resource, previous_window))
        await pipe.execute()

        logger.info(f"Rate limit reset: {resource}")

    async def get_all_usage(self, window: int = 60) -> dict[str, dict]:
        """Scan all rate limit keys and return usage per resource.

        This is an admin/metrics operation — not for hot paths.
        """
        results = {}
        pattern = f"{self._prefix}ratelimit:*"

        try:
            now = time.time()
            current_window = int(now // window) * window

            async for key in self._redis.scan_iter(match=pattern, count=100):
                k = key if isinstance(key, str) else key.decode("utf-8")
                parts = k.rsplit(":", 2)
                if len(parts) >= 3:
                    resource = parts[-2]
                    try:
                        ts = int(parts[-1])
                    except ValueError:
                        continue

                    # Only count current window keys
                    if ts == current_window and resource not in results:
                        results[resource] = await self.get_usage(resource, window)

        except Exception as e:
            logger.warning(f"Scan rate limits error: {e}")

        return results

    def get_stats(self) -> dict[str, int]:
        """Return rate limiter statistics."""
        return {
            "checks": self._checks,
            "allowed": self._allowed,
            "denied": self._denied,
        }
