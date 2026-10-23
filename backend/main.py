"""
Legal Cockpit — email triage service (FastAPI).

Pipeline
--------
    Graph webhook / POST /ingest
        │
        ├─ excluded: sent by this service, or Legal already copied
        ├─ duplicate: same internet message id already processed
        ▼
    Stage 1: keyword gate (deterministic, multilingual, body + attachments)
        │ no match ───────────────▶ dropped (logged)
        ▼
    Stage 2: AI intent (Azure OpenAI) — suggests category + risk only
        ▼
    Stage 3: disposition
        • sensitive (POSH / whistleblower)  ─▶ HELD, in both modes
        • mode = "auto"                     ─▶ forward now, notify owner
        • mode = "human_in_loop"            ─▶ owner gets a review link → approve → forward

Run:  uvicorn main:app --reload        Docs: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import auth
import consent
import graph
import legal_classification as legal_rules
from config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("legal-cockpit")
settings = get_settings()

if not settings.consent_signing_key:
    log.warning("CONSENT_SIGNING_KEY not set: using a random key; consent links break on restart.")

if settings.auth_mode == "dev":
    log.warning("AUTH_MODE=dev: sign-in is simulated. Never deploy this setting.")
auth.load_directory()

app = FastAPI(
    title="Legal Cockpit — Triage Service",
    version="0.3.0",
    description="AI-assisted email triage for Legal, with automatic and human-in-the-loop modes.",
)
print("CORS allowed_origins:", settings.allowed_origins)
print("CORS origins:", settings.origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
SUPER_ADMIN = Depends(auth.require("super_admin"))

SUBJECT_PREFIX = "[Legal Cockpit]"
Mode = Literal["human_in_loop", "auto"]

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Attachment(BaseModel):
    filename: str
    text: Optional[str] = None


class EmailIn(BaseModel):
    message_id: str = Field(..., description="Internet message id (shared across recipients) — dedup key")
    sender: str
    owner: str = Field(..., description="Mailbox owner whose consent is sought in human_in_loop mode")
    recipients: list[str] = []
    subject: str
    body: str
    attachments: list[Attachment] = []
    received_at: Optional[datetime] = None
    mode: Optional[Mode] = Field(None, description="Overrides the server default for this item")
    # Set when the email came from Graph, so forwarding keeps the original + attachments.
    source_user_id: Optional[str] = None
    source_message_id: Optional[str] = None
    # Gmail source metadata for the POC.
    source_gmail_message_id: Optional[str] = None
    source_gmail_owner: Optional[str] = None


class Status(str, Enum):
    scanned = "scanned"
    excluded = "excluded"
    duplicate = "duplicate"
    dropped = "dropped"
    pending_consent = "pending_consent"
    forwarded = "forwarded"
    declined = "declined"
    held = "held"


class Classification(BaseModel):
    category: str
    risk: str
    rationale: str
    confidence: float


class LegalClassification(BaseModel):
    """Legal's final call. Separate from the AI suggestion, which is kept for comparison."""
    category: str
    risk: Literal["High", "Medium", "Low", "Sensitive"]
    note: str = ""
    by: str
    at: datetime


class Matter(BaseModel):
    id: str
    email: EmailIn
    mode: Mode
    status: Status
    reason: Optional[str] = None
    gate_matched: list[str] = []
    personal_exclusion_matches: list[str] = []
    negative_exclusion_matches: list[str] = []
    urgency_matches: list[str] = []
    stakeholder_matches: list[str] = []
    classification_method: Optional[str] = None
    sensitive: bool = False
    classification: Optional[Classification] = None
    legal_classification: Optional[LegalClassification] = None
    created_at: datetime
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Stores — in-memory for the POC; Cosmos DB / Azure SQL in production
# ---------------------------------------------------------------------------

MATTERS: dict[str, Matter] = {}
SEEN_KEYS: set[str] = set()
TASKS: dict[str, "object"] = {}   # id -> legal_api.Task
AUDIT: list[dict] = []


def now() -> datetime:
    return datetime.now(timezone.utc)


