"""OAuth callback server for Schwab API authentication.

Multi-app broker: holds tokens for **two** Schwab apps in parallel, so a
production app and a sandbox app can be authorized independently without
either process holding the other's refresh token.

  - **prod**    (default) — your production Schwab app
  - **sandbox** — your sandbox Schwab app

Each app reads its credentials from a distinct env-var prefix
(``SCHWAB_*`` for prod, ``SCHWAB_SANDBOX_*`` for sandbox) and persists
its tokens to a distinct file. Endpoints accept an optional
``?app=prod|sandbox`` query parameter (default ``prod``).

The ``/oauth/callback`` endpoint reads OAuth's ``state`` parameter to
know which app a returning consent belongs to, which is what lets both
apps share a single registered callback URL. Set that URL — whatever you
registered with Schwab — via ``SCHWAB_REDIRECT_URI`` and
``SCHWAB_SANDBOX_REDIRECT_URI``; nothing here is tied to a particular
host or hosting provider.
"""

import hmac
import html
import json
import os
import secrets
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from .auth import SchwabAuth

app = FastAPI(title="Schwab OAuth Server")

API_KEY = os.environ.get("API_KEY", "")

AppName = Literal["prod", "sandbox"]

# One lock per tenant: reload-from-disk and refresh must be a single
# atomic step, or two threadpool workers can refresh concurrently and the
# loser persists a refresh token Schwab just rotated away.
_TENANT_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)

# --- OAuth state (CSRF) nonces --------------------------------------
#
# /oauth/start mints a single-use nonce and rides it through Schwab in
# the OAuth `state` parameter as "<tenant>:<nonce>"; /oauth/callback
# only exchanges codes whose state carries a live nonce. Without this,
# anyone who knows the (public) client_id can complete consent with
# their OWN Schwab login and overwrite our stored tokens with theirs —
# a token-store poisoning/DoS, though never a disclosure of our data.
#
# Nonces persist to disk (OAUTH_STATE_FILE), NOT process memory: a host
# that autostops when idle can cold-restart between /oauth/start and the
# callback, which a user's login easily spans.

_STATE_TTL = timedelta(minutes=10)
_STATE_LOCK = threading.Lock()


def _state_file() -> Path:
    return Path(os.environ.get("OAUTH_STATE_FILE", "/data/oauth_state.json"))


