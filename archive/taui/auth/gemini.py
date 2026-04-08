"""
Google Gemini CLI OAuth — PKCE browser redirect to Google accounts.
Uses the Cloud Code Assist endpoint.
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
    "NjgxMjU1ODA5Mzk1LW9v"
    "OGZ0Mm9wcmRybnA5ZTNh"
    "cWY2YXYzaG1kaWIxMzVq"
    "LmFwcHMuZ29vZ2xldXNl"
    "cmNvbnRlbnQuY29t"
).decode()
CLIENT_SECRET = base64.b64decode(
    "R09DU1BYLTR1SGdNUG0t"
    "MW83U2stZ2VWNkN1NWNs"
    "WEZzeGw="
).decode()
REDIRECT_URI = "http://localhost:8085/oauth2callback"
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"

_CODE_ASSIST_HEADERS = {
    "User-Agent": "google-api-nodejs-client/9.15.1",
    "X-Goog-Api-Client": "gl-node/22.17.0",
    "Content-Type": "application/json",
}


# ── Credentials ────────────────────────────────────────────────────────────────


@dataclass
class GeminiCredentials:
    access_token: str  # short-lived Google OAuth2 token
    refresh_token: str  # long-lived, persisted
    expires_at_ms: int
    project_id: str  # GCP project, persisted
    email: Optional[str] = None


# ── Auth flow ──────────────────────────────────────────────────────────────────


def login() -> GeminiCredentials:
    """Full interactive PKCE OAuth login for Gemini CLI."""
    verifier, challenge = generate_pkce()
    # NOTE: verifier doubles as state for Google providers
    state = verifier

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",  # required to get refresh_token
        "prompt": "consent",  # required to get refresh_token
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    print("\nLogging in to Google Gemini CLI...")
    code = race_callback_or_paste(
        port=8085,
        path="/oauth2callback",
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
        "gemini",
        {
            "refresh_token": refresh_token,
            "project_id": project_id,
            "email": email or "",
        },
    )

    print("Gemini login successful.\n")
    return GeminiCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_ms=expires_at_ms,
        project_id=project_id,
        email=email,
    )


def refresh_access_token(creds: GeminiCredentials) -> GeminiCredentials:
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

    return GeminiCredentials(
        access_token=data["access_token"],
        refresh_token=creds.refresh_token,
        expires_at_ms=expires_at_ms,
        project_id=creds.project_id,
        email=creds.email,
    )


def ensure_valid_token(creds: GeminiCredentials) -> GeminiCredentials:
    if time.time() * 1000 >= creds.expires_at_ms:
        return refresh_access_token(creds)
    return creds


def get_gemini_credentials() -> GeminiCredentials:
    """Load saved credentials or trigger interactive login."""
    saved = config.load_provider_config("gemini")
    if saved:
        refresh_token = saved.get("refresh_token")
        project_id = saved.get("project_id", "")
        email = saved.get("email") or None
        if refresh_token and project_id:
            try:
                creds = GeminiCredentials(
                    access_token="",
                    refresh_token=refresh_token,
                    expires_at_ms=0,
                    project_id=project_id,
                    email=email,
                )
                return refresh_access_token(creds)
            except Exception as exc:
                print(f"Saved Gemini token invalid ({exc}). Re-authenticating...\n")

    return login()


# ── GCP project discovery ──────────────────────────────────────────────────────


def _discover_project(access_token: str) -> str:
    """
    Discover or create a GCP project for Cloud Code Assist.
    Mirrors google-gemini-cli setup.ts setupUser().
    """
    import os

    # 1. Check environment variables first
    env_project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get(
        "GOOGLE_CLOUD_PROJECT_ID"
    )

    headers = {
        **_CODE_ASSIST_HEADERS,
        "Authorization": f"Bearer {access_token}",
    }

    # 2. POST loadCodeAssist to check current tier
    # Request body mirrors gemini-cli setup.ts: cloudaicompanionProject + metadata
    req_body = {
        "cloudaicompanionProject": env_project,
        "metadata": {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": env_project,
        },
    }
    try:
        resp = httpx.post(
            f"{CODE_ASSIST_ENDPOINT}/v1internal:loadCodeAssist",
            json=req_body,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(
                f"Unexpected loadCodeAssist response type: {type(data).__name__}: {data!r}"
            )
    except Exception as exc:
        if env_project:
            return env_project
        raise RuntimeError(
            f"Failed to contact Cloud Code Assist ({exc}). "
            "Set GOOGLE_CLOUD_PROJECT env var or try again."
        )

    # currentTier present means user is set up
    current_tier = data.get("currentTier")
    if current_tier:
        # cloudaicompanionProject is a string in the response (not {id: ...})
        project = data.get("cloudaicompanionProject")
        if project and isinstance(project, str):
            return project
        if env_project:
            return env_project
        raise RuntimeError(
            "Cloud Code Assist is enabled but no project ID found. "
            "Set GOOGLE_CLOUD_PROJECT env var."
        )

    # 3. No tier — need onboarding
    # Pick the default tier (isDefault=True), fall back to first, then LEGACY
    allowed_tiers = data.get("allowedTiers") or []
    default_tier = next((t for t in allowed_tiers if t.get("isDefault")), None)
    tier = default_tier or (allowed_tiers[0] if allowed_tiers else None)
    tier_id = (tier or {}).get("id", "LEGACY")

    # For FREE tier, don't set cloudaicompanionProject (causes Precondition Failed)
    if tier_id == "FREE":
        onboard_body: dict = {
            "tierId": tier_id,
            "metadata": {
                "ideType": "IDE_UNSPECIFIED",
                "platform": "PLATFORM_UNSPECIFIED",
                "pluginType": "GEMINI",
            },
        }
    else:
        onboard_body = {
            "tierId": tier_id,
            "cloudaicompanionProject": env_project,
            "metadata": {
                "ideType": "IDE_UNSPECIFIED",
                "platform": "PLATFORM_UNSPECIFIED",
                "pluginType": "GEMINI",
                "duetProject": env_project,
            },
        }

    try:
        onboard_resp = httpx.post(
            f"{CODE_ASSIST_ENDPOINT}/v1internal:onboardUser",
            json=onboard_body,
            headers=headers,
            timeout=30,
        )
        onboard_resp.raise_for_status()
        lro = onboard_resp.json()
        op_name = lro.get("name", "")

        # Poll until done (5s interval, 60s max)
        import time as _time

        deadline = _time.time() + 60
        while _time.time() < deadline:
            _time.sleep(5)
            poll_resp = httpx.get(
                f"{CODE_ASSIST_ENDPOINT}/v1internal/{op_name}",
                headers=headers,
                timeout=30,
            )
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()
            if poll_data.get("done"):
                # LRO response: {response: {cloudaicompanionProject: {id: "..."}}}
                project = (
                    poll_data.get("response", {})
                    .get("cloudaicompanionProject", {})
                    .get("id")
                )
                if project:
                    return project
                break
    except Exception:
        pass

    if env_project:
        return env_project
    raise RuntimeError(
        "Onboarding failed. Set GOOGLE_CLOUD_PROJECT env var and try again."
    )


def _get_user_email(access_token: str) -> Optional[str]:
    """GET Google userinfo to retrieve the user's email."""
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
