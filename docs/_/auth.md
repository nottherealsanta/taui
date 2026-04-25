# Auth System

## Overview

Two OAuth flows, one per provider. Both persist credentials to `~/.config/taui/config.toml` and refresh automatically before each LLM request.

| Provider | Flow | Token Lifetime | Persisted Fields |
|---|---|---|---|
| **Copilot** | GitHub Device Flow | ~30 min (copilot token) | `api_key` (GitHub OAuth token) |
| **Codex** | PKCE OAuth (browser redirect) | ~1 hour (access token) | `refresh_token`, `account_id` |

---

## Credential Lifecycle

```
Agent loop → provider.create_turn()
  → base class calls refresh_credentials()
    → provider checks token expiry
      → if valid: return
      → if expired: refresh (Copilot: exchange GitHub token → copilot token; Codex: refresh_token → new access_token)
      → if no token: trigger interactive login
  → build_request() uses fresh credentials
  → _do_stream() sends request
    → 401 → PermissionError (never retried)
```

Both providers hold credentials in-memory on the provider instance. `refresh_credentials()` is called before every `create_turn()` / `stream_text()` call in `base.py`.

---

## Copilot Auth (auth/copilot.py)

### Constants

```python
CLIENT_ID = base64.b64decode("SXYxLmI1MDdhMDhjODdlY2ZlOTg=").decode()
# Decodes to: "Iv1.b507a08c87ecfe98" — GitHub OAuth App client ID
```

The client ID is base64-encoded in source (common practice for GitHub Copilot clients — same in opencode and VS Code extension).

### Three-Step Flow

```
1. Device Flow      → user_code + device_code + verification_uri
2. Poll for Token   → github_token (long-lived GitHub OAuth token)
3. Exchange Token   → copilot_token (short-lived, ~30 min)
```

#### Step 1: start_device_flow()

```
POST https://github.com/login/device/code
Body: client_id=..., scope=
Headers: Accept: application/json

Response:
  device_code: "xxxx"        # used in polling
  user_code: "ABCD-1234"     # shown to user
  verification_uri: "https://github.com/login/device"
  interval: 5                # polling interval in seconds
```

Enterprise domains use: `https://{domain}/login/device/code`

#### Step 2: poll_for_github_access_token()

```
POST https://github.com/login/oauth/access_token
Body: client_id=..., device_code=..., grant_type=urn:ietf:params:oauth:grant-type:device_code
Headers: Accept: application/json

Poll every {interval} seconds until:
  error=authorization_pending → keep polling
  error=slow_down → increase interval by 5s
  error=expired_token → fail
  error=access_denied → fail
  access_token present → success, return "ghu_..." token
```

#### Step 3: refresh_copilot_token()

```
GET https://api.github.com/copilot_internal/v2/token
Headers: Authorization: token ghu_...

Response:
  token: "tid=...; exp=...; sku=...; proxy-ep=..."  # JWT-like semicolon format
  expires_at: 1234567890
  endpoints: {api: "...", proxy: "...", ...}
```

The copilot token is a semicolon-separated string (not a real JWT). It contains:
- `proxy-ep` — the proxy endpoint URL, used to derive the API base URL
- `exp` — expiration timestamp
- `sku` — subscription type

### Token Lifecycle

```
github_token (ghu_...)
  ├── lifetime: effectively permanent (until user revokes)
  ├── persisted as: [providers.copilot] api_key
  └── used for: exchanging to copilot_token

copilot_token (tid=...; exp=...; sku=...; proxy-ep=...)
  ├── lifetime: ~30 minutes
  ├── NOT persisted (in-memory only)
  ├── refreshed: when expires_at_ms - 5min < now
  └── used for: Authorization header in LLM requests
```

The `_EXPIRY_BUFFER_MS = 5 * 60 * 1000` (5 minutes) ensures the copilot token is refreshed before actual expiry.

### Base URL Extraction

`get_copilot_base_url(copilot_token)`:

```python
# Parse "proxy-ep=proxy.individual.githubcopilot.com" from token
# Replace "proxy." prefix with "api."
# Result: "https://api.individual.githubcopilot.com"
```

Enterprise fallback: if no `proxy-ep` found, uses `https://copilot-api.{enterprise_domain}` if enterprise domain is set, otherwise `https://api.individual.githubcopilot.com`.

### Header Sets

