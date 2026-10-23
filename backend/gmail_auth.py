"""Google OAuth helpers for the Gmail POC, implemented with httpx only."""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from config import get_settings

settings = get_settings()

print("\n" + "=" * 60)
print("🔍 GMAIL OAUTH DEBUG")
print("=" * 60)

# print("Client ID      :", settings.gmail_client_id)
print("Redirect URI   :", repr(settings.gmail_redirect_uri))
print("Token Path     :", settings.gmail_token_path)
# print("Scopes         :", SCOPES)

print("=" * 60 + "\n")
# flow = InstalledAppFlow.from_client_config(...)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_oauth_state: str | None = None


def configured() -> bool:
    s = get_settings()
    return bool(s.gmail_client_id and s.gmail_client_secret and s.gmail_redirect_uri)


def start_authorization() -> str:
    global _oauth_state
    s = get_settings()
    if not configured():
        raise RuntimeError("Gmail OAuth is not configured")
    _oauth_state = secrets.token_urlsafe(32)
    params = {
        "client_id": s.gmail_client_id,
        "redirect_uri": s.gmail_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": _oauth_state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def finish_authorization(code: str, state: str) -> dict:
    global _oauth_state
    if not _oauth_state or state != _oauth_state:
        raise ValueError("invalid OAuth state")
    s = get_settings()
    r = httpx.post(TOKEN_ENDPOINT, data={
        "code": code,
        "client_id": s.gmail_client_id,
        "client_secret": s.gmail_client_secret,
        "redirect_uri": s.gmail_redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=30)
    r.raise_for_status()
    data = r.json()
    data["expires_at"] = int(time.time()) + int(data.get("expires_in", 3600))
    _save(data)
    _oauth_state = None
    return data


def _load() -> dict | None:
    path = Path(get_settings().gmail_token_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(data: dict) -> None:
    path = Path(get_settings().gmail_token_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def access_token() -> str | None:
    data = _load()
    if not data:
        return None
    if data.get("access_token") and time.time() < float(data.get("expires_at", 0)) - 60:
        return data["access_token"]
    refresh = data.get("refresh_token")
    if not refresh:
        return None
    s = get_settings()
    r = httpx.post(TOKEN_ENDPOINT, data={
        "client_id": s.gmail_client_id,
        "client_secret": s.gmail_client_secret,
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    }, timeout=30)
    r.raise_for_status()
    fresh = r.json()
    data.update(fresh)
    data["expires_at"] = int(time.time()) + int(fresh.get("expires_in", 3600))
    _save(data)
    return data.get("access_token")


def credentials() -> dict | None:
    token = access_token()
    return {"access_token": token} if token else None


def require_access_token() -> str:
    token = access_token()
    if not token:
        raise RuntimeError("Gmail is not connected. Open /gmail/auth first.")
    return token


def disconnect() -> None:
    path = Path(get_settings().gmail_token_path)
    if path.exists():
        path.unlink()
