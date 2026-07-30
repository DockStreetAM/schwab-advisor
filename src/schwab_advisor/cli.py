"""CLI tools for Schwab Advisor API authentication."""

import html
import os
import ssl
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from .auth import SchwabAuth


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to capture OAuth callback."""

    authorization_code: str | None = None
    error: str | None = None

    def do_GET(self):
        """Handle GET request from OAuth callback."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            OAuthCallbackHandler.authorization_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <head><title>Authorization Successful</title></head>
                <body>
                <h1>Authorization Successful!</h1>
                <p>You can close this window and return to the terminal.</p>
                </body>
                </html>
            """)
        elif "error" in params:
            error_info = params.get("error_description", params["error"])
            OAuthCallbackHandler.error = error_info[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"""
                <html>
                <head><title>Authorization Failed</title></head>
                <body>
                <h1>Authorization Failed</h1>
                <p>Error: {html.escape(str(OAuthCallbackHandler.error))}</p>
                </body>
                </html>
            """.encode())
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Missing authorization code")

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def _create_self_signed_cert():
    """Create a temporary self-signed certificate for HTTPS."""
    try:
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("Error: cryptography package required for HTTPS callback server.")
        print("Install with: pip install cryptography")
        sys.exit(1)

    # Generate private key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Generate certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress_from_string("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    # Write to temp files
    cert_file = tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False)
    key_file = tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False)

    cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )

    cert_file.close()
    key_file.close()

    return cert_file.name, key_file.name


def ipaddress_from_string(ip_str: str):
    """Convert IP string to ipaddress object."""
    import ipaddress
    return ipaddress.IPv4Address(ip_str)


def _parse_redirect_uri(redirect_uri: str) -> tuple[str, int, bool]:
    """Parse redirect URI into host, port, and HTTPS flag.

    Args:
        redirect_uri: OAuth redirect URI

    Returns:
        Tuple of (host, port, use_https)
    """
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    use_https = parsed.scheme == "https"

    if parsed.port:
        port = parsed.port
    elif use_https:
        port = 443
    else:
        port = 80

    return host, port, use_https


def _extract_code_from_url(url: str) -> str | None:
    """Extract authorization code from callback URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    if "code" in params:
        return params["code"][0]
    return None


def _manual_code_entry(auth: SchwabAuth, auth_url: str) -> None:
    """Handle manual code entry flow."""
    print("=" * 60)
    print("Schwab OAuth Authorization (Manual Mode)")
    print("=" * 60)
    print()
    print("1. Open the following URL in your browser:")
    print()
    print(f"   {auth_url}")
    print()
    print("2. Log in to your Schwab account and authorize the application.")
    print()
    print("3. After authorization, you'll be redirected to a page that won't load.")
    print("   That's OK! Copy the FULL URL from your browser's address bar.")
    print()
    print("   It will look like: https://127.0.0.1/?code=XXXXX&session=YYYYY")
    print()

    while True:
        callback_url = input("Paste the callback URL here: ").strip()
        if not callback_url:
            print("No URL provided. Please try again.")
            continue

        code = _extract_code_from_url(callback_url)
        if code:
            break
        print("Could not find authorization code in URL. Please try again.")

    print()
    print("Exchanging code for tokens...")

    try:
        tokens = auth.exchange_code(code)
        print()
        print("=" * 60)
        print("Authorization Successful!")
        print("=" * 60)
        print()
        print(f"Access token expires at: {tokens.expires_at}")
        if auth.token_file:
            print(f"Tokens saved to: {auth.token_file}")
        print()
        print("You can now use the Schwab Advisor API client:")
        print()
        print("  from schwab_advisor import SchwabAdvisorClient")
        print("  client = SchwabAdvisorClient()")
        print("  profiles = client.get_account_profiles()")
        print()
    except Exception as e:
        print(f"Error exchanging code for tokens: {e}")
        sys.exit(1)