```python
COPILOT_HEADERS = {
    "User-Agent": "taui/0.1.0",
    "Editor-Version": "vscode/1.99.0",
    "Editor-Plugin-Version": "copilot/1.300.0",
    "Copilot-Integration-Id": "vscode-chat",
}

COPILOT_AGENT_HEADERS = {
    **COPILOT_HEADERS,
    "Copilot-Integration-Id": "copilot-chat",  # overrides vscode-chat
}
```

The `Copilot-Integration-Id` header controls which capabilities GitHub's proxy enables. `copilot-chat` enables tool calling.

### CopilotCredentials

```python
@dataclass
class CopilotCredentials:
    github_token: str           # ghu_... — long-lived
    copilot_token: str          # tid=...; — short-lived, refreshed
    expires_at_ms: int          # copilot token expiry (ms since epoch)
    enterprise_domain: str | None
```

### Entry Points

- `login()` — full interactive flow: device code → poll → exchange → save
- `get_copilot_credentials()` — load from config or trigger login. Returns `CopilotCredentials`.
- `ensure_valid_token(creds)` — refresh copilot token if within 5 min of expiry
- `refresh_copilot_token(github_token)` — exchange github token for fresh copilot token

---

## Codex Auth (auth/codex.py)

### Constants

```python
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPE = "openid profile email offline_access"
```

Same `CLIENT_ID` as opencode (`/tmp/opencode/packages/opencode/src/plugin/codex.ts`). Port 1455 is the local callback server.

### PKCE OAuth Flow

```
1. Generate PKCE    → verifier + challenge
2. Open Browser     → auth.openai.com/oauth/authorize?...
3. Wait for Callback → localhost:1455/auth/callback?code=...&state=...
4. Exchange Code    → access_token + refresh_token
5. Extract Account  → decode JWT → chatgpt_account_id
```

#### Step 1-2: login()

```python
verifier, challenge = generate_pkce()
state = secrets.token_urlsafe(32)

auth_url = f"{AUTHORIZE_URL}?" + urlencode({
    "client_id": CLIENT_ID,
    "response_type": "code",
    "redirect_uri": REDIRECT_URI,
    "scope": SCOPE,
    "state": state,
    "code_challenge": challenge,
    "code_challenge_method": "S256",
    "prompt": "login",
    "screen_hint": "login",
    "codex_cli_simplified_flow": "true",
    "originator": "taui",
})
```

`codex_cli_simplified_flow=true` and `originator=taui` are OpenAI-specific parameters that may affect the consent screen.

#### Step 3: race_callback_or_paste()

Opens browser and simultaneously:
1. Starts HTTP server on `localhost:1455` (daemon thread)
2. Polls stdin for manual URL paste (for headless environments)

Uses `select.select()` with 1-second granularity to check stdin without blocking. Timeout: 120 seconds.

The callback server validates the `state` parameter against the expected value to prevent CSRF.

#### Step 4: Token Exchange

```
POST https://auth.openai.com/oauth/token
Body: grant_type=authorization_code, client_id=..., code=..., 
      redirect_uri=..., code_verifier=...
Headers: Content-Type: application/x-www-form-urlencoded

Response:
  access_token: "eyJ..."     # JWT, ~1 hour lifetime
  refresh_token: "rt_..."    # long-lived, used for refresh
  token_type: "bearer"
  expires_in: 3600
```

**No `client_secret`** — PKCE replaces it. The `code_verifier` proves we're the same client that started the flow.

#### Step 5: Account ID Extraction

```python
def _decode_jwt_payload(token: str) -> dict:
    # Split JWT: header.payload.signature
    # Base64url decode the payload part
    # Parse as JSON

def _get_account_id(access_token: str) -> str | None:
    claims = _decode_jwt_payload(access_token)
    # Tries: "chatgpt_account_id", "https://api.openai.com/auth" nested dict
    return account_id
```

The `chatgpt_account_id` is sent as `chatgpt-account-id` header in Codex API requests. It identifies the ChatGPT subscription (Plus/Pro/Team) that grants model access.

### Token Refresh

```python
def refresh_access_token(refresh_token: str) -> CodexCredentials:
    resp = httpx.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    })
    # No client_secret needed — PKCE
    # OpenAI rotates refresh_token on each use → must persist the new one
    # Re-extracts account_id from new JWT
```

**Important:** OpenAI rotates the refresh token on each use. The new `refresh_token` must be persisted immediately, or the old one becomes invalid.

### Token Lifecycle

