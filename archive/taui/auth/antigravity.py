"""
Google Antigravity OAuth — nearly identical to gemini.py.
Different constants, port, and simpler project discovery.
"""

from __future__ import annotations

import base64
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import httpx

from taui import config
from taui.auth.pkce import generate_pkce, race_callback_or_paste

# ── Constants ──────────────────────────────────────────────────────────────────

CLIENT_ID = base64.b64decode(
    "MTA3MTAwNjA2MDU5MS10"
    "bWhzc2luMmgyMWxjcmUy"
    "MzV2dG9sb2poNGc0MDNl"
    "cC5hcHBzLmdvb2dsZXVz"
    "ZXJjb250ZW50LmNvbQ=="
).decode()
CLIENT_SECRET = base64.b64decode(
    "R09DU1BYLUs1OEZXUjQ4"
    "NkxkTEoxbUxCOHNYQzR6"
    "NnFEQWY="
).decode()
REDIRECT_URI = "http://localhost:51121/oauth-callback"
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_PROJECT_ID = "rising-fact-p41fc"

_PROD_ENDPOINT = "https://cloudcode-pa.googleapis.com"
_SANDBOX_ENDPOINT = "https://daily-cloudcode-pa.sandbox.googleapis.com"

_CODE_ASSIST_HEADERS = {
    "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "Client-Metadata": '{"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
    "Content-Type": "application/json",
}


# ── Credentials ────────────────────────────────────────────────────────────────


@dataclass
class AntigravityCredentials:
    access_token: str
    refresh_token: str
    expires_at_ms: int
    project_id: str
    email: Optional[str] = None


# ── Auth flow ──────────────────────────────────────────────────────────────────


def login() -> AntigravityCredentials:
    """Full interactive PKCE OAuth login for Antigravity."""
    verifier, challenge = generate_pkce()
    # verifier doubles as state for Google providers
    state = verifier

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    print("\nLogging in to Google Antigravity...")
    code = race_callback_or_paste(
        port=51121,
        path="/oauth-callback",
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
            "client_secret": CLIENT_SECRET,
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

    email = _get_user_email(access_token)
    project_id = _discover_project(access_token)

    config.save_provider_config(
        "antigravity",
        {
            "refresh_token": refresh_token,
            "project_id": project_id,
            "email": email or "",
        },
    )

    print("Antigravity login successful.\n")
    return AntigravityCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_ms=expires_at_ms,
        project_id=project_id,
        email=email,
    )


def refresh_access_token(creds: AntigravityCredentials) -> AntigravityCredentials:
    """Exchange refresh_token for a new access_token."""
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": creds.refresh_token,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    expires_in = int(data.get("expires_in", 3600))
    expires_at_ms = int(time.time() * 1000) + expires_in * 1000

    return AntigravityCredentials(
        access_token=data["access_token"],
        refresh_token=creds.refresh_token,
        expires_at_ms=expires_at_ms,
        project_id=creds.project_id,
        email=creds.email,
    )


def ensure_valid_token(creds: AntigravityCredentials) -> AntigravityCredentials:
    if time.time() * 1000 >= creds.expires_at_ms:
        return refresh_access_token(creds)
    return creds


def get_antigravity_credentials() -> AntigravityCredentials:
    """Load saved credentials or trigger interactive login."""
    saved = config.load_provider_config("antigravity")
    if saved:
        refresh_token = saved.get("refresh_token")
        project_id = saved.get("project_id", DEFAULT_PROJECT_ID)
        email = saved.get("email") or None
        if refresh_token:
            try:
                creds = AntigravityCredentials(
                    access_token="",
                    refresh_token=refresh_token,
                    expires_at_ms=0,
                    project_id=project_id,
                    email=email,
                )
                return refresh_access_token(creds)
            except Exception as exc:
                print(
                    f"Saved Antigravity token invalid ({exc}). Re-authenticating...\n"
                )

    return login()


# ── GCP project discovery ──────────────────────────────────────────────────────


def _discover_project(access_token: str) -> str:
    """
    Simpler project discovery than gemini.py:
    Try prod endpoint, then sandbox, then fall back to DEFAULT_PROJECT_ID (never raises).
    """
    headers = {
        **_CODE_ASSIST_HEADERS,
        "Authorization": f"Bearer {access_token}",
    }

    for endpoint in (_SANDBOX_ENDPOINT, _PROD_ENDPOINT):
        try:
            resp = httpx.post(
                f"{endpoint}/v1internal:loadCodeAssist",
                json={},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            # cloudaicompanionProject is a plain string, not {"id": "..."}
            project = data.get("cloudaicompanionProject")
            if isinstance(project, dict):
                project = project.get("id")
            if project:
                return project
        except Exception:
            continue

    return DEFAULT_PROJECT_ID


def _get_user_email(access_token: str) -> Optional[str]:
    try:
        resp = httpx.get(
            "https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("email")
    except Exception:
        return None
