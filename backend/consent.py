"""
Consent flow for human-in-the-loop mode.

The mailbox owner receives an email with a single "Review" link. The link carries
a signed, expiring token bound to one matter and one owner. Opening it shows a
review page; the decision itself is a POST from that page.

Why the decision is a POST and not a GET link: Microsoft Defender Safe Links and
other mail scanners open every link in an email to check it. A GET "approve" link
would be approved by the scanner before the owner ever saw it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import secrets
import time
from typing import Optional

from config import get_settings

_runtime_key = secrets.token_bytes(32)


def _key() -> bytes:
    k = get_settings().consent_signing_key
    return k.encode() if k else _runtime_key


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(matter_id: str, owner: str, ttl_hours: Optional[int] = None) -> str:
    ttl = ttl_hours if ttl_hours is not None else get_settings().consent_ttl_hours
    payload = {"m": matter_id, "o": owner.lower(), "exp": int(time.time()) + ttl * 3600}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


class TokenError(Exception):
    pass


def read_token(token: str) -> dict:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        raise TokenError("malformed")
    expected = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise TokenError("invalid signature")
    payload = json.loads(_unb64(body))
    if payload["exp"] < time.time():
        raise TokenError("expired")
    return payload


def review_url(token: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/consent/{token}"


# ---------------------------------------------------------------------------
# Owner-facing email
# ---------------------------------------------------------------------------

def consent_email_html(subject: str, sender: str, category: str, risk: str,
                       rationale: str, url: str) -> str:
    e = html.escape
    return f"""<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#14233a;max-width:560px">
<p>An email in your mailbox looks legally relevant. Nothing has been sent to Legal yet.</p>
<table style="border-collapse:collapse;margin:12px 0">
<tr><td style="padding:4px 12px 4px 0;color:#5a6b82">Subject</td><td><b>{e(subject)}</b></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#5a6b82">From</td><td>{e(sender)}</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#5a6b82">Suggested</td><td>{e(category)} · risk {e(risk)}</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#5a6b82">Why</td><td>{e(rationale)}</td></tr>
</table>
<p><a href="{e(url)}" style="display:inline-block;background:#14233a;color:#ffffff;padding:10px 18px;border-radius:6px;text-decoration:none">Review and decide</a></p>
<p style="color:#8794a6;font-size:12px">The suggestion is automated. Legal makes the final classification. This link expires after {get_settings().consent_ttl_hours} hours.</p>
</div>"""


def teams_card(subject: str, sender: str, category: str, risk: str, url: str) -> dict:
    """
    Adaptive Card for Teams. Uses Action.OpenUrl to the same review page, so it
    works without a bot. Deliver it with an Incoming Webhook / Workflows post, or
    a bot if one-click in-card actions are wanted later.
    """
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": "Forward this email to Legal?", "weight": "Bolder", "size": "Medium"},
            {"type": "FactSet", "facts": [
                {"title": "Subject", "value": subject},
                {"title": "From", "value": sender},
                {"title": "Suggested", "value": f"{category} · risk {risk}"},
            ]},
            {"type": "TextBlock", "text": "Nothing is sent until you approve.", "isSubtle": True, "wrap": True},
        ],
        "actions": [{"type": "Action.OpenUrl", "title": "Review and decide", "url": url}],
    }


# ---------------------------------------------------------------------------
# Review page
# ---------------------------------------------------------------------------

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Legal Cockpit · Review</title>
<style>
body{{margin:0;background:#eef1f5;color:#14233a;font:15px/1.5 "Segoe UI",system-ui,Arial,sans-serif}}
.c{{max-width:620px;margin:40px auto;padding:0 16px}}
.p{{background:#fff;border:1px solid #e1e6ee;border-radius:12px;padding:24px}}
h1{{font-size:20px;margin:0 0 4px}} .m{{color:#5a6b82;font-size:13px;margin:0}}
pre{{white-space:pre-wrap;font:inherit;background:#f6f8fb;border-radius:8px;padding:14px;margin:16px 0}}
.tag{{display:inline-block;font-size:12px;font-weight:600;padding:2px 10px;border-radius:999px;background:#f6ecd8;color:#8a5a14;margin-right:6px}}
.row{{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}}
button{{font:600 14px "Segoe UI",Arial,sans-serif;border-radius:7px;padding:10px 18px;cursor:pointer}}
.y{{background:#1d6e56;color:#fff;border:1px solid #1d6e56}} .n{{background:#fff;color:#5a6b82;border:1px solid #c9d1dd}}
.note{{color:#8794a6;font-size:12px;margin-top:16px}}
.done{{border-left:4px solid {accent};padding-left:14px}}
</style></head><body><div class="c"><div class="p">{content}</div></div></body></html>"""


def page(content: str, accent: str = "#1d6e56") -> str:
    return _PAGE.format(content=content, accent=accent)


def review_page(token: str, subject: str, sender: str, body: str,
                category: str, risk: str, rationale: str) -> str:
    e = html.escape
    content = f"""
<p class="m">Legal Cockpit · consent request</p>
<h1>{e(subject)}</h1>
<p class="m">From {e(sender)}</p>
<pre>{e(body[:4000])}</pre>
<p><span class="tag">{e(category)}</span><span class="tag">Risk: {e(risk)}</span></p>
<p class="m">{e(rationale)}</p>
<div class="row">
  <form method="post" action="/consent/{e(token)}/approve"><button class="y" type="submit">Approve and forward to Legal</button></form>
  <form method="post" action="/consent/{e(token)}/decline"><button class="n" type="submit">Decline</button></form>
</div>
<p class="note">The category and risk are automated suggestions. Legal makes the final classification. Your decision is recorded.</p>"""
    return page(content)


def result_page(title: str, message: str, ok: bool = True) -> str:
    accent = "#1d6e56" if ok else "#a32d2d"
    return page(f'<div class="done"><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></div>', accent)
