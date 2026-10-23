"""
Microsoft Graph client: token, message fetch, forward, send, subscriptions.

Uses the client-credentials flow (application permissions). The app registration
needs Mail.Read (fetch) and Mail.Send (forward/notify), and MUST be scoped with an
Exchange application access policy to the in-scope mailboxes only — see README.
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from config import get_settings

GRAPH = "https://graph.microsoft.com/v1.0"
# Mailbox message subscriptions max out just under 3 days (4230 minutes).
MAX_SUBSCRIPTION_MINUTES = 4200

_token: dict = {"value": None, "expires": 0.0}


def token() -> str:
    """Client-credentials token, cached until shortly before expiry."""
    s = get_settings()
    if _token["value"] and time.time() < _token["expires"] - 120:
        return _token["value"]
    r = httpx.post(
        f"https://login.microsoftonline.com/{s.graph_tenant_id}/oauth2/v2.0/token",
        data={
            "client_id": s.graph_client_id,
            "client_secret": s.graph_client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    _token["value"] = data["access_token"]
    _token["expires"] = time.time() + int(data.get("expires_in", 3600))
    return _token["value"]


def _h() -> dict:
    return {"Authorization": f"Bearer {token()}"}


@dataclass
class FetchedAttachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class FetchedMessage:
    user_id: str                 # mailbox owner's Entra object id
    message_id: str              # Graph id, unique per mailbox
    internet_message_id: str     # RFC 5322 id, shared across recipients -> dedup key
    owner: str                   # owner's SMTP address
    sender: str
    recipients: list[str]
    subject: str
    body: str
    received_at: Optional[datetime]
    attachments: list[FetchedAttachment] = field(default_factory=list)


def fetch_message(resource: str) -> FetchedMessage:
    """
    Resolve a change-notification resource ("Users/{uid}/Messages/{mid}") into
    the full message, its owner and its file attachments.
    """
    parts = resource.strip("/").split("/")
    user_id, msg_id = parts[1], parts[3]

    with httpx.Client(timeout=30, headers=_h()) as c:
        m = c.get(
            f"{GRAPH}/users/{user_id}/messages/{msg_id}",
            params={"$select": "id,internetMessageId,subject,body,from,toRecipients,"
                               "ccRecipients,receivedDateTime,hasAttachments"},
            headers={"Prefer": 'outlook.body-content-type="text"'},
        )
        m.raise_for_status()
        msg = m.json()

        u = c.get(f"{GRAPH}/users/{user_id}", params={"$select": "mail,userPrincipalName"})
        u.raise_for_status()
        user = u.json()

        atts: list[FetchedAttachment] = []
        if msg.get("hasAttachments"):
            a = c.get(f"{GRAPH}/users/{user_id}/messages/{msg_id}/attachments")
            a.raise_for_status()
            for item in a.json().get("value", []):
                if item.get("@odata.type") == "#microsoft.graph.fileAttachment":
                    atts.append(FetchedAttachment(
                        filename=item.get("name", "attachment"),
                        content_type=item.get("contentType", "application/octet-stream"),
                        data=base64.b64decode(item.get("contentBytes", "")),
                    ))

    def addr(r):
        return (r.get("emailAddress") or {}).get("address", "")

    received = msg.get("receivedDateTime")
    return FetchedMessage(
        user_id=user_id,
        message_id=msg["id"],
        internet_message_id=msg.get("internetMessageId") or msg["id"],
        owner=user.get("mail") or user.get("userPrincipalName", ""),
        sender=addr(msg.get("from") or {}),
        recipients=[addr(r) for r in (msg.get("toRecipients", []) + msg.get("ccRecipients", []))],
        subject=msg.get("subject") or "",
        body=(msg.get("body") or {}).get("content", ""),
        received_at=datetime.fromisoformat(received.replace("Z", "+00:00")) if received else None,
        attachments=atts,
    )


def forward(user_id: str, message_id: str, to: str, comment: str) -> None:
    """Forward the original message (attachments intact) from the owner's mailbox."""
    r = httpx.post(
        f"{GRAPH}/users/{user_id}/messages/{message_id}/forward",
        headers=_h(),
        json={"comment": comment, "toRecipients": [{"emailAddress": {"address": to}}]},
        timeout=30,
    )
    r.raise_for_status()


def send_mail(sender: str, to: str, subject: str, html: str) -> None:
    r = httpx.post(
        f"{GRAPH}/users/{sender}/sendMail",
        headers=_h(),
        json={"message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }, "saveToSentItems": False},
        timeout=30,
    )
    r.raise_for_status()


def create_subscription(user: str, notification_url: str, client_state: str) -> dict:
    """Subscribe to new mail in one mailbox's Inbox."""
    expiry = datetime.now(timezone.utc) + timedelta(minutes=MAX_SUBSCRIPTION_MINUTES)
    r = httpx.post(
        f"{GRAPH}/subscriptions",
        headers=_h(),
        json={
            "changeType": "created",
            "notificationUrl": notification_url,
            "resource": f"users/{user}/mailFolders('Inbox')/messages",
            "expirationDateTime": expiry.isoformat().replace("+00:00", "Z"),
            "clientState": client_state,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def renew_subscription(subscription_id: str) -> dict:
    expiry = datetime.now(timezone.utc) + timedelta(minutes=MAX_SUBSCRIPTION_MINUTES)
    r = httpx.patch(
        f"{GRAPH}/subscriptions/{subscription_id}",
        headers=_h(),
        json={"expirationDateTime": expiry.isoformat().replace("+00:00", "Z")},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
