"""Tests for the FastAPI OAuth callback server."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from schwab_advisor.models import TokenResponse


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.get_authorization_url.return_value = "https://schwab.com/authorize?client_id=test"
    auth.tokens = None
    auth.load_tokens.return_value = None
    return auth


@pytest.fixture
def client(mock_auth, tmp_path):
    env = {
        "API_KEY": "test-api-key",
        # CSRF nonces persist here; per-test tmp dir keeps tests isolated
        "OAUTH_STATE_FILE": str(tmp_path / "oauth_state.json"),
    }
    with patch.dict("os.environ", env, clear=False):
        # Must import after env is set so API_KEY picks up the value
        import importlib
        import schwab_advisor.server as server_module
        importlib.reload(server_module)

        with patch.object(server_module, "get_auth", return_value=mock_auth):
            yield TestClient(server_module.app)


def _mint_state(app_name="prod"):
    """Issue a live CSRF state exactly as /oauth/start would."""
    import schwab_advisor.server as server_module

    return server_module._issue_state(app_name)


class TestOAuthStart:
    def test_start_with_valid_key(self, client, mock_auth):
        resp = client.get("/oauth/start?key=test-api-key")
        assert resp.status_code == 200
        assert "authorize_url" in resp.json()

    def test_start_with_invalid_key(self, client):
        resp = client.get("/oauth/start?key=wrong-key")
        assert resp.status_code == 401

    def test_start_missing_key(self, client):
        resp = client.get("/oauth/start")
        assert resp.status_code == 422  # FastAPI validation error


class TestOAuthCallback:
    def test_callback_success(self, client, mock_auth):
        mock_auth.exchange_code.return_value = TokenResponse(
            access_token="new_token", refresh_token="new_refresh",
            token_type="Bearer", expires_in=1800, scope="api",
            expires_at=datetime.now() + timedelta(seconds=1800),
        )
        resp = client.get(
            f"/oauth/callback?code=auth_code_123&state={_mint_state()}"
        )
        assert resp.status_code == 200
        assert "Success" in resp.text
        mock_auth.exchange_code.assert_called_once_with("auth_code_123")

    def test_callback_error_hides_detail(self, client, mock_auth):
        """Unexpected-exception detail goes to server logs only — the
        unauthenticated caller gets a generic page (str(e) can carry
        internal paths/config)."""
        mock_auth.exchange_code.side_effect = Exception("Token exchange failed")
        resp = client.get(f"/oauth/callback?code=bad_code&state={_mint_state()}")
        assert resp.status_code == 500
        assert "Error" in resp.text
        assert "Token exchange failed" not in resp.text
        assert "see server logs" in resp.text

    def test_callback_xss_protection(self, client, mock_auth):
        mock_auth.exchange_code.side_effect = Exception("<script>alert('xss')</script>")
        resp = client.get(f"/oauth/callback?code=xss&state={_mint_state()}")
        assert "<script>" not in resp.text
        # New contract: the exception string never reaches the page in
        # any form, escaped or not.
        assert "alert(" not in resp.text


class TestOAuthStatus:
    def test_status_no_tokens(self, client, mock_auth):
        mock_auth.tokens = None
        mock_auth.load_tokens.return_value = None
        resp = client.get("/oauth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False

    def test_status_with_valid_tokens(self, client, mock_auth):
        mock_auth.tokens = TokenResponse(
            access_token="t", refresh_token="r",
            token_type="Bearer", expires_in=1800, scope="api",
            expires_at=datetime.now() + timedelta(seconds=1800),
        )
        mock_auth.load_tokens.return_value = mock_auth.tokens
        resp = client.get("/oauth/status")
        data = resp.json()
        assert data["authenticated"] is True
        assert data["expired"] is False

    def test_status_with_expired_tokens(self, client, mock_auth):
        mock_auth.tokens = TokenResponse(
            access_token="t", refresh_token="r",
            token_type="Bearer", expires_in=1800, scope="api",
            expires_at=datetime.now() - timedelta(seconds=100),
        )
        mock_auth.load_tokens.return_value = mock_auth.tokens
        resp = client.get("/oauth/status")
        data = resp.json()
        assert data["authenticated"] is True
        assert data["expired"] is True


class TestOAuthTokens:
    def test_tokens_with_valid_key(self, client, mock_auth):
        mock_auth.tokens = TokenResponse(
            access_token="export_token", refresh_token="export_refresh",
            token_type="Bearer", expires_in=1800, scope="api",
            expires_at=datetime.now() + timedelta(seconds=1800),
        )
        mock_auth.load_tokens.return_value = mock_auth.tokens
        resp = client.get("/oauth/tokens?key=test-api-key")
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "export_token"

    def test_tokens_with_invalid_key(self, client):
        resp = client.get("/oauth/tokens?key=wrong")
        assert resp.status_code == 401

    def test_tokens_none(self, client, mock_auth):
        mock_auth.tokens = None
        mock_auth.load_tokens.return_value = None
        resp = client.get("/oauth/tokens?key=test-api-key")
        assert resp.status_code == 404


class TestOAuthAccessToken:
    def test_access_token_with_valid_key(self, client, mock_auth):
        expires = datetime.now() + timedelta(seconds=1800)
        mock_auth.get_access_token.return_value = "fresh_access_token"
        mock_auth.tokens = TokenResponse(
            access_token="fresh_access_token", refresh_token="r",
            token_type="Bearer", expires_in=1800, scope="api",
            expires_at=expires,
        )
        mock_auth.load_tokens.return_value = mock_auth.tokens
        resp = client.get("/oauth/access_token?key=test-api-key")
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "fresh_access_token"
        assert data["expires_at"] == expires.isoformat()
        mock_auth.load_tokens.assert_called_once()
        mock_auth.get_access_token.assert_called_once_with(auto_refresh=True)

    def test_access_token_with_invalid_key(self, client):
        resp = client.get("/oauth/access_token?key=wrong")
        assert resp.status_code == 401

    def test_access_token_no_tokens(self, client, mock_auth):
        mock_auth.get_access_token.side_effect = ValueError("No tokens available")
        resp = client.get("/oauth/access_token?key=test-api-key")
        assert resp.status_code == 404
        assert "No tokens" in resp.json()["error"]


class TestAccessTokenRefreshFailures:
    """A failed refresh must surface as a clean 502, not an unhandled
    500 traceback (invalid_grant and the sandbox token endpoint's
    8-10s timeouts both happen in practice)."""

    def test_refresh_http_error_returns_502(self, client, mock_auth):
        import httpx

        mock_auth.get_access_token.side_effect = httpx.HTTPStatusError(
            "invalid_grant", request=MagicMock(), response=MagicMock()
        )
        resp = client.get("/oauth/access_token?key=test-api-key")
        assert resp.status_code == 502
        assert "token refresh failed" in resp.json()["error"]

    def test_refresh_timeout_returns_502(self, client, mock_auth):
        import httpx

        mock_auth.get_access_token.side_effect = httpx.ReadTimeout("timed out")
        resp = client.get("/oauth/access_token?key=test-api-key")
        assert resp.status_code == 502
        assert "token refresh failed" in resp.json()["error"]


class TestCallbackCsrfNonce:
    """The callback only exchanges codes whose state carries a live
    single-use nonce minted by /oauth/start — a self-consented code
    from a stranger can't overwrite the token store."""

    def test_missing_state_rejected(self, client, mock_auth):
        resp = client.get("/oauth/callback?code=stolen")
        assert resp.status_code == 403
        mock_auth.exchange_code.assert_not_called()

    def test_legacy_bare_tenant_state_rejected(self, client, mock_auth):
        resp = client.get("/oauth/callback?code=stolen&state=prod")
        assert resp.status_code == 403
        mock_auth.exchange_code.assert_not_called()

    def test_unknown_nonce_rejected(self, client, mock_auth):
        resp = client.get("/oauth/callback?code=stolen&state=prod:forged123")
        assert resp.status_code == 403
        mock_auth.exchange_code.assert_not_called()

    def test_nonce_is_single_use(self, client, mock_auth):
        mock_auth.exchange_code.return_value = TokenResponse(
            access_token="t", refresh_token="r", token_type="Bearer",
            expires_in=1800, scope="api",
            expires_at=datetime.now() + timedelta(seconds=1800),
        )
        state = _mint_state()
        first = client.get(f"/oauth/callback?code=c1&state={state}")
        assert first.status_code == 200
        replay = client.get(f"/oauth/callback?code=c2&state={state}")
        assert replay.status_code == 403
        mock_auth.exchange_code.assert_called_once_with("c1")

    def test_tenant_mismatch_rejected(self, client, mock_auth):
        # Minted for sandbox, presented as prod.
        state = _mint_state("sandbox")
        nonce = state.split(":", 1)[1]
        resp = client.get(f"/oauth/callback?code=c&state=prod:{nonce}")
        assert resp.status_code == 403
        mock_auth.exchange_code.assert_not_called()

    def test_expired_nonce_rejected(self, client, mock_auth):
        import json
        import os

        state = _mint_state()
        nonce = state.split(":", 1)[1]
        state_file = os.environ["OAUTH_STATE_FILE"]
        with open(state_file) as f:
            states = json.load(f)
        states[nonce]["expires_at"] = (
            datetime.now() - timedelta(minutes=1)
        ).isoformat()
        with open(state_file, "w") as f:
            json.dump(states, f)
        resp = client.get(f"/oauth/callback?code=c&state={state}")
        assert resp.status_code == 403
        mock_auth.exchange_code.assert_not_called()

    def test_start_mints_nonce_into_state(self, client, mock_auth):
        client.get("/oauth/start?key=test-api-key&app=sandbox")
        state = mock_auth.get_authorization_url.call_args.kwargs["state"]
        assert state.startswith("sandbox:")
        assert len(state.split(":", 1)[1]) >= 24

    def test_nonce_survives_process_restart(self, client, mock_auth, tmp_path):
        """The store is the volume file, not process memory — a machine
        autostop between /oauth/start and the callback must not lose
        the nonce. Simulated by reloading the server module."""
        import importlib

        import schwab_advisor.server as server_module

        state = _mint_state()
        importlib.reload(server_module)  # cold restart
        with patch.object(server_module, "get_auth", return_value=mock_auth):
            mock_auth.exchange_code.return_value = TokenResponse(
                access_token="t", refresh_token="r", token_type="Bearer",
                expires_in=1800, scope="api",
                expires_at=datetime.now() + timedelta(seconds=1800),
            )
            restarted = TestClient(server_module.app)
            resp = restarted.get(f"/oauth/callback?code=c&state={state}")
        assert resp.status_code == 200
