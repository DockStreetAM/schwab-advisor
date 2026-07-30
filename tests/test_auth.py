"""Tests for Schwab OAuth authentication."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from schwab_advisor.auth import OAUTH_AUTHORIZE_URLS, OAUTH_TOKEN_URLS, SchwabAuth
from schwab_advisor.models import TokenResponse


class TestSchwabAuth:
    """Tests for SchwabAuth class."""

    def test_init(self):
        """Test basic initialization."""
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
        )
        assert auth.client_id == "test_id"
        assert auth.client_secret == "test_secret"
        assert auth.redirect_uri == "https://127.0.0.1"
        assert auth.token_file is None
        assert auth.environment == "sandbox"

    def test_init_with_token_file(self):
        """Test initialization with token file path."""
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
            token_file="~/.schwab_tokens.json",
        )
        assert auth.token_file == Path.home() / ".schwab_tokens.json"

    def test_init_with_environment(self):
        """Test initialization with production environment."""
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
            environment="production",
        )
        assert auth.environment == "production"
        assert auth.authorize_url == OAUTH_AUTHORIZE_URLS["production"]
        assert auth.token_url == OAUTH_TOKEN_URLS["production"]

    def test_sandbox_uses_sandbox_oauth_urls(self):
        """Test sandbox environment uses sandbox OAuth URLs."""
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
            environment="sandbox",
        )
        assert "sandbox.schwabapi.com" in auth.authorize_url
        assert "sandbox.schwabapi.com" in auth.token_url

    def test_from_env_missing_vars(self):
        """Test from_env works with missing client ID/secret (defaults to empty)."""
        with patch.dict("os.environ", {}, clear=True):
            auth = SchwabAuth.from_env()
            assert auth.client_id == ""
            assert auth.client_secret == ""

    def test_empty_credentials_raises_on_refresh(self):
        """Empty credentials raise clear error when token refresh is attempted."""
        auth = SchwabAuth(
            client_id="", client_secret="", redirect_uri="https://example.com"
        )
        with pytest.raises(ValueError, match="SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET"):
            auth._get_basic_auth_header()

    def test_from_env_success(self):
        """Test from_env with all vars set."""
        env = {
            "SCHWAB_CLIENT_ID": "env_client_id",
            "SCHWAB_CLIENT_SECRET": "env_client_secret",
            "SCHWAB_REDIRECT_URI": "https://callback.example.com",
            "SCHWAB_TOKEN_FILE": "/tmp/tokens.json",
            "SCHWAB_ENVIRONMENT": "production",
        }
        with patch.dict("os.environ", env, clear=True):
            auth = SchwabAuth.from_env()
            assert auth.client_id == "env_client_id"
            assert auth.client_secret == "env_client_secret"
            assert auth.redirect_uri == "https://callback.example.com"
            assert auth.token_file == Path("/tmp/tokens.json")
            assert auth.environment == "production"

    def test_from_env_defaults(self):
        """Test from_env uses defaults for optional vars."""
        env = {
            "SCHWAB_CLIENT_ID": "test_id",
            "SCHWAB_CLIENT_SECRET": "test_secret",
        }
        with patch.dict("os.environ", env, clear=True):
            auth = SchwabAuth.from_env()
            assert auth.redirect_uri == "https://127.0.0.1"
            assert auth.token_file == Path.home() / ".schwab_tokens.json"
            assert auth.environment == "sandbox"


class TestAuthorizationUrl:
    """Tests for authorization URL generation."""

    def test_get_authorization_url(self):
        """Test authorization URL is correctly formatted."""
        auth = SchwabAuth(
            client_id="my_client_id",
            client_secret="my_secret",
            redirect_uri="https://127.0.0.1",
        )
        url = auth.get_authorization_url()

        # Default sandbox environment uses sandbox URL
        assert url.startswith(OAUTH_AUTHORIZE_URLS["sandbox"])
        assert "client_id=my_client_id" in url
        assert "redirect_uri=https%3A%2F%2F127.0.0.1" in url
        # Schwab doesn't use response_type or scope in authorize URL
        assert "response_type" not in url
        assert "scope" not in url

    def test_get_authorization_url_encodes_redirect(self):
        """Test redirect URI with port is properly encoded."""
        auth = SchwabAuth(
            client_id="test",
            client_secret="secret",
            redirect_uri="https://127.0.0.1:8443/callback",
        )
        url = auth.get_authorization_url()
        assert "redirect_uri=https%3A%2F%2F127.0.0.1%3A8443%2Fcallback" in url


class TestBasicAuth:
    """Tests for Basic authentication header."""

    def test_basic_auth_header(self):
        """Test Basic auth header is correctly encoded."""
        auth = SchwabAuth(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
        )
        header = auth._get_basic_auth_header()

        # "test_client:test_secret" base64 encoded
        import base64

        expected = base64.b64encode(b"test_client:test_secret").decode()
        assert header == f"Basic {expected}"


class TestTokenExchange:
    """Tests for token exchange."""

    def test_exchange_code_success(self):
        """Test successful code exchange."""
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "token_type": "Bearer",
            "expires_in": 1800,
            "scope": "api",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_response) as mock_post:
            tokens = auth.exchange_code("auth_code_123")

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == auth.token_url
            assert call_args.kwargs["data"]["grant_type"] == "authorization_code"
            assert call_args.kwargs["data"]["code"] == "auth_code_123"

            assert tokens.access_token == "new_access_token"
            assert tokens.refresh_token == "new_refresh_token"
            assert tokens.token_type == "Bearer"
            assert tokens.expires_in == 1800

    def test_refresh_tokens_success(self):
        """Test successful token refresh."""
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "refreshed_access",
            "refresh_token": "refreshed_refresh",
            "token_type": "Bearer",
            "expires_in": 1800,
            "scope": "api",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_response) as mock_post:
            tokens = auth.refresh_tokens("old_refresh_token")

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == auth.token_url
            assert call_args.kwargs["data"]["grant_type"] == "refresh_token"

            assert tokens.access_token == "refreshed_access"

    def test_token_request_sends_explicit_timeout(self):
        """Gap E: the sandbox token endpoint takes 8-10s to answer a refresh
        grant; httpx's 5s default turned every expired-token call into a
        ReadTimeout. The token POST must carry an explicit generous timeout."""
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "a", "refresh_token": "r",
            "token_type": "Bearer", "expires_in": 1800, "scope": "api",
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response) as mock_post:
            auth.refresh_tokens("old_refresh_token")
            timeout = mock_post.call_args.kwargs.get("timeout")
            assert timeout is not None and timeout >= 10.0


class TestTokenPersistence:
    """Tests for token save/load."""

    def test_save_and_load_tokens(self):
        """Test tokens can be saved and loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "tokens.json"
            auth = SchwabAuth(
                client_id="test_id",
                client_secret="test_secret",
                redirect_uri="https://127.0.0.1",
                token_file=str(token_file),
            )

            tokens = TokenResponse(
                access_token="saved_access",
                refresh_token="saved_refresh",
                token_type="Bearer",
                expires_in=1800,
                scope="api",
                expires_at=datetime.now() + timedelta(seconds=1800),
            )

            auth.save_tokens(tokens)
            assert token_file.exists()

            # Check file permissions (Unix only)
            mode = token_file.stat().st_mode
            assert mode & 0o777 == 0o600

            # Load tokens
            loaded = auth.load_tokens()
            assert loaded is not None
            assert loaded.access_token == "saved_access"
            assert loaded.refresh_token == "saved_refresh"

    def test_load_tokens_file_not_found(self):
        """Test load_tokens returns None when file missing."""
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
            token_file="/nonexistent/path/tokens.json",
        )
        assert auth.load_tokens() is None

    def test_load_tokens_no_file_configured(self):
        """Test load_tokens returns None when no file configured."""
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
        )
        assert auth.load_tokens() is None


