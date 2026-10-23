"""
Legal Cockpit API — what the frontend calls. Everything here requires sign-in.

What each role sees
-------------------
Matters
  super_admin  every matter in the Legal mailbox, including held (sensitive) ones
  admin        every forwarded matter; never held ones
  user         only matters they have a task on
  Nobody sees the content of emails that were dropped, declined or are still
  awaiting the owner's consent: those never reached Legal. They appear only as
  counts on the dashboard.

Tasks
  super_admin  all tasks; assigns to Admins
  admin        tasks assigned to them or their direct reports, and tasks they
               created; assigns to their direct reports
  user         tasks assigned to them; marks them done
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import auth
import main as core
from auth import User, current_user
from config import get_settings

router = APIRouter(prefix="/api", tags=["Legal Cockpit"])
STAFF = Depends(auth.require("super_admin", "admin"))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Task(BaseModel):
    id: str
    matter_id: str
    title: str
    assignee: str
    assigned_by: str
    due: date
    status: Literal["open", "done"] = "open"
    created_at: datetime
    done_at: Optional[datetime] = None


def is_overdue(t: Task) -> bool:
    return t.status == "open" and t.due < date.today()


class TaskOut(Task):
    overdue: bool
    assignee_name: str
    assigned_by_name: str
    matter_subject: str


class MatterSummary(BaseModel):
    id: str
    subject: str
    sender: str
    owner: str
    received: datetime
    status: core.Status
    sensitive: bool
    ai: Optional[core.Classification]
    legal: Optional[core.LegalClassification]
    classification_method: Optional[str] = None
    urgency_matches: list[str] = []
    stakeholder_matches: list[str] = []
    open_tasks: int
    overdue_tasks: int


class MatterDetail(MatterSummary):
    body: str
    attachments: list[core.Attachment]
    gate_matched: list[str]
    personal_exclusion_matches: list[str] = []
    negative_exclusion_matches: list[str] = []
    decided_by: Optional[str]
    mode: str
    tasks: list[TaskOut]


class ClassifyIn(BaseModel):
    category: str = Field(..., min_length=2, max_length=120)
    risk: Literal["High", "Medium", "Low", "Sensitive"]
    note: str = Field("", max_length=2000)


class TaskIn(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    assignee: str
    due: date


class TaskPatch(BaseModel):
    status: Literal["open", "done"]


# ---------------------------------------------------------------------------
# Visibility rules
# ---------------------------------------------------------------------------

LEGAL_STATUSES = (core.Status.forwarded, core.Status.held)


def _tasks() -> list[Task]:
    return list(core.TASKS.values())  # type: ignore[arg-type]


def can_see_task(user: User, t: Task) -> bool:
    if user.role == "super_admin":
        return True
    if user.role == "admin":
        reports = {u.email for u in auth.direct_reports(user.email)}
        return t.assignee == user.email or t.assignee in reports or t.assigned_by == user.email
    return t.assignee == user.email


def can_see_matter(user: User, m: core.Matter) -> bool:
    if m.status not in LEGAL_STATUSES:
        return False
    if m.status == core.Status.held:
        return user.role == "super_admin"
    if user.role in ("super_admin", "admin"):
        return True
    return any(t.matter_id == m.id and t.assignee == user.email for t in _tasks())


def assignable_to(user: User) -> list[User]:
    if user.role == "super_admin":
        return sorted((u for u in auth.DIRECTORY.values() if u.role == "admin"), key=lambda u: u.name)
    if user.role == "admin":
        return sorted((u for u in auth.direct_reports(user.email) if u.role == "user"), key=lambda u: u.name)
    return []


def _get_matter(user: User, matter_id: str) -> core.Matter:
    m = core.MATTERS.get(matter_id)
    if not m or not can_see_matter(user, m):
        raise HTTPException(404, "matter not found")
    return m


def _name(email: str) -> str:
    u = auth.DIRECTORY.get(email.lower())
    return u.name if u else email


def _task_out(t: Task) -> TaskOut:
    m = core.MATTERS.get(t.matter_id)
    return TaskOut(**t.model_dump(), overdue=is_overdue(t), assignee_name=_name(t.assignee),
                   assigned_by_name=_name(t.assigned_by),
                   matter_subject=m.email.subject if m else "")


def _summary(m: core.Matter, user: User) -> MatterSummary:
    tasks = [t for t in _tasks() if t.matter_id == m.id and can_see_task(user, t)]
    return MatterSummary(
        id=m.id, subject=m.email.subject, sender=m.email.sender, owner=m.email.owner,
        received=m.email.received_at or m.created_at, status=m.status, sensitive=m.sensitive,
        ai=m.classification, legal=m.legal_classification,
        classification_method=m.classification_method,
        urgency_matches=m.urgency_matches, stakeholder_matches=m.stakeholder_matches,
        open_tasks=sum(t.status == "open" for t in tasks),
        overdue_tasks=sum(is_overdue(t) for t in tasks),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/me")
def me(user: User = Depends(current_user)):
    s = get_settings()
    return {
        **user.model_dump(),
        "auth_mode": s.auth_mode,
        "can_assign_to": [u.model_dump() for u in assignable_to(user)],
        # In dev mode the frontend offers a switcher so a demo can show each role.
        "dev_users": [u.model_dump() for u in auth.DIRECTORY.values()] if s.auth_mode == "dev" else [],
    }


@router.get("/dashboard", dependencies=[STAFF])
def dashboard():
    base = core.dashboard()
    tasks = _tasks()
    week = date.today() + timedelta(days=7)
    classified = [m for m in core.MATTERS.values() if m.legal_classification and m.classification]
    agree = sum(m.legal_classification.risk == m.classification.risk for m in classified)
    return {
        **base,
        "tasks": {
            "open": sum(t.status == "open" for t in tasks),
            "overdue": sum(is_overdue(t) for t in tasks),
            "due_this_week": sum(t.status == "open" and t.due <= week for t in tasks),
            "done": sum(t.status == "done" for t in tasks),
        },
        "legal_classified": len(classified),
        "awaiting_legal_classification": sum(
            m.status == core.Status.forwarded and not m.legal_classification
            for m in core.MATTERS.values()),
        # How often Legal kept the AI's risk suggestion: the headline POC quality metric.
        "ai_risk_agreement": round(agree / len(classified), 2) if classified else None,
    }


@router.get("/matters", response_model=list[MatterSummary])
def list_matters(view: Literal["all", "unclassified", "held"] = "all",
                 user: User = Depends(current_user)):
    items = [m for m in core.MATTERS.values() if can_see_matter(user, m)]
    if view == "unclassified":
        items = [m for m in items if m.status == core.Status.forwarded and not m.legal_classification]
    elif view == "held":
        items = [m for m in items if m.status == core.Status.held]
    items.sort(key=lambda m: m.email.received_at or m.created_at, reverse=True)
    return [_summary(m, user) for m in items]


@router.get("/matters/{matter_id}", response_model=MatterDetail)
def get_matter(matter_id: str, user: User = Depends(current_user)):
    m = _get_matter(user, matter_id)
    tasks = sorted((t for t in _tasks() if t.matter_id == m.id and can_see_task(user, t)),
                   key=lambda t: t.due)
    return MatterDetail(
        **_summary(m, user).model_dump(),
        body=m.email.body, attachments=m.email.attachments, gate_matched=m.gate_matched,
        personal_exclusion_matches=m.personal_exclusion_matches,
        negative_exclusion_matches=m.negative_exclusion_matches,
        decided_by=m.decided_by, mode=m.mode, tasks=[_task_out(t) for t in tasks],
    )


@router.get("/matters/{matter_id}/audit")
def matter_audit(matter_id: str, user: User = Depends(auth.require("super_admin", "admin"))):
    _get_matter(user, matter_id)
    return [e for e in core.AUDIT if e["matter_id"] == matter_id]


@router.post("/matters/{matter_id}/classify", response_model=MatterDetail)
def classify(matter_id: str, body: ClassifyIn,
             user: User = Depends(auth.require("super_admin", "admin"))):
    m = _get_matter(user, matter_id)
    before = m.legal_classification.model_dump() if m.legal_classification else None
    m.legal_classification = core.LegalClassification(
        category=body.category.strip(), risk=body.risk, note=body.note.strip(),
        by=user.email, at=core.now())
    core.audit(m.id, user.email, "legal_classified",
               {"before": before, "after": body.model_dump(),
                "ai_suggested": m.classification.model_dump() if m.classification else None})
    return get_matter(matter_id, user)


@router.post("/matters/{matter_id}/tasks", response_model=TaskOut, status_code=201)
def create_task(matter_id: str, body: TaskIn, user: User = Depends(current_user)):
    m = _get_matter(user, matter_id)
    if m.status == core.Status.held:
        raise HTTPException(409, "Sensitive matters follow the restricted review process, not task assignment.")
    allowed = {u.email.lower() for u in assignable_to(user)}
    if not allowed:
        raise HTTPException(403, "your role cannot assign tasks")
    if body.assignee.lower() not in allowed:
        raise HTTPException(403, "you can only assign to "
                                 + ("Admins" if user.role == "super_admin" else "your direct reports"))
    t = Task(id=str(uuid.uuid4()), matter_id=m.id, title=body.title.strip(),
             assignee=body.assignee.lower(), assigned_by=user.email, due=body.due,
             created_at=core.now())
    core.TASKS[t.id] = t
    core.audit(m.id, user.email, "task_assigned",
               {"task": t.id, "to": t.assignee, "due": t.due.isoformat(), "title": t.title})
    return _task_out(t)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(scope: Literal["mine", "all"] = "mine", status: Optional[Literal["open", "done"]] = None,
               user: User = Depends(current_user)):
    items = [t for t in _tasks() if can_see_task(user, t)]
    if scope == "mine":
        items = [t for t in items if t.assignee == user.email]
    if status:
        items = [t for t in items if t.status == status]
    items.sort(key=lambda t: (t.status == "done", t.due))
    return [_task_out(t) for t in items]


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: str, body: TaskPatch, user: User = Depends(current_user)):
    t: Optional[Task] = core.TASKS.get(task_id)  # type: ignore[assignment]
    if not t or not can_see_task(user, t):
        raise HTTPException(404, "task not found")
    if user.email not in (t.assignee, t.assigned_by) and user.role != "super_admin":
        raise HTTPException(403, "only the assignee or the person who assigned it can update this task")
    t.status = body.status
    t.done_at = core.now() if body.status == "done" else None
    core.audit(t.matter_id, user.email, f"task_{body.status}", {"task": t.id})
    return _task_out(t)


# ---------------------------------------------------------------------------
# Demo data (dev mode only)
# ---------------------------------------------------------------------------

SAMPLE_EMAILS = [
    # (mode, owner decision, fields) — owner decision applies in human_in_loop mode
    ("auto", None, dict(
        sender="priya.menon@vendorco.example", owner="r.kapoor@example.com",
        subject="Notice of termination — Supply Agreement SA-4471",
        body="Further to repeated service failures, we intend to terminate Supply Agreement SA-4471 "
             "on 30 days' notice and will pursue liquidated damages under clause 14.2.")),
    ("human_in_loop", "approve", dict(
        sender="n.iyer@example.com", owner="a.fernandes@example.com",
        subject="Data incident affecting access-card logs",
        body="A misconfigured export may have exposed about 1,200 access-card records. "
             "We may have a regulatory notification obligation.")),
    ("human_in_loop", None, dict(
        sender="hr-intake@example.com", owner="hr.lead@example.com",
        subject="Formal complaint — workplace conduct",
        body="Submitting a formal complaint about conduct by a senior colleague, to be handled "
             "confidentially under the POSH process.")),
    ("human_in_loop", None, dict(
        sender="facilities@example.com", owner="s.rao@example.com",
        subject="Cafeteria menu — week of 5 Oct", body="Millet Monday returns by popular demand.")),
    ("human_in_loop", "approve", dict(
        sender="landlord.office@example.in", owner="s.rao@example.com",
        subject="गोदाम पट्टा — कानूनी नोटिस",
        body="यह गोदाम पट्टा अनुबंध के उल्लंघन के संबंध में कानूनी नोटिस है। 15 दिनों के भीतर उत्तर दें।")),
    ("auto", None, dict(
        sender="counsel@distributor.example", owner="r.kapoor@example.com",
        subject="Invocation of arbitration — Distribution Agreement",
        body="Our client invokes arbitration under clause 22 over unpaid commissions and the "
             "dispute regarding territory exclusivity.")),
    ("human_in_loop", None, dict(
        sender="ro.pcb@state.example", owner="a.fernandes@example.com",
        subject="Show cause notice — effluent discharge",
        body="Non-compliance with consent conditions was observed. Show cause why a penalty "
             "should not be imposed.")),
    ("human_in_loop", "decline", dict(
        sender="accounts@printshop.example", owner="s.rao@example.com",
        subject="Invoice dispute — brochure print run",
        body="We dispute the deduction made from invoice 8812 and request a call.")),
    ("auto", None, dict(
        sender="estate@landco.example", owner="s.rao@example.com",
        subject="ಕಾನೂನು ಸೂಚನೆ — ಗುತ್ತಿಗೆ ನವೀಕರಣ",
        body="ಗುತ್ತಿಗೆ ಒಪ್ಪಂದದ ನವೀಕರಣ ಕುರಿತು ಕಾನೂನು ಸೂಚನೆ. ದಯವಿಟ್ಟು 30 ದಿನಗಳಲ್ಲಿ ಉತ್ತರಿಸಿ.")),
    ("auto", None, dict(
        sender="comms@example.com", owner="r.kapoor@example.com",
        subject="Town hall on Friday", body="Join the quarterly town hall in the main auditorium.")),
]


@router.post("/dev/seed", dependencies=[Depends(auth.require("super_admin"))])
def seed(reset: bool = True):
    """Load fictitious sample data so the cockpit can be demoed. Dev mode only."""
    if get_settings().auth_mode != "dev":
        raise HTTPException(404, "not found")
    if reset:
        core.MATTERS.clear(); core.SEEN_KEYS.clear(); core.TASKS.clear(); core.AUDIT.clear()

    base_time = core.now() - timedelta(hours=len(SAMPLE_EMAILS) * 3)
    made: list[core.Matter] = []
    for i, (mode, decision, f) in enumerate(SAMPLE_EMAILS):
        m = core.process(core.EmailIn(message_id=f"<seed-{i}@demo>", mode=mode,
                                      received_at=base_time + timedelta(hours=i * 3),
                                      recipients=[f["owner"]], **f))
        if m.status == core.Status.pending_consent and decision:
            core.decide(m.id, decision == "approve", actor=m.email.owner)
        made.append(m)

    gc, arjun, sana = "gc@example.com", "arjun.rao@example.com", "sana.khan@example.com"
    by_subject = {m.email.subject.split(" —")[0]: m for m in made}
    today = date.today()

    def classify_as(key, category, risk, who, note=""):
        m = by_subject[key]
        m.legal_classification = core.LegalClassification(category=category, risk=risk, note=note,
                                                          by=who, at=core.now())
        core.audit(m.id, who, "legal_classified", {"after": {"category": category, "risk": risk}})

    def task(key, title, to, frm, due_days, done=False):
        m = by_subject[key]
        t = Task(id=str(uuid.uuid4()), matter_id=m.id, title=title, assignee=to, assigned_by=frm,
                 due=today + timedelta(days=due_days), created_at=core.now(),
                 status="done" if done else "open", done_at=core.now() if done else None)
        core.TASKS[t.id] = t
        core.audit(m.id, frm, "task_assigned", {"task": t.id, "to": to})

    classify_as("Notice of termination", "Contract dispute", "High", gc)
    classify_as("Data incident affecting access-card logs", "Regulatory / data incident", "High", gc,
                "Raised from the AI's Medium: notification clock may already be running.")
    classify_as("Invocation of arbitration", "Arbitration", "High", arjun)

    task("Notice of termination", "Review termination notice and advise on cure period", arjun, gc, -1)
    task("Notice of termination", "Pull performance records for SA-4471", "kavya.iyer@example.com", arjun, 3)
    task("Data incident affecting access-card logs", "Assess breach-notification obligation",
         sana, gc, 1)
    task("Data incident affecting access-card logs", "Draft regulator notification",
         "neha.pillai@example.com", sana, 4)
    task("Invocation of arbitration", "Shortlist arbitrators and confirm seat",
         "rohan.das@example.com", arjun, 9)
    task("Invocation of arbitration", "Acknowledge receipt to opposing counsel",
         "kavya.iyer@example.com", arjun, -3, done=True)

    return {"matters": len(core.MATTERS), "tasks": len(core.TASKS)}
