"""
GitHub Copilot OAuth device flow and token management.

Implements the same auth flow used by the VS Code Copilot Chat extension:
  1. start_device_flow()             — obtain device_code + user_code
  2. poll_for_github_access_token()  — wait for user to authorize on GitHub
  3. refresh_copilot_token()         — exchange GitHub token for a short-lived Copilot API token

The GitHub OAuth token (long-lived) is persisted to ~/.config/taui/config.toml
under [providers.copilot].api_key so subsequent runs skip the device flow.
"""

from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from taui import config

# ── Constants ─────────────────────────────────────────────────────────────────

# CLIENT_ID is base64-encoded to avoid plain-text exposure in source
CLIENT_ID: str = base64.b64decode("SXYxLmI1MDdhMDhjODdlY2ZlOTg=").decode()

COPILOT_HEADERS: dict[str, str] = {
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
}

# Headers for agent/tool-calling requests (Copilot agent mode).
COPILOT_AGENT_HEADERS: dict[str, str] = {
    **COPILOT_HEADERS,
    "Copilot-Integration-Id": "copilot-chat",
}

# Copilot token is valid for ~30 min; refresh 5 min early.
_EXPIRY_BUFFER_MS: int = 5 * 60 * 1000


# ── Credentials ────────────────────────────────────────────────────────────────


@dataclass
class CopilotCredentials:
    """Holds both the long-lived GitHub token and the short-lived Copilot API token."""

    github_token: str
    copilot_token: str
    expires_at_ms: int
    enterprise_domain: Optional[str] = None


# ── URL helpers ────────────────────────────────────────────────────────────────


def _get_urls(domain: str) -> dict[str, str]:
    return {
        "device_code": f"https://{domain}/login/device/code",
        "access_token": f"https://{domain}/login/oauth/access_token",
        "copilot_token": f"https://api.{domain}/copilot_internal/v2/token",
    }


def get_copilot_base_url(
    copilot_token: Optional[str] = None,
    enterprise_domain: Optional[str] = None,
) -> str:
    """Derive the Copilot API base URL from the token's proxy-ep field."""
    if copilot_token:
        match = re.search(r"proxy-ep=([^;]+)", copilot_token)
        if match:
            proxy_host = match.group(1)
            api_host = re.sub(r"^proxy\.", "api.", proxy_host)
            return f"https://{api_host}"
    if enterprise_domain:
        return f"https://copilot-api.{enterprise_domain}"
    return "https://api.individual.githubcopilot.com"


# ── Device flow ────────────────────────────────────────────────────────────────


def start_device_flow(domain: str = "github.com") -> dict:
    """Step 1: request device_code and user_code from GitHub."""
    urls = _get_urls(domain)
    resp = httpx.post(
        urls["device_code"],
        json={"client_id": CLIENT_ID, "scope": "read:user"},
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            **COPILOT_HEADERS,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    for key in (
        "device_code",
        "user_code",
        "verification_uri",
        "interval",
        "expires_in",
    ):
        if key not in data:
            raise ValueError(f"Device code response missing '{key}': {data}")
    return data


def poll_for_github_access_token(
    domain: str,
    device_code: str,
    interval_seconds: int,
    expires_in: int,
) -> str:
    """Step 2: poll until the user authorizes the device. Returns GitHub OAuth token."""
    urls = _get_urls(domain)
    deadline = time.time() + expires_in
    interval = max(1, interval_seconds)

    while time.time() < deadline:
        time.sleep(interval)
        resp = httpx.post(
            urls["access_token"],
            json={
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                **COPILOT_HEADERS,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if "access_token" in data:
            return data["access_token"]

        error = data.get("error", "")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error:
            raise RuntimeError(f"GitHub device flow failed: {error}")

    raise RuntimeError("GitHub device flow timed out.")


# ── Copilot token exchange ─────────────────────────────────────────────────────


def refresh_copilot_token(
    github_token: str,
    enterprise_domain: Optional[str] = None,
) -> CopilotCredentials:
    """Step 3: exchange a GitHub OAuth token for a short-lived Copilot API token."""
    domain = enterprise_domain or "github.com"
    urls = _get_urls(domain)

    resp = httpx.get(
        urls["copilot_token"],
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {github_token}",
            **COPILOT_HEADERS,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if "token" not in data or "expires_at" not in data:
        raise ValueError(f"Invalid Copilot token response: {data}")

    expires_at_ms = int(data["expires_at"]) * 1000 - _EXPIRY_BUFFER_MS

    return CopilotCredentials(
        github_token=github_token,
        copilot_token=data["token"],
        expires_at_ms=expires_at_ms,
        enterprise_domain=enterprise_domain,
    )


def is_token_expired(credentials: CopilotCredentials) -> bool:
    return time.time() * 1000 >= credentials.expires_at_ms


def ensure_valid_token(credentials: CopilotCredentials) -> CopilotCredentials:
    """Refresh the Copilot API token if it is expired or about to expire."""
    if is_token_expired(credentials):
        credentials = refresh_copilot_token(
            credentials.github_token,
            credentials.enterprise_domain,
        )
    return credentials


# ── Interactive login ──────────────────────────────────────────────────────────


def login(enterprise_domain: Optional[str] = None) -> CopilotCredentials:
    """
    Full interactive device-flow login.

    Prints the verification URL and user code, polls until authorized,
    saves the GitHub token to ~/.config/taui/config.toml, and returns
    ready-to-use CopilotCredentials.
    """
    domain = enterprise_domain or "github.com"
    device = start_device_flow(domain)

    print(f"\nOpen this URL in your browser: {device['verification_uri']}")
    print(f"Enter code:                    {device['user_code']}\n")

    github_token = poll_for_github_access_token(
        domain=domain,
        device_code=device["device_code"],
        interval_seconds=int(device["interval"]),
        expires_in=int(device["expires_in"]),
    )

    print("GitHub authorization successful. Fetching Copilot token...")
    credentials = refresh_copilot_token(github_token, enterprise_domain)
    print("Login successful.\n")

    config.save_provider_config("copilot", {"api_key": github_token})
    return credentials


# ── High-level credential getter ───────────────────────────────────────────────


def get_copilot_credentials() -> CopilotCredentials:
    """
    Load saved credentials or trigger interactive login.

    1. Load saved github_token from config.load_provider_config("copilot")["api_key"]
    2. If found: refresh_copilot_token(github_token) -> CopilotCredentials
    3. If not found or refresh fails: login() -> CopilotCredentials
    """
    saved = config.load_provider_config("copilot")
    if saved:
        github_token = saved.get("api_key")
        if github_token:
            print("Authenticating with saved credentials...")
            try:
                return refresh_copilot_token(github_token)
            except Exception as exc:
                print(f"Saved token invalid ({exc}). Re-authenticating...\n")

    return login()