class TestGetAccessToken:
    """Tests for get_access_token method."""

    def test_get_access_token_no_tokens(self):
        """Test error when no tokens available."""
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
        )
        with pytest.raises(ValueError, match="No tokens available"):
            auth.get_access_token()

    def test_get_access_token_valid(self):
        """Test returns token when valid."""
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
        )
        auth._tokens = TokenResponse(
            access_token="valid_token",
            refresh_token="refresh",
            token_type="Bearer",
            expires_in=1800,
            scope="api",
            expires_at=datetime.now() + timedelta(seconds=1800),
        )

        assert auth.get_access_token() == "valid_token"

    def test_get_access_token_auto_refresh(self):
        """Test auto-refresh when token expired."""
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
        )
        auth._tokens = TokenResponse(
            access_token="expired_token",
            refresh_token="refresh",
            token_type="Bearer",
            expires_in=1800,
            scope="api",
            expires_at=datetime.now() - timedelta(seconds=100),  # Expired
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_token",
            "refresh_token": "new_refresh",
            "token_type": "Bearer",
            "expires_in": 1800,
            "scope": "api",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_response):
            token = auth.get_access_token(auto_refresh=True)
            assert token == "new_token"


class TestFromEnvValidation:
    """Tests for from_env environment validation."""

    def test_invalid_environment_raises(self):
        env = {
            "SCHWAB_CLIENT_ID": "id",
            "SCHWAB_CLIENT_SECRET": "secret",
            "SCHWAB_ENVIRONMENT": "staging",
        }
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ValueError, match="sandbox.*production"):
                SchwabAuth.from_env()


