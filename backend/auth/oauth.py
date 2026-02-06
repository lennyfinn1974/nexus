"""Google OAuth 2.0 — authorization code flow with CSRF state protection."""
from __future__ import annotations

import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("nexus.auth.oauth")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


class OAuthManager:
    """Server-side Google OAuth 2.0 authorization code flow."""

    def __init__(self, cfg):
        self._cfg = cfg
        # State store: {state_hash: (expire_ts, used)}
        self._states: dict[str, tuple[float, bool]] = {}

    def _client_id(self):
        return self._cfg.google_client_id

    def _client_secret(self):
        return self._cfg.google_client_secret

    # ── Authorization URL ────────────────────────────────────────

    def get_authorization_url(self, redirect_uri: str) -> tuple[str, str]:
        """Return (url, state). Caller must pass state to the callback for CSRF check."""
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        self._states[state_hash] = (time.time() + 600, False)  # 10 min TTL
        self._cleanup_states()

        params = {
            "client_id": self._client_id(),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}", state

    def _verify_state(self, state: str) -> bool:
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        entry = self._states.get(state_hash)
        if not entry:
            return False
        expire_ts, used = entry
        if used or time.time() > expire_ts:
            del self._states[state_hash]
            return False
        # Mark as used (one-time)
        self._states[state_hash] = (expire_ts, True)
        return True

    def _cleanup_states(self):
        now = time.time()
        expired = [k for k, (exp, _) in self._states.items() if now > exp]
        for k in expired:
            del self._states[k]

    # ── Code Exchange ────────────────────────────────────────────

    async def exchange_code(self, code: str, state: str, redirect_uri: str) -> dict | None:
        """Exchange authorization code for user info.

        Returns dict with email, name, picture — or None on failure.
        """
        if not self._verify_state(state):
            logger.warning("OAuth state verification failed")
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Exchange code for tokens
                token_resp = await client.post(GOOGLE_TOKEN_URL, data={
                    "client_id": self._client_id(),
                    "client_secret": self._client_secret(),
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                })
                if token_resp.status_code != 200:
                    logger.error(f"Token exchange failed: {token_resp.status_code} {token_resp.text}")
                    return None

                tokens = token_resp.json()
                access_token = tokens.get("access_token")
                if not access_token:
                    logger.error("No access_token in Google response")
                    return None

                # Fetch user info
                userinfo_resp = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if userinfo_resp.status_code != 200:
                    logger.error(f"Userinfo fetch failed: {userinfo_resp.status_code}")
                    return None

                info = userinfo_resp.json()
                return {
                    "email": info.get("email", ""),
                    "name": info.get("name", ""),
                    "picture": info.get("picture", ""),
                }

        except httpx.HTTPError as e:
            logger.error(f"OAuth HTTP error: {e}")
            return None