def audit(matter_id: str, actor: str, action: str, detail=None) -> None:
    entry = {"ts": now().isoformat(), "matter_id": matter_id, "actor": actor,
             "action": action, "detail": detail}
    AUDIT.append(entry)
    log.info("AUDIT %s %s %s", matter_id, actor, action)
    try:
        with open(settings.audit_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except OSError as exc:
        log.warning("audit write failed: %s", exc)


# ---------------------------------------------------------------------------
# Stage 1 — deterministic keyword gate
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return legal_rules.normalize(text)


def _has(term: str, text: str) -> bool:
    return legal_rules.contains(term, text)


def keyword_gate(email: EmailIn) -> tuple[bool, list[str], bool]:
    """Run the deterministic keyword gate and log every matching category."""
    result = legal_rules.analyze(email)

    print("\n" + "=" * 90)
    print("[LEGAL COCKPIT] KEYWORD GATE")
    print(f"[EMAIL] Subject: {email.subject}")
    print(f"[EMAIL] Sender: {email.sender}")

    matched = []

    for category, terms in result["category_matches"].items():
        for term in terms:
            matched.append(f"{category}: {term}")
            print(f"[KEYWORD MATCH] '{term}' -> CATEGORY: {category}")

    for term in result["urgency_matches"]:
        matched.append(f"urgency: {term}")
        print(f"[URGENCY MATCH] '{term}' -> PRIORITY/RISK SIGNAL")

    for name in result["stakeholder_matches"]:
        matched.append(f"stakeholder: {name}")
        print(f"[STAKEHOLDER MATCH] '{name}' -> STAKEHOLDER SIGNAL")

    for term in result["sensitive_matches"]:
        matched.append(f"sensitive: {term}")
        print(f"[SENSITIVE MATCH] '{term}' -> RESTRICTED REVIEW")

    for term in result["legacy_legal_matches"]:
        matched.append(f"legacy: {term}")
        print(f"[LEGACY LEGAL MATCH] '{term}' -> LEGAL GATE SIGNAL")

    passed = bool(
        result["category_matches"]
        or result["legacy_legal_matches"]
        or result["sensitive_matches"]
    )

    print(f"[KEYWORD GATE RESULT] {'PASS' if passed else 'FAIL'}")
    print(f"[SUGGESTED CATEGORY FROM RULES] {result.get('suggested_category')}")
    print(f"[ALL MATCHES] {matched}")
    print("=" * 90 + "\n")

    return passed, matched, bool(result["sensitive_matches"])


def extract_text(filename: str, content_type: str, data: bytes) -> str:
    """Attachment text: plain text decoded directly, everything else via Document Intelligence."""
    if content_type.startswith("text/"):
        return data.decode("utf-8", errors="ignore")
    if not (settings.doc_intelligence_endpoint and settings.doc_intelligence_api_key):
        return ""
    try:
        base = settings.doc_intelligence_endpoint.rstrip("/")
        key = {"Ocp-Apim-Subscription-Key": settings.doc_intelligence_api_key}
        r = httpx.post(
            f"{base}/documentintelligence/documentModels/prebuilt-read:analyze",
            params={"api-version": "2024-11-30"},
            headers={**key, "Content-Type": "application/octet-stream"},
            content=data, timeout=60,
        )
        r.raise_for_status()
        op = r.headers["Operation-Location"]
        for _ in range(30):
            time.sleep(1)
            p = httpx.get(op, headers=key, timeout=30).json()
            if p.get("status") == "succeeded":
                return p["analyzeResult"].get("content", "")
            if p.get("status") == "failed":
                break
    except Exception as exc:
        log.warning("Document Intelligence failed for %s: %s", filename, exc)
    return ""


# ---------------------------------------------------------------------------
# Stage 2 — AI intent, suggestion only
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a triage assistant for an aviation company's Legal team. Use the email subject, "
    "sender, body, and extracted attachment text to classify intent. Prefer the best-fit category "
    "from this taxonomy: " + "; ".join(legal_rules.CATEGORY_KEYWORDS.keys()) + ". "
    "Treat the supplied keyword matches as signals, not proof; consider context and intent. "
    "Urgency terms such as 'final notice', 'within 7 days', and 'failure to respond' increase priority. "
    "Return STRICT JSON with keys: category, risk ('High','Medium','Low'), rationale (one sentence), "
    "confidence (0-1). You only suggest; a lawyer makes the final classification. Do not add keys."
)