class TestRefreshTokensEdgeCases:
    """Tests for refresh_tokens error paths."""

    def test_refresh_no_token_available_raises(self):
        auth = SchwabAuth(
            client_id="id", client_secret="secret",
            redirect_uri="https://example.com",
        )
        with pytest.raises(ValueError, match="No refresh token available"):
            auth.refresh_tokens()

    def test_refresh_loads_from_file(self):
        """refresh_tokens loads stored token when no explicit token given."""
        auth = SchwabAuth(
            client_id="id", client_secret="secret",
            redirect_uri="https://example.com",
        )
        auth._tokens = TokenResponse(
            access_token="old", refresh_token="stored_refresh",
            token_type="Bearer", expires_in=1800, scope="api",
            expires_at=datetime.now() - timedelta(seconds=100),
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_access", "refresh_token": "new_refresh",
            "token_type": "Bearer", "expires_in": 1800, "scope": "api",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_response) as mock_post:
            tokens = auth.refresh_tokens()
            assert tokens.access_token == "new_access"
            call_data = mock_post.call_args.kwargs["data"]
            assert call_data["refresh_token"] == "stored_refresh"

    def test_exchange_code_saves_to_file(self):
        """exchange_code persists tokens when token_file is set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "tokens.json"
            auth = SchwabAuth(
                client_id="id", client_secret="secret",
                redirect_uri="https://example.com",
                token_file=str(token_file),
            )
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "saved", "refresh_token": "saved_refresh",
                "token_type": "Bearer", "expires_in": 1800, "scope": "api",
            }
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.post", return_value=mock_response):
                auth.exchange_code("code123")
            assert token_file.exists()


class TestLoadTokensEdgeCases:
    """Tests for token loading edge cases."""

    def test_load_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "tokens.json"
            token_file.write_text("not valid json{{{")
            auth = SchwabAuth(
                client_id="id", client_secret="secret",
                redirect_uri="https://example.com",
                token_file=str(token_file),
            )
            assert auth.load_tokens() is None

    def test_load_missing_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "tokens.json"
            token_file.write_text('{"access_token": "x"}')
            auth = SchwabAuth(
                client_id="id", client_secret="secret",
                redirect_uri="https://example.com",
                token_file=str(token_file),
            )
            assert auth.load_tokens() is None


class TestTokensProperty:
    """Tests for the tokens lazy-loading property."""

    def test_tokens_property_loads_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "tokens.json"
            auth = SchwabAuth(
                client_id="id", client_secret="secret",
                redirect_uri="https://example.com",
                token_file=str(token_file),
            )
            tokens = TokenResponse(
                access_token="prop_test", refresh_token="r",
                token_type="Bearer", expires_in=1800, scope="api",
                expires_at=datetime.now() + timedelta(seconds=1800),
            )
            auth.save_tokens(tokens)
            assert auth._tokens is None
            result = auth.tokens
            assert result is not None
            assert result.access_token == "prop_test"

    def test_tokens_property_returns_none_no_file(self):
        auth = SchwabAuth(
            client_id="id", client_secret="secret",
            redirect_uri="https://example.com",
        )
        assert auth.tokens is None

    def test_get_access_token_no_auto_refresh(self):
        """auto_refresh=False returns expired token without refreshing."""
        auth = SchwabAuth(
            client_id="id", client_secret="secret",
            redirect_uri="https://example.com",
        )
        auth._tokens = TokenResponse(
            access_token="expired_token", refresh_token="r",
            token_type="Bearer", expires_in=1800, scope="api",
            expires_at=datetime.now() - timedelta(seconds=100),
        )
        token = auth.get_access_token(auto_refresh=False)
        assert token == "expired_token"


class TestTokenResponse:
    """Tests for TokenResponse model."""

    def test_is_expired_false(self):
        """Test is_expired returns False for valid token."""
        token = TokenResponse(
            access_token="token",
            refresh_token="refresh",
            token_type="Bearer",
            expires_in=1800,
            scope="api",
            expires_at=datetime.now() + timedelta(seconds=1800),
        )
        assert token.is_expired() is False

    def test_is_expired_true(self):
        """Test is_expired returns True for expired token."""
        token = TokenResponse(
            access_token="token",
            refresh_token="refresh",
            token_type="Bearer",
            expires_in=1800,
            scope="api",
            expires_at=datetime.now() - timedelta(seconds=100),
        )
        assert token.is_expired() is True

    def test_to_dict_and_from_dict(self):
        """Test serialization round-trip."""
        expires_at = datetime.now() + timedelta(seconds=1800)
        token = TokenResponse(
            access_token="token",
            refresh_token="refresh",
            token_type="Bearer",
            expires_in=1800,
            scope="api",
            expires_at=expires_at,
        )

        data = token.to_dict()
        restored = TokenResponse.from_dict(data)

        assert restored.access_token == token.access_token
        assert restored.refresh_token == token.refresh_token
        assert restored.token_type == token.token_type
        assert restored.expires_in == token.expires_in
        assert restored.scope == token.scope
        # Datetime comparison (may have microsecond differences)
        assert abs((restored.expires_at - token.expires_at).total_seconds()) < 1


class TestTokenPersistenceRobustness:
    """Atomic writes, permissions, and corrupt-file tolerance."""

    def _auth(self, token_file):
        return SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
            token_file=token_file,
        )

    def _tokens(self):
        return TokenResponse(
            access_token="a",
            refresh_token="r",
            token_type="Bearer",
            expires_in=1800,
            scope="api",
            expires_at=datetime.now() + timedelta(minutes=30),
        )

    def test_save_creates_file_with_0600(self, tmp_path):
        token_file = tmp_path / "tokens.json"
        self._auth(token_file).save_tokens(self._tokens())
        assert (token_file.stat().st_mode & 0o777) == 0o600

    def test_save_leaves_no_temp_file(self, tmp_path):
        token_file = tmp_path / "tokens.json"
        self._auth(token_file).save_tokens(self._tokens())
        leftovers = [p.name for p in tmp_path.iterdir()]
        assert leftovers == ["tokens.json"]

    def test_save_is_atomic_on_write_failure(self, tmp_path):
        """A failure mid-write must not clobber the existing token file."""
        token_file = tmp_path / "tokens.json"
        auth = self._auth(token_file)
        auth.save_tokens(self._tokens())
        original = token_file.read_text()

        bad = self._tokens()
        bad.to_dict = MagicMock(side_effect=OSError("disk full"))
        with pytest.raises(OSError):
            auth.save_tokens(bad)
        assert token_file.read_text() == original
        assert list(tmp_path.iterdir()) == [token_file]

    def test_load_null_json_body_returns_none(self, tmp_path):
        token_file = tmp_path / "tokens.json"
        token_file.write_text("null")
        assert self._auth(token_file).load_tokens() is None

    def test_load_list_json_body_returns_none(self, tmp_path):
        token_file = tmp_path / "tokens.json"
        token_file.write_text("[]")
        assert self._auth(token_file).load_tokens() is None

    def test_load_corrupt_expires_at_returns_none(self, tmp_path):
        token_file = tmp_path / "tokens.json"
        token_file.write_text(
            '{"access_token": "a", "refresh_token": "r", "token_type": "B",'
            ' "expires_in": 1800, "scope": "api", "expires_at": ""}'
        )
        assert self._auth(token_file).load_tokens() is None

    def test_load_token_file_is_directory_returns_none(self, tmp_path):
        assert self._auth(tmp_path).load_tokens() is None


class TestRefreshTokenFallback:
    """RFC 6749: a refresh-grant response may omit refresh_token."""

    def _grant_response(self, body):
        mock_response = MagicMock()
        mock_response.json.return_value = body
        mock_response.raise_for_status = MagicMock()
        return mock_response

    def test_missing_refresh_token_keeps_current(self):
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
        )
        auth._tokens = TokenResponse(
            access_token="old_access",
            refresh_token="current_refresh",
            token_type="Bearer",
            expires_in=1800,
            scope="api",
            expires_at=datetime.now(),
        )
        body = {"access_token": "new_access", "expires_in": 1800}
        with patch("httpx.post", return_value=self._grant_response(body)):
            tokens = auth.refresh_tokens("current_refresh")
        assert tokens.access_token == "new_access"
        assert tokens.refresh_token == "current_refresh"

    def test_missing_refresh_token_with_no_cache_raises(self):
        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
        )
        body = {"access_token": "new_access", "expires_in": 1800}
        with patch("httpx.post", return_value=self._grant_response(body)):
            with pytest.raises(KeyError):
                auth.exchange_code("code")

    def test_failed_refresh_leaves_tokens_untouched(self):
        """A non-2xx token response must not clobber cached tokens."""
        import httpx as _httpx

        auth = SchwabAuth(
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="https://127.0.0.1",
        )
        original = TokenResponse(
            access_token="old_access",
            refresh_token="old_refresh",
            token_type="Bearer",
            expires_in=1800,
            scope="api",
            expires_at=datetime.now(),
        )
        auth._tokens = original
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = _httpx.HTTPStatusError(
            "401", request=MagicMock(), response=MagicMock()
        )
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(_httpx.HTTPStatusError):
                auth.refresh_tokens("old_refresh")
        assert auth._tokens is original


class TestExpiryMargin:
    """is_expired treats a nearly-expired token as expired."""

    def _tok(self, seconds_left):
        return TokenResponse(
            access_token="a",
            refresh_token="r",
            token_type="Bearer",
            expires_in=1800,
            scope="api",
            expires_at=datetime.now() + timedelta(seconds=seconds_left),
        )

    def test_token_expiring_within_margin_is_expired(self):
        assert self._tok(30).is_expired() is True

    def test_token_beyond_margin_is_valid(self):
        assert self._tok(300).is_expired() is False

    def test_margin_override(self):
        assert self._tok(30).is_expired(margin_seconds=0) is False
