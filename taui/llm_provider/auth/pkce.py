"""
Shared PKCE infrastructure for browser-redirect OAuth providers.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import threading
import urllib.parse
import webbrowser


def generate_pkce() -> tuple[str, str]:
    """Returns (verifier, challenge). Uses base64url encoding (no padding)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def wait_for_callback(
    port: int,
    path: str,
    expected_state: str,
    timeout: float = 120.0,
) -> str | None:
    """
    Start an HTTP server on localhost:port in a daemon thread.
    Wait for GET request to `path` with ?code=...&state=... params.
    Validates state == expected_state.
    Returns authorization code, or None on timeout/cancel.
    """
    result: list[str | None] = [None]
    ready = threading.Event()

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args, **kwargs) -> None:
            pass  # suppress access log

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != path:
                self._respond(404, "Not found")
                return

            params = urllib.parse.parse_qs(parsed.query)
            code = (params.get("code") or [None])[0]
            state = (params.get("state") or [None])[0]
            error = (params.get("error") or [None])[0]

            if error:
                self._respond(400, f"<h1>OAuth error: {error}</h1>")
                ready.set()
                return

            if state != expected_state:
                self._respond(400, "<h1>State mismatch. Please try again.</h1>")
                return

            result[0] = code
            self._respond(
                200, "<h1>Authorization successful! You can close this tab.</h1>"
            )
            ready.set()

        def _respond(self, status: int, body: str) -> None:
            encoded = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = http.server.HTTPServer(("localhost", port), _Handler)
    server.timeout = 1.0  # so handle_request() returns regularly

    def _serve() -> None:
        while not ready.is_set():
            server.handle_request()
        server.server_close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    ready.wait(timeout=timeout)
    return result[0]


def race_callback_or_paste(
    port: int,
    path: str,
    expected_state: str,
    auth_url: str,
    timeout: float = 120.0,
) -> str:
    """
    Open auth_url in browser, also print it for manual use.
    Race between:
      - The local callback server receiving the redirect, and
      - The user manually pasting the full redirect URL into stdin.
    Returns the authorization code. Raises RuntimeError on timeout.
    """
    webbrowser.open(auth_url)
    print(f"\nOpen this URL if the browser did not open automatically:\n  {auth_url}\n")
    print("Or paste the full redirect URL here (and press Enter): ", end="", flush=True)

    code_holder: list[str | None] = [None]
    done = threading.Event()

    # Thread 1: callback server
    def _server_thread() -> None:
        code = wait_for_callback(port, path, expected_state, timeout)
        if code and not done.is_set():
            code_holder[0] = code
            done.set()

    threading.Thread(target=_server_thread, daemon=True).start()

    # Thread 2 (main thread): stdin paste
    import select
    import sys

    deadline_remaining = timeout
    while not done.is_set() and deadline_remaining > 0:
        # Poll stdin with 1-second granularity so we can check done.is_set()
        r, _, _ = select.select([sys.stdin], [], [], 1.0)
        deadline_remaining -= 1.0
        if r:
            line = sys.stdin.readline().strip()
            if line:
                parsed = urllib.parse.urlparse(line)
                params = urllib.parse.parse_qs(parsed.query)
                pasted_code = (params.get("code") or [None])[0]
                pasted_state = (params.get("state") or [None])[0]
                if pasted_code and pasted_state == expected_state:
                    code_holder[0] = pasted_code
                    done.set()

    if not code_holder[0]:
        raise RuntimeError("OAuth callback timed out. Please try again.")

    return code_holder[0]
