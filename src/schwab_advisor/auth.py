"""OAuth 2.0 authentication for Schwab Advisor API."""

import base64
import json
import os
import threading
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import httpx

from .models import TokenResponse

OAUTH_AUTHORIZE_URLS = {
    "sandbox": "https://sandbox.schwabapi.com/v1/oauth/authorize",
    "production": "https://api.schwabapi.com/v1/oauth/authorize",
}
OAUTH_TOKEN_URLS = {
    "sandbox": "https://sandbox.schwabapi.com/v1/oauth/token",
    "production": "https://api.schwabapi.com/v1/oauth/token",
}


class SchwabAuth:
    """Handle OAuth 2.0 authentication for Schwab API."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_file: str | Path | None = None,
        environment: Literal["sandbox", "production"] = "sandbox",
    ):
        """Initialize authentication handler.

        Args:
            client_id: OAuth client ID from Schwab Developer Portal.
            client_secret: OAuth client secret from Schwab Developer Portal.
            redirect_uri: Registered redirect URI for OAuth callback.
            token_file: Optional path to file for persisting tokens.
            environment: API environment, "sandbox" or "production".
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_file = Path(token_file).expanduser() if token_file else None
        self.environment = environment
        self._tokens: TokenResponse | None = None
        # Serializes load/expiry-check/refresh so concurrent callers can't
        # double-refresh (Schwab may rotate refresh tokens; the losing
        # refresh would persist an already-invalidated pair).
        self._refresh_lock = threading.Lock()

    @property
    def authorize_url(self) -> str:
        """Get the OAuth authorize URL for current environment."""
        return OAUTH_AUTHORIZE_URLS[self.environment]

    @property
    def token_url(self) -> str:
        """Get the OAuth token URL for current environment."""
        return OAUTH_TOKEN_URLS[self.environment]

    @classmethod
    def from_env(cls) -> "SchwabAuth":
        """Create SchwabAuth from environment variables.

        Environment variables:
            SCHWAB_CLIENT_ID: OAuth client ID
            SCHWAB_CLIENT_SECRET: OAuth client secret
            SCHWAB_REDIRECT_URI: Redirect URI (default: https://127.0.0.1)
            SCHWAB_TOKEN_FILE: Token file path (default: ~/.schwab_tokens.json)
            SCHWAB_ENVIRONMENT: "sandbox" or "production" (default: sandbox)
        """
        client_id = os.environ.get("SCHWAB_CLIENT_ID", "")
        client_secret = os.environ.get("SCHWAB_CLIENT_SECRET", "")
        environment = os.environ.get("SCHWAB_ENVIRONMENT", "sandbox")
        if environment not in ("sandbox", "production"):
            raise ValueError(
                "SCHWAB_ENVIRONMENT must be 'sandbox' or 'production', "
                f"got {environment}"
            )
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1"),
            token_file=os.environ.get("SCHWAB_TOKEN_FILE", "~/.schwab_tokens.json"),
            environment=environment,
        )

    def get_authorization_url(self, state: str | None = None) -> str:
        """Generate the authorization URL for user to visit.

        Args:
            state: Optional opaque value Schwab will echo back as `state=...`
                on the callback redirect. Useful for multi-tenant brokers
                that need to know which app/tenant a callback belongs to.

        Returns:
            URL to redirect user to for Schwab login and consent.
        """
        # Schwab only uses client_id and redirect_uri (no scope or response_type)
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
        }
        if state is not None:
            params["state"] = state
        return f"{self.authorize_url}?{urllib.parse.urlencode(params)}"

    def _get_basic_auth_header(self) -> str:
        """Generate Basic auth header value."""
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET are required "
                "for token exchange/refresh"
            )
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    def _token_request(self, data: dict) -> TokenResponse:
        """POST to the token endpoint, parse, store, and persist tokens.

        The sandbox token endpoint routinely takes 8-10s to answer a
        refresh grant (measured 2026-07-15), so httpx's 5s default
        timeout turns every expired-token call into a ReadTimeout.
        """
        headers = {
            "Authorization": self._get_basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        response = httpx.post(self.token_url, headers=headers, data=data, timeout=30.0)
        response.raise_for_status()

        tokens = self._parse_token_response(response.json())
        self._tokens = tokens

        if self.token_file:
            self.save_tokens(tokens)

        return tokens

    def exchange_code(self, authorization_code: str) -> TokenResponse:
        """Exchange authorization code for access and refresh tokens."""
        return self._token_request({
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": self.redirect_uri,
        })

    def refresh_tokens(self, refresh_token: str | None = None) -> TokenResponse:
        """Refresh the access token using the refresh token."""
        if refresh_token is None:
            if self._tokens is None:
                self._tokens = self.load_tokens()
            if self._tokens is None:
                raise ValueError("No refresh token available")
            refresh_token = self._tokens.refresh_token

        return self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })

    def _parse_token_response(self, data: dict) -> TokenResponse:
        """Parse token response from API."""
        expires_in = data.get("expires_in", 1800)
        expires_at = datetime.now() + timedelta(seconds=expires_in)

        # RFC 6749 allows a refresh-grant response to omit refresh_token
        # (meaning "keep using your current one") — fall back to it rather
        # than discarding a successful grant.
        refresh_token = data.get("refresh_token")
        if not refresh_token and self._tokens is not None:
            refresh_token = self._tokens.refresh_token
        if not refresh_token:
            raise KeyError("refresh_token")

        return TokenResponse(
            access_token=data["access_token"],
            refresh_token=refresh_token,
            token_type=data.get("token_type", "Bearer"),
            expires_in=expires_in,
            scope=data.get("scope", ""),
            expires_at=expires_at,
        )

    def load_tokens(self) -> TokenResponse | None:
        """Load tokens from file.

        Returns:
            TokenResponse if file exists and is valid, None otherwise.
        """
        if self.token_file is None:
            return None

        try:
            with open(self.token_file) as f:
                data = json.load(f)
            self._tokens = TokenResponse.from_dict(data)
            return self._tokens
        except (OSError, ValueError, TypeError, KeyError):
            # Unreadable path, corrupt/truncated JSON, a hand-edited
            # expires_at, or a non-object body ("null") all mean the same
            # thing to callers: no usable persisted tokens.
            return None

    def save_tokens(self, tokens: TokenResponse) -> None:
        """Save tokens to file with restricted permissions.

        Args:
            tokens: TokenResponse to persist.
        """
        if self.token_file is None:
            return

        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically (temp file + rename) so a crash mid-write can't
        # truncate the only copy of the refresh token, and create with
        # owner-only permissions from the start rather than chmod-ing after
        # the secret is already on disk.
        tmp_path = self.token_file.with_name(self.token_file.name + ".tmp")
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(tokens.to_dict(), f, indent=2)
            os.replace(tmp_path, self.token_file)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        self.token_file.chmod(0o600)

    def get_access_token(self, auto_refresh: bool = True) -> str:
        """Get a valid access token, refreshing if needed.

        Args:
            auto_refresh: If True, automatically refresh expired tokens.

        Returns:
            Valid access token string.

        Raises:
            ValueError: If no valid token is available.
        """
        with self._refresh_lock:
            if self._tokens is None:
                self._tokens = self.load_tokens()

            if self._tokens is None:
                raise ValueError(
                    "No tokens available. Run schwab-auth to authenticate first."
                )

            if self._tokens.is_expired() and auto_refresh:
                self.refresh_tokens()

            return self._tokens.access_token

    @property
    def tokens(self) -> TokenResponse | None:
        """Get current tokens, loading from file if needed."""
        if self._tokens is None:
            self._tokens = self.load_tokens()
        return self._tokens
