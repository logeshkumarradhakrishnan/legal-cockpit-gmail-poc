"""Role and visibility rules for the Legal Cockpit API (dev sign-in)."""
from datetime import date, timedelta

import pytest

import main
from conftest import email

GC, ARJUN, SANA = "gc@example.com", "arjun.rao@example.com", "sana.khan@example.com"
KAVYA, NEHA = "kavya.iyer@example.com", "neha.pillai@example.com"


def as_(who):
    return {"X-Dev-User": who}


@pytest.fixture
def forwarded(client):
    r = client.post("/ingest", json=email(mode="auto"), headers=as_(GC))
    assert r.json()["status"] == "forwarded"
    return r.json()["id"]


@pytest.fixture
def held(client):
    r = client.post("/ingest", json=email(message_id="<posh@x>", subject="Complaint",
                                          body="POSH complaint."), headers=as_(GC))
    return r.json()["id"]


def due(days=3):
    return (date.today() + timedelta(days=days)).isoformat()


def test_me_reports_role_and_who_i_can_assign(client):
    me = client.get("/api/me", headers=as_(ARJUN)).json()
    assert me["role"] == "admin"
    assert {u["email"] for u in me["can_assign_to"]} == {KAVYA, "rohan.das@example.com"}


def test_unknown_user_rejected(client):
    assert client.get("/api/me", headers=as_("stranger@example.com")).status_code == 401


def test_operational_endpoints_need_super_admin(client):
    assert client.get("/dashboard", headers=as_(ARJUN)).status_code == 403


# --- Matter visibility -------------------------------------------------------

def test_held_matter_visible_to_super_admin_only(client, forwarded, held):
    assert {m["id"] for m in client.get("/api/matters", headers=as_(GC)).json()} == {forwarded, held}
    assert {m["id"] for m in client.get("/api/matters", headers=as_(ARJUN)).json()} == {forwarded}
    assert client.get(f"/api/matters/{held}", headers=as_(ARJUN)).status_code == 404


def test_pending_and_declined_content_never_shown(client):
    p = client.post("/ingest", json=email(message_id="<p@x>"), headers=as_(GC)).json()
    assert p["status"] == "pending_consent"
    assert client.get("/api/matters", headers=as_(GC)).json() == []
    assert client.get(f"/api/matters/{p['id']}", headers=as_(GC)).status_code == 404


def test_user_sees_only_matters_with_their_task(client, forwarded):
    assert client.get("/api/matters", headers=as_(KAVYA)).json() == []
    client.post(f"/api/matters/{forwarded}/tasks", headers=as_(ARJUN),
                json={"title": "Pull records", "assignee": KAVYA, "due": due()})
    assert [m["id"] for m in client.get("/api/matters", headers=as_(KAVYA)).json()] == [forwarded]


# --- Classification ------------------------------------------------------------

def test_admin_classifies_and_ai_suggestion_is_kept(client, forwarded):
    r = client.post(f"/api/matters/{forwarded}/classify", headers=as_(ARJUN),
                    json={"category": "Contract dispute", "risk": "Medium", "note": "Cure period applies"})
    d = r.json()
    assert d["legal"]["risk"] == "Medium" and d["legal"]["by"] == ARJUN
    assert d["ai"]["risk"] == "High"
    actions = [e["action"] for e in client.get(f"/api/matters/{forwarded}/audit", headers=as_(GC)).json()]
    assert "legal_classified" in actions


def test_user_cannot_classify(client, forwarded):
    r = client.post(f"/api/matters/{forwarded}/classify", headers=as_(KAVYA),
                    json={"category": "X dispute", "risk": "Low"})
    assert r.status_code == 403


# --- Task assignment rules -------------------------------------------------

def test_super_admin_assigns_to_admin_only(client, forwarded):
    ok = client.post(f"/api/matters/{forwarded}/tasks", headers=as_(GC),
                     json={"title": "Advise", "assignee": ARJUN, "due": due()})
    assert ok.status_code == 201
    no = client.post(f"/api/matters/{forwarded}/tasks", headers=as_(GC),
                     json={"title": "Advise", "assignee": KAVYA, "due": due()})
    assert no.status_code == 403