def authorize():
    """Run OAuth flow interactively.

    This function:
    1. Prints authorization URL for user to visit
    2. Tries to start local HTTPS server to receive callback
    3. Falls back to manual code entry if server can't start
    4. Exchanges code for tokens
    5. Saves tokens to file
    """
    # Check for required environment variables
    client_id = os.environ.get("SCHWAB_CLIENT_ID")
    client_secret = os.environ.get("SCHWAB_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Error: Required environment variables not set.")
        print()
        print("Please set the following environment variables:")
        print("  SCHWAB_CLIENT_ID=your_client_id")
        print("  SCHWAB_CLIENT_SECRET=your_client_secret")
        print("  SCHWAB_REDIRECT_URI=https://127.0.0.1 (optional)")
        print("  SCHWAB_TOKEN_FILE=~/.schwab_tokens.json (optional)")
        sys.exit(1)

    auth = SchwabAuth.from_env()
    redirect_uri = auth.redirect_uri

    # Parse redirect URI
    host, port, use_https = _parse_redirect_uri(redirect_uri)

    # Generate the authorization URL. When the redirect URI points at the
    # multi-tenant broker, the URL must come from its /oauth/start — the
    # broker mints a single-use CSRF nonce into OAuth `state` and its
    # callback rejects consent flows it didn't initiate. Local redirects
    # (127.0.0.1) don't involve the broker, so the URL is built locally
    # with no state.
    if host in ("127.0.0.1", "localhost"):
        auth_url = auth.get_authorization_url()
    else:
        broker_app = "sandbox" if auth.environment == "sandbox" else "prod"
        broker_key = os.environ.get("SCHWAB_OAUTH_API_KEY") or os.environ.get(
            "SCHWAB_OAUTH_BROKER_KEY"
        )
        if not broker_key:
            print(
                "Error: redirect URI points at the OAuth broker, but no "
                "SCHWAB_OAUTH_API_KEY is set.\n"
                "The broker's callback only accepts flows initiated via its "
                "/oauth/start endpoint (CSRF nonce), which requires the "
                "broker API key."
            )
            sys.exit(1)
        import httpx as _httpx

        broker_base = f"https://{host}" if port == 443 else f"https://{host}:{port}"
        resp = _httpx.get(
            f"{broker_base}/oauth/start",
            params={"key": broker_key, "app": broker_app},
            timeout=15.0,
        )
        resp.raise_for_status()
        auth_url = resp.json()["authorize_url"]

    # For sandbox, surface the login creds (from the environment) so the
    # operator running a recorded walkthrough doesn't have to hunt for them.
    # Never hardcoded here — this is a shared library; creds come from env.
    if auth.environment == "sandbox":
        sac_user = os.environ.get("SCHWAB_SAC_USERNAME")
        sac_pass = os.environ.get("SCHWAB_SAC_PASSWORD")
        if sac_user and sac_pass:
            print("Sandbox login for the browser pop-up:")
            print(f"   username:      {sac_user}")
            print(f"   password:      {sac_pass}")
            print("   security code: 123456   (fixed sandbox value)")
            print()

    # Check if we need elevated privileges for port < 1024
    # (geteuid doesn't exist on Windows; assume unprivileged there)
    if port < 1024 and getattr(os, "geteuid", lambda: -1)() != 0:
        # Fall back to manual mode
        _manual_code_entry(auth, auth_url)
        return

    print("=" * 60)
    print("Schwab OAuth Authorization")
    print("=" * 60)
    print()
    print("1. Open the following URL in your browser:")
    print()
    print(f"   {auth_url}")
    print()
    print("2. Log in to your Schwab account and authorize the application.")
    print()
    print(f"3. You will be redirected to {redirect_uri}")
    print()
    print(f"Starting {'HTTPS' if use_https else 'HTTP'} server on {host}:{port}...")
    print("Waiting for authorization callback...")
    print()

    # Reset handler state
    OAuthCallbackHandler.authorization_code = None
    OAuthCallbackHandler.error = None

    # Create and configure server
    try:
        server = HTTPServer((host, port), OAuthCallbackHandler)
    except PermissionError:
        print(f"Permission denied for port {port}. Falling back to manual mode.")
        print()
        _manual_code_entry(auth, auth_url)
        return

    if use_https:
        cert_file, key_file = _create_self_signed_cert()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_file, key_file)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        # Clean up temp files
        os.unlink(cert_file)
        os.unlink(key_file)

    # Serve until the callback (or an error) arrives — a stray first
    # request (favicon.ico, a browser TLS pre-probe) must not consume
    # the only handled request and abort the flow. Bounded so a never-
    # completed login can't hang the process forever.
    server.timeout = 300
    for _ in range(20):
        if OAuthCallbackHandler.authorization_code or OAuthCallbackHandler.error:
            break
        server.handle_request()
    server.server_close()

    if OAuthCallbackHandler.error:
        print(f"Error: {OAuthCallbackHandler.error}")
        sys.exit(1)

    if not OAuthCallbackHandler.authorization_code:
        print("Error: No authorization code received")
        sys.exit(1)

    print("Authorization code received!")
    print("Exchanging code for tokens...")

    try:
        tokens = auth.exchange_code(OAuthCallbackHandler.authorization_code)
        print()
        print("=" * 60)
        print("Authorization Successful!")
        print("=" * 60)
        print()
        print(f"Access token expires at: {tokens.expires_at}")
        if auth.token_file:
            print(f"Tokens saved to: {auth.token_file}")
        print()
        print("You can now use the Schwab Advisor API client:")
        print()
        print("  from schwab_advisor import SchwabAdvisorClient")
        print("  client = SchwabAdvisorClient()")
        print("  profiles = client.get_account_profiles()")
        print()
    except Exception as e:
        print(f"Error exchanging code for tokens: {e}")
        sys.exit(1)


def main():
    """Entry point for CLI."""
    authorize()


if __name__ == "__main__":
    main()