_LAST_CLASSIFICATION_METHOD = "rules_fallback"


def classify(
    email: EmailIn,
    sensitive: bool,
    analysis: Optional[dict] = None,
) -> Classification:
    """Classify an email and log the actual execution path."""
    global _LAST_CLASSIFICATION_METHOD

    analysis = analysis or legal_rules.analyze(email)

    if sensitive:
        _LAST_CLASSIFICATION_METHOD = "rules_fallback"
        print(
            "[CLASSIFICATION PATH] DETERMINISTIC RESTRICTED HANDLING"
            " — Azure OpenAI not called for sensitive email"
        )
        return Classification(
            category="POSH / whistleblower — sensitive",
            risk="Sensitive",
            rationale="Matched a sensitive-matter term; restricted handling.",
            confidence=0.99,
        )

    if settings.openai_configured:
        print("[CLASSIFICATION PATH] Attempting Azure OpenAI call")
        try:
            result = _classify_azure_openai(email, analysis)
            _LAST_CLASSIFICATION_METHOD = "azure_openai"

            print("[CLASSIFICATION PATH] AZURE OPENAI SUCCESS")
            print(f"[AI CATEGORY] {result.category}")
            print(f"[AI RISK] {result.risk}")
            print(f"[AI CONFIDENCE] {result.confidence}")
            print(f"[AI RATIONALE] {result.rationale}")

            return result

        except Exception as exc:
            _LAST_CLASSIFICATION_METHOD = "rules_fallback"
            log.exception(
                "Azure OpenAI classification failed; "
                "using deterministic fallback. Error: %s",
                exc,
            )
            print("[CLASSIFICATION PATH] AZURE OPENAI FAILED")
            print("[CLASSIFICATION PATH] SWITCHING TO DETERMINISTIC FALLBACK")

    else:
        _LAST_CLASSIFICATION_METHOD = "rules_fallback"
        print("[CLASSIFICATION PATH] Azure OpenAI not configured")
        print("[CLASSIFICATION PATH] USING DETERMINISTIC FALLBACK")

    result = _classify_fallback(email, analysis)

    print("[CLASSIFICATION PATH] DETERMINISTIC FALLBACK USED")
    print(f"[FALLBACK CATEGORY] {result.category}")
    print(f"[FALLBACK RISK] {result.risk}")
    print(f"[FALLBACK CONFIDENCE] {result.confidence}")
    print(f"[FALLBACK RATIONALE] {result.rationale}")

    return result



def _classify_azure_openai(email: EmailIn, analysis: Optional[dict] = None) -> Classification:
    from openai import AzureOpenAI

    client = AzureOpenAI(api_key=settings.azure_openai_api_key,
                         api_version=settings.azure_openai_api_version,
                         azure_endpoint=settings.azure_openai_endpoint)
    attach = "\n\n".join(f"[Attachment: {a.filename}]\n{(a.text or '')[:6000]}" for a in email.attachments)
    analysis = analysis or legal_rules.analyze(email)
    context = (f"Deterministic category keyword matches: {analysis['category_matches']}\n"
               f"Suggested category: {analysis['suggested_category']}\n"
               f"Urgency matches: {analysis['urgency_matches']}\n"
               f"Stakeholder-name matches: {analysis['stakeholder_matches']}\n")
    resp = client.chat.completions.create(
        model=settings.azure_openai_deployment, temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": f"{context}Subject: {email.subject}\nSender: {email.sender}\n\n{email.body[:12000]}\n\n{attach}"}],
    )
    d = json.loads(resp.choices[0].message.content)
    risk = str(d.get("risk", "Medium")).capitalize()
    return Classification(category=str(d.get("category", "Uncategorised")),
                          risk=risk if risk in ("High", "Medium", "Low") else "Medium",
                          rationale=str(d.get("rationale", "")),
                          confidence=max(0.0, min(1.0, float(d.get("confidence", 0.6)))))


