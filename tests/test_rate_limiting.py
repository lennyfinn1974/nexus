"""Tests for rate limiting middleware."""

import time

import pytest


class TestRateLimiter:
    """Unit tests for the RateLimiter class."""

    def test_allows_requests_under_limit(self):
        from middleware.rate_limit import RateLimiter

        limiter = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            allowed, remaining = limiter.is_allowed("test-ip")
            assert allowed is True

    def test_blocks_after_limit(self):
        from middleware.rate_limit import RateLimiter

        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            limiter.is_allowed("test-ip")
        allowed, remaining = limiter.is_allowed("test-ip")
        assert allowed is False
        assert remaining == 0

    def test_different_keys_independent(self):
        from middleware.rate_limit import RateLimiter

        limiter = RateLimiter(max_requests=2, window_seconds=60)
        limiter.is_allowed("ip-1")
        limiter.is_allowed("ip-1")
        # ip-1 is now at limit
        allowed_1, _ = limiter.is_allowed("ip-1")
        assert allowed_1 is False
        # ip-2 should still be allowed
        allowed_2, _ = limiter.is_allowed("ip-2")
        assert allowed_2 is True

    def test_remaining_count(self):
        from middleware.rate_limit import RateLimiter

        limiter = RateLimiter(max_requests=5, window_seconds=60)
        _, remaining = limiter.is_allowed("test-ip")
        assert remaining == 4

    def test_window_expiry(self):
        """Entries should expire after the window."""
        from middleware.rate_limit import RateLimiter

        limiter = RateLimiter(max_requests=1, window_seconds=1)
        limiter.is_allowed("test-ip")
        allowed, _ = limiter.is_allowed("test-ip")
        assert allowed is False
        # Wait for window to expire
        time.sleep(1.1)
        allowed, _ = limiter.is_allowed("test-ip")
        assert allowed is True


class TestRateLimitMiddleware:
    """Integration tests for rate limiting via HTTP."""

    @pytest.mark.slow
    async def test_rate_limit_header_present(self, client):
        resp = await client.get("/api/status")
        assert "x-ratelimit-remaining" in resp.headers

    async def test_non_api_routes_not_rate_limited(self, client):
        """Non-/api/ routes should bypass rate limiting."""
        for _ in range(5):
            resp = await client.get("/")
            assert resp.status_code == 200