def _load_states() -> dict:
    try:
        data = json.loads(_state_file().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_states(states: dict) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(states, f)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _prune_expired(states: dict) -> dict:
    now = datetime.now()
    out = {}
    for nonce, entry in states.items():
        try:
            if datetime.fromisoformat(entry["expires_at"]) > now:
                out[nonce] = entry
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _issue_state(app_name: AppName) -> str:
    """Mint a single-use CSRF nonce for a consent flow; returns the
    OAuth state value ("<tenant>:<nonce>")."""
    nonce = secrets.token_urlsafe(24)
    with _STATE_LOCK:
        states = _prune_expired(_load_states())
        states[nonce] = {
            "app": app_name,
            "expires_at": (datetime.now() + _STATE_TTL).isoformat(),
        }
        _save_states(states)
    return f"{app_name}:{nonce}"


def _consume_state(state: str | None) -> AppName | None:
    """Validate and burn a callback's state. Returns the tenant it was
    minted for, or None if the state is missing/unknown/expired/reused
    or names a different tenant than it was minted for."""
    if not state or ":" not in state:
        return None
    app_name, _, nonce = state.partition(":")
    if app_name not in ("prod", "sandbox") or not nonce:
        return None
    with _STATE_LOCK:
        states = _prune_expired(_load_states())
        entry = states.pop(nonce, None)
        _save_states(states)
    if entry is None or entry.get("app") != app_name:
        return None
    return app_name  # type: ignore[return-value]


@lru_cache
def get_auth(app_name: AppName = "prod") -> SchwabAuth:
    """Return the SchwabAuth for the named tenant app.

    "prod" reads the original ``SCHWAB_*`` env vars (preserves existing
    behavior). "sandbox" reads ``SCHWAB_SANDBOX_*`` env vars.
    """
    if app_name == "sandbox":
        environment = os.environ.get("SCHWAB_SANDBOX_ENVIRONMENT", "sandbox")
        if environment not in ("sandbox", "production"):
            raise ValueError(
                "SCHWAB_SANDBOX_ENVIRONMENT must be 'sandbox' or 'production'"
            )
        return SchwabAuth(
            client_id=os.environ.get("SCHWAB_SANDBOX_CLIENT_ID", ""),
            client_secret=os.environ.get("SCHWAB_SANDBOX_CLIENT_SECRET", ""),
            # Same default as SchwabAuth.from_env() uses for the prod app.
            # Deployments set SCHWAB_SANDBOX_REDIRECT_URI to whatever
            # callback URL is registered with Schwab for their app.
            redirect_uri=os.environ.get(
                "SCHWAB_SANDBOX_REDIRECT_URI", "https://127.0.0.1"
            ),
            token_file=os.environ.get(
                "SCHWAB_SANDBOX_TOKEN_FILE", "/data/schwab_sandbox_tokens.json"
            ),
            environment=environment,
        )
    return SchwabAuth.from_env()


def _verify_api_key(key: str = Query(...)) -> str:
    if not API_KEY or not hmac.compare_digest(key, API_KEY):
        raise HTTPException(status_code=401, detail="unauthorized")
    return key


def _resolve_app(app: str | None) -> AppName:
    if app and app not in ("prod", "sandbox"):
        raise HTTPException(
            status_code=400,
            detail=f"app must be 'prod' or 'sandbox', got {app!r}",
        )
    return app or "prod"  # type: ignore[return-value]


@app.get("/oauth/start")
def oauth_start(
    _: str = Depends(_verify_api_key),
    app: str | None = Query(None),
):
    name = _resolve_app(app)
    # OAuth state round-trips "<tenant>:<nonce>" through Schwab: the
    # tenant routes the callback to the right app, the nonce proves the
    # flow was initiated here (CSRF/token-poisoning guard).
    state = _issue_state(name)
    return {"authorize_url": get_auth(name).get_authorization_url(state=state)}


@app.get("/oauth/callback", response_class=HTMLResponse)
def oauth_callback(
    code: str = Query(...),
    state: str | None = Query(None),
):
    # state must carry a live single-use nonce minted by /oauth/start —
    # a code from a consent flow we didn't initiate is rejected before
    # any exchange, so a stranger self-consenting against our (public)
    # client_id can't overwrite the stored tokens with their own.
    name = _consume_state(state)
    if name is None:
        print(
            f"[oauth_callback] rejected state={state!r} (missing/unknown/"
            "expired/reused nonce)",
            flush=True,
        )
        return HTMLResponse(
            "<html><body><h1>Error</h1>"
            "<p>Invalid or expired login state. Start the flow again via "
            "/oauth/start (nonces are single-use and expire after 10 "
            "minutes).</p></body></html>",
            status_code=403,
        )
    try:
        tokens = get_auth(name).exchange_code(code)
        return HTMLResponse(
            "<html><body><h1>Success!</h1>"
            f"<p>Authenticated as <b>{name}</b>. Token expires at "
            f"{tokens.expires_at.isoformat()}.</p>"
            "</body></html>"
        )
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text
        except Exception:
            pass
        detail = f"{e} — response body: {body}"
        print(f"[oauth_callback app={name}] exchange failed: {detail}", flush=True)
        return HTMLResponse(
            "<html><body><h1>Error</h1>"
            f"<p>app: {html.escape(name)}</p>"
            f"<p>{html.escape(str(e))}</p>"
            f"<pre>{html.escape(body)}</pre>"
            "</body></html>",
            status_code=500,
        )
    except Exception as e:
        # Full detail goes to the server log only; the unauthenticated
        # caller gets a generic page (str(e) can carry paths/config).
        print(f"[oauth_callback app={name}] unexpected error: {e!r}", flush=True)
        return HTMLResponse(
            "<html><body><h1>Error</h1>"
            f"<p>app: {html.escape(name)}</p>"
            "<p>Unexpected error — see server logs.</p></body></html>",
            status_code=500,
        )


@app.get("/oauth/status")
def oauth_status(app: str | None = Query(None)):
    # Intentionally unauthenticated: exposes only a boolean + expiry so
    # the login helper can poll for completion. Reload from disk so a
    # refresh done by another handler is visible immediately.
    name = _resolve_app(app)
    tokens = get_auth(name).load_tokens()
    if tokens is None:
        return {"app": name, "authenticated": False, "expired": None, "expires_at": None}
    return {
        "app": name,
        "authenticated": True,
        "expired": tokens.is_expired(),
        "expires_at": tokens.expires_at.isoformat(),
    }


@app.get("/oauth/tokens")
def oauth_tokens(
    _: str = Depends(_verify_api_key),
    app: str | None = Query(None),
):
    """Export tokens (API key protected) for syncing to local dev."""
    # Reload from disk: the cached .tokens property could hand out a
    # refresh token that a later refresh already rotated away.
    name = _resolve_app(app)
    tokens = get_auth(name).load_tokens()
    if tokens is None:
        return JSONResponse({"app": name, "error": "no tokens"}, status_code=404)
    payload = tokens.to_dict()
    payload["app"] = name
    return payload


@app.get("/oauth/access_token")
def oauth_access_token(
    _: str = Depends(_verify_api_key),
    app: str | None = Query(None),
):
    """Return a fresh access token, auto-refreshing if expired.

    This endpoint is the single owner of refresh; downstream services call it
    instead of holding the refresh_token themselves so a refresh-token rotation
    can never produce a race between two refreshers.
    """
    name = _resolve_app(app)
    auth = get_auth(name)
    with _TENANT_LOCKS[name]:
        # Reload from disk in case another worker/process refreshed.
        # Inside the lock: reloading concurrently with a refresh would
        # resurrect the pre-refresh (rotated-away) refresh token.
        auth.load_tokens()
        try:
            access_token = auth.get_access_token(auto_refresh=True)
        except ValueError as e:
            return JSONResponse({"app": name, "error": str(e)}, status_code=404)
        except httpx.HTTPError as e:
            # invalid_grant, token-endpoint timeout, etc. — a broker
            # problem, not a caller problem; surface it as 502 rather
            # than an opaque 500 traceback.
            print(
                f"[oauth_access_token app={name}] refresh failed: {e!r}",
                flush=True,
            )
            return JSONResponse(
                {"app": name, "error": f"token refresh failed: {e}"},
                status_code=502,
            )
        tokens = auth.tokens
    return {
        "app": name,
        "access_token": access_token,
        "expires_at": tokens.expires_at.isoformat() if tokens else None,
    }