def _classify_fallback(email: EmailIn, analysis: Optional[dict] = None) -> Classification:
    analysis = analysis or legal_rules.analyze(email)
    category = analysis.get("suggested_category") or "General legal"
    if category in ("Litigation, High Legal Risk", "Tax & Statutory Demand", "Passenger Legal Risk"):
        risk, confidence = "High", 0.82
    elif category in ("Compliance & Regulatory", "International Aviation & Regulatory",
                      "Contract Management, Legal Review Required", "Attorney-Client Privileged"):
        risk, confidence = "Medium", 0.76
    else:
        risk, confidence = "Low", 0.74
    urgency = analysis.get("urgency_matches", [])
    if urgency:
        risk = {"Low": "Medium", "Medium": "High", "High": "High"}[risk]
    rationale = f"Best-fit category from document keyword and intent signals: {category}."
    if urgency:
        rationale += " Urgency modifier matched: " + ", ".join(urgency[:3]) + "."
    if analysis.get("stakeholder_matches"):
        rationale += " Sender matched stakeholder names: " + ", ".join(analysis["stakeholder_matches"][:3]) + "."
    return Classification(category=category, risk=risk, rationale=rationale, confidence=confidence)


# ---------------------------------------------------------------------------
# Outbound actions (Graph, or logged when Graph is not configured)
# ---------------------------------------------------------------------------

def forward_to_legal(m: Matter) -> None:
    c = m.classification
    note = (f"{SUBJECT_PREFIX} Suggested: {c.category} · risk {c.risk}. "
            f"Decided by: {m.decided_by}. Matter: {m.id}") if c else f"{SUBJECT_PREFIX} Matter {m.id}"
    if m.email.source_gmail_message_id:
        import gmail
        source = gmail.fetch_message(m.email.source_gmail_message_id)
        gmail.forward_message(source, settings.legal_mailbox, note)
        return
    if not settings.graph_configured:
        log.info("STUB forward → %s | %s", settings.legal_mailbox, m.email.subject)
        return
    if m.email.source_user_id and m.email.source_message_id:
        graph.forward(m.email.source_user_id, m.email.source_message_id, settings.legal_mailbox, note)
    else:
        graph.send_mail(settings.legal_mailbox, settings.legal_mailbox,
                        f"{SUBJECT_PREFIX} {m.email.subject}",
                        f"<p>{note}</p><pre>{m.email.body}</pre>")


def mail_owner(m: Matter, subject: str, html: str) -> None:
    if m.email.source_gmail_message_id:
        import gmail
        gmail.send_mail(m.email.owner, f"{SUBJECT_PREFIX} {subject}", html)
        return
    if not settings.graph_configured:
        log.info("STUB mail → %s | %s", m.email.owner, subject)
        return
    graph.send_mail(settings.legal_mailbox, m.email.owner, f"{SUBJECT_PREFIX} {subject}", html)


def request_consent(m: Matter) -> str:
    token = consent.make_token(m.id, m.email.owner)
    url = consent.review_url(token)
    c = m.classification
    mail_owner(m, "Review needed before forwarding to Legal",
               consent.consent_email_html(m.email.subject, m.email.sender,
                                          c.category, c.risk, c.rationale, url))
    return url


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def dedup_key(email: EmailIn) -> str:
    # The internet message id is identical in every recipient's copy, so a mail
    # sent to five AGMs is forwarded to Legal once.
    return hashlib.sha256(email.message_id.strip().lower().encode()).hexdigest()


def exclusion_reason(email: EmailIn) -> Optional[str]:
    sender = email.sender.lower()
    if sender == settings.legal_mailbox.lower() or email.subject.startswith(SUBJECT_PREFIX):
        return "sent by Legal Cockpit"          # prevents notification loops
    team = settings.legal_team_set
    if team and (sender in team or team & {r.lower() for r in email.recipients}):
        return "Legal team already on the email"
    return None


