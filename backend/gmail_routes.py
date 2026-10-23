from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

import gmail_auth
import gmail
import auth

router = APIRouter(prefix="/gmail", tags=["Gmail"])
SUPER_ADMIN = Depends(auth.require("super_admin"))


class GmailMessageSummary(BaseModel):
    id: str
    thread_id: str | None = None
    message_id: str
    sender: str
    recipients: list[str]
    subject: str
    date: str
    snippet: str


@router.get("/status", dependencies=[SUPER_ADMIN])
def status():
    connected = gmail_auth.credentials() is not None
    profile = None
    if connected:
        try:
            profile = gmail.profile()
        except Exception:
            connected = False
    return {"configured": gmail_auth.configured(), "connected": connected,
            "email": profile.get("emailAddress") if profile else None}


@router.get("/auth", dependencies=[SUPER_ADMIN])
def auth_start():
    """Return the Google authorization URL; the frontend navigates the browser to it."""
    try:
        return {"authorization_url": gmail_auth.start_authorization()}
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@router.get("/callback")
def auth_callback(code: str = Query(...), state: str = Query(...)):
    try:
        gmail_auth.finish_authorization(code, state)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    from config import get_settings
    target = get_settings().origins[0] if get_settings().origins else "http://localhost:5173"
    return RedirectResponse(f"{target}/#gmail?connected=1")


@router.post("/disconnect", dependencies=[SUPER_ADMIN])
def disconnect():
    gmail_auth.disconnect()
    return {"ok": True}


@router.get("/messages", response_model=list[GmailMessageSummary], dependencies=[SUPER_ADMIN])
def messages(limit: int = Query(20, ge=1, le=100)):
    try:
        return gmail.list_messages(limit)
    except RuntimeError as exc:
        raise HTTPException(401, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Gmail API error: {exc}")


@router.post("/ingest/{message_id}", dependencies=[SUPER_ADMIN])
def ingest_message(message_id: str):
    # Import lazily to avoid a circular import during application startup.
    import main

    try:
        msg = gmail.fetch_message(message_id)
    except RuntimeError as exc:
        raise HTTPException(401, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Gmail API error: {exc}")

    email = main.EmailIn(
        message_id=msg.internet_message_id,
        sender=msg.sender,
        owner=msg.owner,
        recipients=msg.recipients,
        subject=msg.subject,
        body=msg.body,
        received_at=msg.received_at,
        attachments=[main.Attachment(filename=a.filename,
                                      text=main.extract_text(a.filename, a.content_type, a.data))
                     for a in msg.attachments],
        source_gmail_message_id=msg.message_id,
        source_gmail_owner=msg.owner,
    )
    return main.process(email)
