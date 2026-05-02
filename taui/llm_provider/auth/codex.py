"""
OpenAI Codex (ChatGPT Plus/Pro) OAuth — PKCE browser redirect.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.parse
from dataclasses import dataclass

import httpx

from ..config import load_provider_config, save_provider_config
from .pkce import generate_pkce, race_callback_or_paste

# ── Constants ──────────────────────────────────────────────────────────────────

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPE = "openid profile email offline_access"


# ── Credentials ────────────────────────────────────────────────────────────────


@dataclass
class CodexCredentials:
    access_token: str  # JWT, short-lived
    refresh_token: str  # long-lived, persisted
    expires_at_ms: int
    account_id: str  # extracted from JWT, persisted


# ── JWT helpers ────────────────────────────────────────────────────────────────


def _decode_jwt_payload(token: str) -> dict:
    """Split on '.', take parts[1], base64url-decode, json.loads. Stdlib only."""
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("Not a valid JWT")
    payload = parts[1]
    payload += "=" * (4 - len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload)
    return json.loads(decoded)


def _get_account_id(access_token: str) -> str:
    payload = _decode_jwt_payload(access_token)
    try:
        return payload["https://api.openai.com/auth"]["chatgpt_account_id"]
    except (KeyError, TypeError) as exc:
        raise ValueError("chatgpt_account_id not found in JWT payload") from exc


# ── Auth flow ──────────────────────────────────────────────────────────────────


def login() -> CodexCredentials:
    """Full interactive PKCE OAuth login for Codex."""
    verifier, challenge = generate_pkce()
    import secrets as _secrets

    state = _secrets.token_bytes(16).hex()

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": "taui",
    }
    auth_url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    print("\nLogging in to OpenAI Codex...")
    code = race_callback_or_paste(
        port=1455,
        path="/auth/callback",
        expected_state=state,
        auth_url=auth_url,
    )

    # Exchange code for tokens
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    access_token = data["access_token"]
    refresh_token = data["refresh_token"]
    expires_in = int(data.get("expires_in", 3600))
    expires_at_ms = int(time.time() * 1000) + expires_in * 1000

    account_id = _get_account_id(access_token)

    save_provider_config(
        "codex",
        {
            "refresh_token": refresh_token,
            "account_id": account_id,
        },
    )

    print("Codex login successful.\n")
    return CodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_ms=expires_at_ms,
        account_id=account_id,
    )


def refresh_access_token(creds: CodexCredentials) -> CodexCredentials:
    """POST TOKEN_URL with grant_type=refresh_token. No client_secret — PKCE only."""
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": creds.refresh_token,
            "client_id": CLIENT_ID,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    access_token = data["access_token"]
    refresh_token = data.get("refresh_token", creds.refresh_token)
    expires_in = int(data.get("expires_in", 3600))
    expires_at_ms = int(time.time() * 1000) + expires_in * 1000

    # Re-extract account_id from new JWT (it shouldn't change, but be safe)
    try:
        account_id = _get_account_id(access_token)
    except ValueError:
        account_id = creds.account_id

    # Persist rotated refresh_token
    save_provider_config(
        "codex",
        {
            "refresh_token": refresh_token,
            "account_id": account_id,
        },
    )

    return CodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_ms=expires_at_ms,
        account_id=account_id,
    )


def ensure_valid_token(creds: CodexCredentials) -> CodexCredentials:
    if time.time() * 1000 >= creds.expires_at_ms:
        return refresh_access_token(creds)
    return creds


def get_codex_credentials() -> CodexCredentials:
    """Load saved credentials or trigger interactive login."""
    saved = load_provider_config("codex")
    if saved:
        refresh_token = saved.get("refresh_token")
        account_id = saved.get("account_id", "")
        if refresh_token:
            try:
                creds = CodexCredentials(
                    access_token="",
                    refresh_token=refresh_token,
                    expires_at_ms=0,
                    account_id=account_id,
                )
                return refresh_access_token(creds)
            except Exception as exc:
                print(f"Saved Codex token invalid ({exc}). Re-authenticating...\n")

    return login()