def process(email: EmailIn) -> Matter:
    mode = email.mode or settings.default_mode
    m = Matter(id=str(uuid.uuid4()), email=email, mode=mode, status=Status.scanned, created_at=now())
    MATTERS[m.id] = m
    audit(m.id, "system", "scanned", {"mode": mode})

    reason = exclusion_reason(email)
    if reason:
        m.status, m.reason = Status.excluded, reason
        audit(m.id, "system", "excluded", reason)
        return m

    key = dedup_key(email)
    if key in SEEN_KEYS:
        m.status, m.reason = Status.duplicate, "already processed"
        audit(m.id, "system", "duplicate")
        return m
    SEEN_KEYS.add(key)

    rule_analysis = legal_rules.analyze(email)
    
    print("\n[PIPELINE] Starting legal email analysis")
    print(f"[PIPELINE] Subject: {email.subject}")
    print(f"[PIPELINE] Personal exclusions: {rule_analysis['personal_exclusions']}")
    print(f"[PIPELINE] Negative exclusions: {rule_analysis['negative_exclusions']}")

    if rule_analysis["personal_exclusions"]:
        print("[PIPELINE DECISION] EXCLUDED — personal-matter rule matched")

    if rule_analysis["negative_exclusions"]:
        print("[PIPELINE DECISION] DROPPED — negative/exclusion rule matched")


    m.personal_exclusion_matches = rule_analysis["personal_exclusions"]
    m.negative_exclusion_matches = rule_analysis["negative_exclusions"]
    m.urgency_matches = rule_analysis["urgency_matches"]
    m.stakeholder_matches = rule_analysis["stakeholder_matches"]

    # Personal exclusions run before all legal classification, as required by the source document.
    if rule_analysis["personal_exclusions"]:
        m.status = Status.excluded
        m.reason = "personal-matter exclusion: " + ", ".join(rule_analysis["personal_exclusions"])
        audit(m.id, "system", "personal_exclusion", {"matches": rule_analysis["personal_exclusions"]})
        return m
    # Negative/exclusion signals suppress classification even when legal terms also match.
    if rule_analysis["negative_exclusions"]:
        m.status = Status.dropped
        m.reason = "negative/exclusion keyword: " + ", ".join(rule_analysis["negative_exclusions"])
        audit(m.id, "system", "negative_exclusion", {"matches": rule_analysis["negative_exclusions"]})
        return m

    passed, matched, sensitive = keyword_gate(email)
    m.gate_matched, m.sensitive = matched, sensitive
    if not passed:
        m.status, m.reason = Status.dropped, "no keyword match"
        audit(m.id, "system", "dropped", {"classification_method": "keyword_gate"})
        return m

    
    m.classification = classify(email, sensitive, rule_analysis)
    m.classification_method = _LAST_CLASSIFICATION_METHOD

    print("\n[FINAL CLASSIFICATION SUMMARY]")
    print(f"[METHOD ACTUALLY USED] {m.classification_method}")
    print(f"[FINAL CATEGORY] {m.classification.category}")
    print(f"[FINAL RISK] {m.classification.risk}")
    print(f"[FINAL CONFIDENCE] {m.classification.confidence}")
    print(f"[FINAL RATIONALE] {m.classification.rationale}")

    audit(m.id, "ai" if m.classification_method == "azure_openai" else "rules", "classified",
          {**m.classification.model_dump(), "classification_method": m.classification_method,
           "matched_categories": list(rule_analysis["category_matches"]),
           "urgency_matches": rule_analysis["urgency_matches"],
           "stakeholder_matches": rule_analysis["stakeholder_matches"]})

    if sensitive:
        m.status, m.reason = Status.held, "sensitive matter — restricted handling"
        audit(m.id, "system", "held")
        return m

    low_confidence = m.classification.confidence < settings.min_confidence
    if mode == "auto" and not low_confidence:
        m.decided_by, m.decided_at = "auto", now()
        forward_to_legal(m)
        m.status = Status.forwarded
        audit(m.id, "system", "forwarded_auto")
        mail_owner(m, "Forwarded to Legal",
                   f"<p>An email in your mailbox, <b>{email.subject}</b>, was forwarded to Legal for review.</p>")
        return m

    # human_in_loop — or auto mode with a low-confidence suggestion
    m.status = Status.pending_consent
    m.reason = "low AI confidence — consent required" if mode == "auto" else None
    request_consent(m)
    audit(m.id, "system", "awaiting_consent", {"owner": email.owner})
    return m