```
access_token (eyJ...)
  ├── lifetime: ~1 hour
  ├── NOT persisted (in-memory only)
  ├── refreshed: when expires_at_ms - 5min < now
  └── used for: Authorization header in Codex API requests

refresh_token (rt_...)
  ├── lifetime: long-lived (until rotation or revocation)
  ├── persisted as: [providers.codex] refresh_token
  ├── ROTATED on each use (must save the new one)
  └── used for: obtaining new access_token

account_id (UUID)
  ├── persisted as: [providers.codex] account_id
  └── used for: chatgpt-account-id header
```

### CodexCredentials

```python
@dataclass
class CodexCredentials:
    access_token: str         # JWT, ~1 hour
    refresh_token: str        # rt_..., rotated on each refresh
    expires_at_ms: int        # access token expiry (ms since epoch)
    account_id: str | None    # chatgpt_account_id from JWT claims
```

### Entry Points

- `login()` — full interactive PKCE flow: browser → callback → exchange → save
- `get_codex_credentials()` — load refresh_token from config, refresh, or trigger login
- `ensure_valid_token(creds)` — refresh if within 5 min of expiry
- `refresh_access_token(refresh_token)` — POST to token endpoint, get new tokens

---

## Shared PKCE Infrastructure (auth/pkce.py)

### generate_pkce()

```python
def generate_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(96)[:128]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge
```

Standard S256 PKCE per RFC 7636.

### wait_for_callback()

Starts a minimal `http.server.HTTPServer` on `localhost:{port}` in a daemon thread:
- GET handler at `/auth/callback` extracts `code` and `state` query params
- Validates `state` against expected value
- Returns `code` via shared `result` dict
- Shows success HTML page to the browser
- Server auto-shuts-down after receiving one request

### race_callback_or_paste()

```python
def race_callback_or_paste(auth_url: str, expected_state: str, port: int, timeout: int = 120) -> str | None:
    # 1. Start callback server (daemon thread)
    # 2. Open browser to auth_url (webbrowser.open)
    # 3. Print URL + instructions for manual paste
    # 4. Poll stdin with select.select(1s) for manual URL paste
    # 5. Check callback server result after each poll
    # 6. Return code from whichever source responds first
    # 7. Timeout after 120s → return None
```

This handles both GUI environments (browser opens, redirect lands on callback) and headless/SSH environments (user copies URL, authenticates elsewhere, pastes the callback URL back).

---

## Config Persistence (config.py)

### File Location

`~/.config/taui/config.toml`

### Format

```toml
[providers.copilot]
api_key = "ghu_UjrP8..."

[providers.codex]
refresh_token = "rt_QaPsj..."
account_id = "cf995405-..."
```

### API

```python
load_config() → dict                    # full TOML as dict, {} on error
save_provider_config(provider, data)     # merge into [providers.{provider}]
load_provider_config(provider) → dict    # read [providers.{provider}]
```

`save_provider_config` does a read-modify-write: loads existing config, merges new data into the provider section, writes back the full file.

### TOML Serializer

`_dict_to_toml()` is a minimal custom serializer. It handles:
- Strings (with `\` and `"` escaping)
- Integers, booleans
- Lists (inline format)
- Nested dicts (as TOML sections with `[headers]`)

No third-party dependency (no `tomli-w` or `tomlkit`). Uses stdlib `tomllib` for reading only.

---

## Auth Registry (auth/__init__.py)

```python
PROVIDER_NAMES = {
    "copilot": "GitHub Copilot",
    "codex": "OpenAI Codex (ChatGPT Plus/Pro)",
}

def get_credentials(provider: str):
    match provider:
        case "copilot": return get_copilot_credentials()
        case "codex":   return get_codex_credentials()
        case _: raise ValueError(f"Unknown provider: {provider!r}")
```

Factory function that dispatches to the right auth module. Used by `provider_probe.py`.

---

## Security Notes

1. **CLIENT_IDs are public** — both are OAuth "public clients" (no client_secret). This is by design for PKCE and device flow.

2. **PKCE prevents code interception** — the `code_verifier` proves we started the flow, so intercepting the `code` at the redirect URI is useless without the verifier.

3. **State parameter prevents CSRF** — `secrets.token_urlsafe(32)` generates 256-bit random state, validated by the callback server.

4. **No secrets in source** — CLIENT_IDs are not secrets (they're in every Copilot extension). The base64 encoding of Copilot's CLIENT_ID is obfuscation, not security.

5. **Refresh token rotation** — Codex rotates refresh tokens, so each token is single-use. If a refresh fails, the user must re-login.

6. **Local callback server** — binds to `localhost:1455` only. No external exposure. Server shuts down after one request.

7. **Token storage** — credentials stored in `~/.config/taui/config.toml` with standard file permissions. No encryption at rest (same as VS Code, opencode, etc.).
