import re

import consent
import graph
import main
from conftest import email


def ingest(client, **over):
    r = client.post("/ingest", json=email(**over))
    assert r.status_code == 200, r.text
    return r.json()


# --- Modes -----------------------------------------------------------------

def test_human_in_loop_waits_for_consent(client):
    m = ingest(client)
    assert m["status"] == "pending_consent"
    assert m["classification"]["risk"] == "High"


def test_human_in_loop_approve_forwards(client):
    m = ingest(client)
    r = client.post(f"/matters/{m['id']}/approve", params={"approver": "agm.commercial@example.com"})
    assert r.json()["status"] == "forwarded"
    assert r.json()["decided_by"] == "agm.commercial@example.com"


def test_human_in_loop_decline(client):
    m = ingest(client)
    r = client.post(f"/matters/{m['id']}/decline", params={"approver": "agm.commercial@example.com"})
    assert r.json()["status"] == "declined"


def test_auto_mode_forwards_without_consent(client):
    m = ingest(client, mode="auto")
    assert m["status"] == "forwarded"
    assert m["decided_by"] == "auto"


def test_auto_mode_low_confidence_falls_back_to_consent(client, monkeypatch):
    monkeypatch.setattr(main.settings, "min_confidence", 0.95)
    m = ingest(client, mode="auto")
    assert m["status"] == "pending_consent"
    assert "low AI confidence" in m["reason"]


# --- Safeguards --------------------------------------------------------------

def test_sensitive_is_held_even_in_auto_mode(client):
    m = ingest(client, mode="auto", message_id="<posh@x>",
               subject="Formal complaint", body="Raising a POSH complaint confidentially.")
    assert m["status"] == "held"
    assert m["sensitive"] is True


def test_sensitive_term_needs_word_boundary(client):
    # "posher" must not trip the POSH rule.
    m = ingest(client, message_id="<p2@x>", subject="Office move",
               body="The new office is posher than the old one.")
    assert m["status"] == "dropped"


def test_non_legal_email_dropped_at_gate(client):
    m = ingest(client, message_id="<menu@x>", subject="Cafeteria menu", body="Millet Monday returns.")
    assert m["status"] == "dropped"


def test_hindi_keyword_passes_gate(client):
    m = ingest(client, message_id="<hi@x>", subject="सूचना", body="यह एक कानूनी नोटिस है।")
    assert m["status"] == "pending_consent"


def test_attachment_text_is_scanned(client):
    m = ingest(client, message_id="<att@x>", subject="Documents", body="Please see attached.",
               attachments=[{"filename": "notice.pdf", "text": "Legal notice under section 138."}])
    assert m["status"] == "pending_consent"


def test_same_email_to_two_owners_forwarded_once(client):
    a = ingest(client, mode="auto", owner="agm.one@example.com")
    b = ingest(client, mode="auto", owner="agm.two@example.com")
    assert a["status"] == "forwarded"
    assert b["status"] == "duplicate"


def test_legal_already_copied_is_excluded(client):
    m = ingest(client, recipients=["agm.commercial@example.com", "counsel@example.com"])
    assert m["status"] == "excluded"


def test_own_notifications_do_not_loop(client):
    m = ingest(client, message_id="<self@x>", sender="legal.intake@example.com",
               subject="[Legal Cockpit] Review needed before forwarding to Legal")
    assert m["status"] == "excluded"


def test_cannot_decide_twice(client):
    m = ingest(client)
    client.post(f"/matters/{m['id']}/approve", params={"approver": "x"})
    r = client.post(f"/matters/{m['id']}/decline", params={"approver": "x"})
    assert r.status_code == 409


# --- Consent links -----------------------------------------------------------

def test_consent_page_and_approve(client):
    m = ingest(client)
    token = consent.make_token(m["id"], m["email"]["owner"])
    page = client.get(f"/consent/{token}")
    assert page.status_code == 200 and "Approve and forward to Legal" in page.text
    r = client.post(f"/consent/{token}/approve")
    assert r.status_code == 200 and "Forwarded to Legal" in r.text
    assert main.MATTERS[m["id"]].status == main.Status.forwarded
    assert main.MATTERS[m["id"]].decided_by == m["email"]["owner"]


def test_consent_page_is_read_only(client):
    # Opening the link (as a mail scanner would) must not decide anything.
    m = ingest(client)
    token = consent.make_token(m["id"], m["email"]["owner"])
    client.get(f"/consent/{token}")
    assert main.MATTERS[m["id"]].status == main.Status.pending_consent