def decide(matter_id: str, approve: bool, actor: str) -> Matter:
    m = MATTERS.get(matter_id)
    if not m:
        raise HTTPException(404, "matter not found")
    if m.status != Status.pending_consent:
        raise HTTPException(409, f"matter is already '{m.status.value}'")
    m.decided_by, m.decided_at = actor, now()
    if approve:
        forward_to_legal(m)
        m.status = Status.forwarded
        audit(matter_id, actor, "approved_and_forwarded")
    else:
        m.status = Status.declined
        audit(matter_id, actor, "declined")
    return m


# ---------------------------------------------------------------------------
# Graph webhook
# ---------------------------------------------------------------------------

def handle_notification(resource: str) -> None:
    """Runs in the background so the webhook answers Graph within its timeout."""
    try:
        msg = graph.fetch_message(resource)
    except Exception as exc:
        log.error("fetch failed for %s: %s", resource, exc)
        return
    email = EmailIn(
        message_id=msg.internet_message_id,
        sender=msg.sender, owner=msg.owner, recipients=msg.recipients,
        subject=msg.subject, body=msg.body, received_at=msg.received_at,
        attachments=[Attachment(filename=a.filename,
                                text=extract_text(a.filename, a.content_type, a.data))
                     for a in msg.attachments],
        source_user_id=msg.user_id, source_message_id=msg.message_id,
    )
    process(email)


@app.post("/webhook/graph")
async def graph_webhook(request: Request, background: BackgroundTasks):
    # Subscription validation: Graph sends ?validationToken=... and expects it echoed.
    vt = request.query_params.get("validationToken")
    if vt:
        return Response(content=vt, media_type="text/plain")

    payload = await request.json()
    for note in payload.get("value", []):
        if note.get("clientState") != settings.graph_webhook_client_state:
            log.warning("ignored notification with bad clientState")
            continue
        resource = note.get("resource", "")
        if resource:
            background.add_task(handle_notification, resource)
    return Response(status_code=202)


class SubscriptionIn(BaseModel):
    mailbox: str = Field(..., description="Address or object id of an in-scope mailbox")


@app.post("/subscriptions", dependencies=[SUPER_ADMIN])
def create_subscription(body: SubscriptionIn):
    """Subscribe one in-scope mailbox. Call once per AGM+ mailbox."""
    if not settings.graph_configured:
        raise HTTPException(503, "Graph is not configured")
    url = f"{settings.public_base_url.rstrip('/')}/webhook/graph"
    return graph.create_subscription(body.mailbox, url, settings.graph_webhook_client_state)


@app.post("/subscriptions/{subscription_id}/renew", dependencies=[SUPER_ADMIN])
def renew_subscription(subscription_id: str):
    """Mailbox subscriptions expire in under 3 days; renew from a daily timer job."""
    if not settings.graph_configured:
        raise HTTPException(503, "Graph is not configured")
    return graph.renew_subscription(subscription_id)


# ---------------------------------------------------------------------------
# Owner consent pages (human-in-the-loop)
# ---------------------------------------------------------------------------

def _matter_from_token(token: str) -> tuple[Matter, dict]:
    try:
        claims = consent.read_token(token)
    except consent.TokenError as exc:
        raise HTTPException(403, f"link not valid: {exc}")
    m = MATTERS.get(claims["m"])
    if not m or m.email.owner.lower() != claims["o"]:
        raise HTTPException(404, "matter not found")
    return m, claims


@app.get("/consent/{token}", response_class=HTMLResponse)
def consent_page(token: str):
    try:
        m, _ = _matter_from_token(token)
    except HTTPException as exc:
        return HTMLResponse(consent.result_page("Link not valid", exc.detail, ok=False), exc.status_code)
    if m.status != Status.pending_consent:
        return HTMLResponse(consent.result_page("Already decided",
                                                f"This email is already {m.status.value.replace('_', ' ')}."))
    c = m.classification
    return HTMLResponse(consent.review_page(token, m.email.subject, m.email.sender, m.email.body,
                                            c.category, c.risk, c.rationale))