def test_admin_assigns_only_to_own_reports(client, forwarded):
    ok = client.post(f"/api/matters/{forwarded}/tasks", headers=as_(ARJUN),
                     json={"title": "Research", "assignee": KAVYA, "due": due()})
    assert ok.status_code == 201
    no = client.post(f"/api/matters/{forwarded}/tasks", headers=as_(ARJUN),
                     json={"title": "Research", "assignee": NEHA, "due": due()})   # Sana's report
    assert no.status_code == 403


def test_user_cannot_assign(client, forwarded):
    client.post(f"/api/matters/{forwarded}/tasks", headers=as_(ARJUN),
                json={"title": "Research", "assignee": KAVYA, "due": due()})
    r = client.post(f"/api/matters/{forwarded}/tasks", headers=as_(KAVYA),
                    json={"title": "Help", "assignee": "rohan.das@example.com", "due": due()})
    assert r.status_code == 403


def test_no_tasks_on_held_matters(client, held):
    r = client.post(f"/api/matters/{held}/tasks", headers=as_(GC),
                    json={"title": "Look", "assignee": ARJUN, "due": due()})
    assert r.status_code == 409


def test_task_visibility_by_role(client, forwarded):
    client.post(f"/api/matters/{forwarded}/tasks", headers=as_(GC),
                json={"title": "Task A", "assignee": SANA, "due": due()})
    client.post(f"/api/matters/{forwarded}/tasks", headers=as_(ARJUN),
                json={"title": "Task B", "assignee": KAVYA, "due": due()})
    titles = lambda who: {t["title"] for t in client.get("/api/tasks?scope=all", headers=as_(who)).json()}
    assert titles(GC) == {"Task A", "Task B"}
    assert titles(ARJUN) == {"Task B"}          # own report's task, not Sana's
    assert titles(SANA) == {"Task A"}
    assert titles(KAVYA) == {"Task B"}
    assert titles(NEHA) == set()


def test_assignee_completes_task_and_overdue_flag(client, forwarded):
    t = client.post(f"/api/matters/{forwarded}/tasks", headers=as_(ARJUN),
                    json={"title": "Late", "assignee": KAVYA, "due": due(-2)}).json()
    assert t["overdue"] is True
    done = client.patch(f"/api/tasks/{t['id']}", headers=as_(KAVYA), json={"status": "done"}).json()
    assert done["status"] == "done" and done["overdue"] is False
    # Someone unrelated cannot touch it
    assert client.patch(f"/api/tasks/{t['id']}", headers=as_(NEHA),
                        json={"status": "open"}).status_code == 404


# --- Dashboard and demo data ---------------------------------------------------

def test_dashboard_for_staff_only(client, forwarded):
    assert client.get("/api/dashboard", headers=as_(KAVYA)).status_code == 403
    d = client.get("/api/dashboard", headers=as_(ARJUN)).json()
    assert d["forwarded_to_legal"] == 1 and d["awaiting_legal_classification"] == 1


def test_seed_builds_a_demoable_state(client):
    r = client.post("/api/dev/seed", headers=as_(GC)).json()
    assert r["matters"] == 10
    d = client.get("/api/dashboard", headers=as_(GC)).json()
    assert d["forwarded_to_legal"] == 5
    assert d["held_sensitive"] == 1
    assert d["dropped_at_gate"] == 2
    assert d["awaiting_consent"] == 1
    assert d["by_status"]["declined"] == 1
    assert d["tasks"]["overdue"] == 1
    assert d["ai_risk_agreement"] is not None


def test_seed_unavailable_outside_dev(client, monkeypatch):
    monkeypatch.setattr(main.settings, "auth_mode", "entra")
    assert client.post("/api/dev/seed").status_code in (401, 404)