def test_tampered_token_rejected(client):
    m = ingest(client)
    token = consent.make_token(m["id"], m["email"]["owner"])
    bad = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    assert client.post(f"/consent/{bad}/approve").status_code == 403


def test_expired_token_rejected(client):
    m = ingest(client)
    token = consent.make_token(m["id"], m["email"]["owner"], ttl_hours=-1)
    assert client.post(f"/consent/{token}/approve").status_code == 403


def test_token_for_other_owner_rejected(client):
    m = ingest(client)
    token = consent.make_token(m["id"], "someone.else@example.com")
    assert client.post(f"/consent/{token}/approve").status_code == 404


def test_teams_card_has_review_link(client):
    m = ingest(client)
    card = client.get(f"/matters/{m['id']}/teams-card").json()
    assert card["type"] == "AdaptiveCard"
    assert re.search(r"/consent/[\w-]+\.[\w-]+$", card["actions"][0]["url"])


# --- Graph webhook -----------------------------------------------------------

def test_webhook_validation_echo(client):
    r = client.post("/webhook/graph?validationToken=abc123")
    assert r.status_code == 200 and r.text == "abc123"


def test_webhook_ignores_bad_client_state(client, monkeypatch):
    called = []
    monkeypatch.setattr(main, "handle_notification", lambda res: called.append(res))
    r = client.post("/webhook/graph", json={"value": [
        {"clientState": "wrong", "resource": "Users/u1/Messages/m1"}]})
    assert r.status_code == 202 and called == []


def test_webhook_fetches_and_processes(client, monkeypatch):
    fetched = graph.FetchedMessage(
        user_id="u1", message_id="graph-id-1", internet_message_id="<wh@vendor>",
        owner="agm.security@example.com", sender="regulator@gov.example",
        recipients=["agm.security@example.com"], subject="Show cause notice",
        body="Non-compliance found; penalty may apply.", received_at=None,
        attachments=[graph.FetchedAttachment("note.txt", "text/plain", b"regulatory follow-up")],
    )
    monkeypatch.setattr(graph, "fetch_message", lambda resource: fetched)
    r = client.post("/webhook/graph", json={"value": [
        {"clientState": "test-state", "resource": "Users/u1/Messages/graph-id-1"}]})
    assert r.status_code == 202
    [m] = main.MATTERS.values()
    assert m.status == main.Status.pending_consent
    assert m.email.source_message_id == "graph-id-1"
    assert m.email.attachments[0].text == "regulatory follow-up"


# --- Dashboard ---------------------------------------------------------------

def test_dashboard_counts(client):
    ingest(client, mode="auto")                                                       # forwarded
    ingest(client, message_id="<p@x>", subject="Complaint", body="POSH matter.")      # held
    ingest(client, message_id="<c@x>", subject="Menu", body="Lunch is served.")       # dropped
    ingest(client, message_id="<q@x>", subject="Dispute", body="A dispute arose.")    # pending
    d = client.get("/dashboard").json()
    assert d["forwarded_to_legal"] == 1
    assert d["held_sensitive"] == 1
    assert d["dropped_at_gate"] == 1
    assert d["awaiting_consent"] == 1
    assert d["total"] == 4


def test_personal_exclusion_precedes_legal_classification(client):
    m = ingest(client, message_id="<personal-legal@x>", subject="Home loan legal notice",
               body="My mortgage documents need review under the agreement.")
    assert m["status"] == "excluded"
    assert m["classification"] is None
    assert "home loan" in m["personal_exclusion_matches"]


def test_negative_exclusion_suppresses_legal_keyword(client):
    m = ingest(client, message_id="<newsletter-legal@x>", subject="Legal compliance newsletter",
               body="Newsletter: regulatory compliance webinar next week.")
    assert m["status"] == "dropped"
    assert m["classification"] is None
    assert m["negative_exclusion_matches"]


def test_document_taxonomy_and_urgency_are_logged(client):
    m = ingest(client, message_id="<show-cause@x>", subject="Show cause notice — CAR compliance",
               body="Final notice. Explain within 7 days why penalty should not be imposed.", mode="auto")
    assert m["classification"]["category"] == "Litigation, High Legal Risk" or m["classification"]["category"] == "Compliance & Regulatory"
    assert m["urgency_matches"]
    assert m["classification_method"] == "rules_fallback"
    assert any("urgency:" in x for x in m["gate_matched"])
