"""Small Gmail REST API adapter used by the Legal Cockpit POC."""
from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx

import gmail_auth

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"


@dataclass
class GmailAttachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class GmailMessage:
    message_id: str
    internet_message_id: str
    owner: str
    sender: str
    recipients: list[str]
    subject: str
    body: str
    received_at: Optional[datetime]
    attachments: list[GmailAttachment] = field(default_factory=list)


def _request(method: str, path: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {gmail_auth.require_access_token()}"
    r = httpx.request(method, f"{GMAIL}{path}", headers=headers, timeout=30, **kwargs)
    r.raise_for_status()
    return r.json() if r.content else {}


def profile() -> dict:
    return _request("GET", "/profile")


def list_messages(max_results: int = 20) -> list[dict]:
    result = _request("GET", "/messages", params={"labelIds": "INBOX", "maxResults": max_results})
    items = []
    for item in result.get("messages", []):
        msg = _request("GET", f"/messages/{item['id']}", params={
            "format": "metadata",
            "metadataHeaders": ["From", "To", "Cc", "Subject", "Date", "Message-ID"],
        })
        headers = _headers(msg)
        items.append({
            "id": msg["id"],
            "thread_id": msg.get("threadId"),
            "message_id": headers.get("message-id") or msg["id"],
            "sender": headers.get("from", ""),
            "recipients": _split_addresses(headers.get("to", ""), headers.get("cc", "")),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": msg.get("snippet", ""),
        })
    return items


def fetch_message(message_id: str) -> GmailMessage:
    msg = _request("GET", f"/messages/{message_id}", params={"format": "full"})
    headers = _headers(msg)
    body, attachment_refs = _walk_parts(msg.get("payload", {}))
    attachments: list[GmailAttachment] = []
    for ref in attachment_refs:
        data = _request("GET", f"/messages/{message_id}/attachments/{ref['attachment_id']}").get("data", "")
        attachments.append(GmailAttachment(
            filename=ref["filename"],
            content_type=ref["content_type"],
            data=base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)),
        ))
    received = None
    if headers.get("date"):
        try:
            received = parsedate_to_datetime(headers["date"])
        except (TypeError, ValueError, OverflowError):
            pass
    owner = profile().get("emailAddress", "")
    return GmailMessage(
        message_id=msg["id"],
        internet_message_id=headers.get("message-id") or msg["id"],
        owner=owner,
        sender=headers.get("from", ""),
        recipients=_split_addresses(headers.get("to", ""), headers.get("cc", "")),
        subject=headers.get("subject", ""),
        body=body,
        received_at=received,
        attachments=attachments,
    )


def send_mail(to: str, subject: str, html_body: str, sender: str | None = None) -> dict:
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    if sender:
        message["From"] = sender
    message.set_content(_html_to_text(html_body))
    message.add_alternative(html_body, subtype="html")
    return _send_raw(message)


def forward_message(source: GmailMessage, to: str, comment: str) -> dict:
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = f"[Legal Cockpit] {source.subject}"
    message.set_content(f"{comment}\n\n--- Original email ---\n{source.body}")
    for attachment in source.attachments:
        maintype, _, subtype = attachment.content_type.partition("/")
        message.add_attachment(attachment.data, maintype=maintype or "application",
                               subtype=subtype or "octet-stream", filename=attachment.filename)
    return _send_raw(message)


def _send_raw(message: EmailMessage) -> dict:
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return _request("POST", "/messages/send", json={"raw": raw})


def _headers(msg: dict) -> dict[str, str]:
    return {h["name"].lower(): h.get("value", "") for h in msg.get("payload", {}).get("headers", [])}


def _split_addresses(*values: str) -> list[str]:
    return [part.strip() for value in values for part in re.split(r",\s*", value or "") if part.strip()]


def _decode(data: str) -> str:
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    return raw.decode("utf-8", errors="replace")


def _walk_parts(part: dict) -> tuple[str, list[dict]]:
    attachments: list[dict] = []
    plain: list[str] = []
    html_parts: list[str] = []

    def visit(p: dict) -> None:
        filename = p.get("filename") or ""
        body = p.get("body", {})
        mime = p.get("mimeType", "")
        if filename and body.get("attachmentId"):
            attachments.append({"filename": filename, "content_type": mime or "application/octet-stream",
                                "attachment_id": body["attachmentId"]})
            return
        if body.get("data"):
            text = _decode(body["data"])
            if mime == "text/plain": plain.append(text)
            elif mime == "text/html": html_parts.append(text)
        for child in p.get("parts", []) or []: visit(child)

    visit(part)
    body = "\n\n".join(plain).strip()
    if not body and html_parts: body = _html_to_text("\n".join(html_parts))
    return body, attachments


def _html_to_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</p\s*>", "\n\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(re.sub(r"\s+", " ", value)).strip()