def _consent_action(token: str, approve: bool) -> HTMLResponse:
    try:
        m, claims = _matter_from_token(token)
        decide(m.id, approve, actor=claims["o"])
    except HTTPException as exc:
        return HTMLResponse(consent.result_page("Not recorded", str(exc.detail), ok=False), exc.status_code)
    if approve:
        return HTMLResponse(consent.result_page("Forwarded to Legal",
                                                "Thank you. Legal will review and classify it."))
    return HTMLResponse(consent.result_page("Declined", "The email was not forwarded. Your decision is recorded."))


@app.post("/consent/{token}/approve", response_class=HTMLResponse)
def consent_approve(token: str):
    return _consent_action(token, True)


@app.post("/consent/{token}/decline", response_class=HTMLResponse)
def consent_decline(token: str):
    return _consent_action(token, False)


@app.get("/matters/{matter_id}/teams-card", dependencies=[SUPER_ADMIN])
def teams_card(matter_id: str):
    """Adaptive Card JSON for posting the consent request into Teams."""
    m = MATTERS.get(matter_id)
    if not m or m.status != Status.pending_consent:
        raise HTTPException(404, "no pending consent for this matter")
    c = m.classification
    url = consent.review_url(consent.make_token(m.id, m.email.owner))
    return consent.teams_card(m.email.subject, m.email.sender, c.category, c.risk, url)


# ---------------------------------------------------------------------------
# Operational API
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "default_mode": settings.default_mode,
            "graph": "configured" if settings.graph_configured else "stubbed",
            "gmail": "connected" if settings.gmail_connected else ("configured" if settings.gmail_configured else "stubbed"),
            "openai": "configured" if settings.openai_configured else "stubbed"}


@app.post("/ingest", response_model=Matter, dependencies=[SUPER_ADMIN])
def ingest(email: EmailIn):
    """Submit one email directly (testing, demos, or a non-Graph source)."""
    return process(email)


@app.get("/matters", response_model=list[Matter], dependencies=[SUPER_ADMIN])
def list_matters(status: Optional[Status] = Query(None)):
    items = [m for m in MATTERS.values() if status is None or m.status == status]
    return sorted(items, key=lambda m: m.created_at, reverse=True)


@app.get("/matters/{matter_id}", response_model=Matter, dependencies=[SUPER_ADMIN])
def get_matter(matter_id: str):
    m = MATTERS.get(matter_id)
    if not m:
        raise HTTPException(404, "matter not found")
    return m


@app.post("/matters/{matter_id}/approve", response_model=Matter, dependencies=[SUPER_ADMIN])
def approve(matter_id: str, approver: str = Query(..., description="Who is approving")):
    """Admin path for consent (e.g. from a Teams bot). Owners use the emailed link."""
    return decide(matter_id, True, approver)


@app.post("/matters/{matter_id}/decline", response_model=Matter, dependencies=[SUPER_ADMIN])
def decline(matter_id: str, approver: str = Query(...)):
    return decide(matter_id, False, approver)


@app.get("/dashboard", dependencies=[SUPER_ADMIN])
def dashboard():
    by_status: dict[str, int] = {s.value: 0 for s in Status}
    risk: dict[str, int] = {}
    category: dict[str, int] = {}
    for m in MATTERS.values():
        by_status[m.status.value] += 1
        if m.classification and m.status in (Status.forwarded, Status.held):
            risk[m.classification.risk] = risk.get(m.classification.risk, 0) + 1
            category[m.classification.category] = category.get(m.classification.category, 0) + 1
    return {
        "total": len(MATTERS),
        "forwarded_to_legal": by_status["forwarded"],
        "held_sensitive": by_status["held"],
        "dropped_at_gate": by_status["dropped"],
        "awaiting_consent": by_status["pending_consent"],
        "by_status": by_status,
        "by_risk": risk,
        "by_category": category,
    }


# Legal Cockpit API for the frontend (imported last: it uses the names above)
import legal_api  # noqa: E402

app.include_router(legal_api.router)

import gmail_routes  # noqa: E402
app.include_router(gmail_routes.router)
