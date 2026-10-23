import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { actionLabel, dueLabel, fmtDate, fmtDateTime, isoDatePlus, roleLabel } from "../format";
import type { AuditEntry, MatterDetail, Me, Risk } from "../types";

const RISKS: Risk[] = ["High", "Medium", "Low", "Sensitive"];
const CATEGORIES = [
  "Contract dispute", "Arbitration", "Regulatory / data incident", "Regulatory / compliance",
  "Employment", "Property / lease", "Intellectual property", "General legal",
];

interface Props {
  id: string;
  me: Me;
  version: number;
  onChanged: () => void;
  onClose: () => void;
}

export default function MatterPanel({ id, me, version, onChanged, onClose }: Props) {
  const [m, setM] = useState<MatterDetail | null>(null);
  const [auditLog, setAuditLog] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const staff = me.role !== "user";

  useEffect(() => {
    setError(null);
    api.matter(id).then(setM).catch((e) => setError(e.message));
    if (staff) api.audit(id).then(setAuditLog).catch(() => setAuditLog([]));
  }, [id, version, staff]);

  if (error) return <div className="card"><div className="notice error">{error}</div></div>;
  if (!m) return <div className="card empty">Loading…</div>;

  const how = m.mode === "auto" && m.decided_by === "auto"
    ? "Forwarded automatically"
    : m.decided_by ? `Approved by mailbox owner (${m.decided_by})` : "Held at intake";

  return (
    <div className="stack">
      <article className="card">
        <div className="card-h">
          <button className="btn ghost small back" onClick={onClose}>← All matters</button>
          {m.status === "held" && <span className="chip risk-Sensitive">Held · sensitive</span>}
        </div>
        <h2 className="subject">{m.subject}</h2>
        <dl className="meta">
          <div><dt>From</dt><dd>{m.sender}</dd></div>
          <div><dt>Mailbox</dt><dd>{m.owner}</dd></div>
          <div><dt>Received</dt><dd>{fmtDateTime(m.received)}</dd></div>
          <div><dt>Route</dt><dd>{how}</dd></div>
        </dl>
        <pre className="body">{m.body}</pre>
        {m.attachments.length > 0 && (
          <p className="attach">Attachments: {m.attachments.map((a) => <span key={a.filename}>{a.filename}</span>)}</p>
        )}
        {m.gate_matched.length > 0 && (
          <p className="fine">Matched terms: {m.gate_matched.join(", ")}</p>
        )}
      </article>

      <ClassificationCard m={m} canEdit={staff && (m.status !== "held" || me.role === "super_admin")}
                          onSaved={(updated) => { setM(updated); onChanged(); }} />

      <TasksCard m={m} me={me} onChanged={onChanged} />

      {staff && auditLog && (
        <section className="card">
          <div className="card-h"><h2>Audit trail</h2></div>
          <ol className="timeline">
            {auditLog.map((e, i) => (
              <li key={i}>
                <span className="t-when">{fmtDateTime(e.ts)}</span>
                <span className="t-what">{actionLabel(e.action)}</span>
                <span className="t-who">{e.actor}</span>
              </li>
            ))}
          </ol>
        </section>
      )}
      {me.role === "user" && (
        <p className="fine pad">You see this matter because a task on it is assigned to you ({roleLabel[me.role]}).</p>
      )}
    </div>
  );
}

function ClassificationCard({ m, canEdit, onSaved }: {
  m: MatterDetail; canEdit: boolean; onSaved: (m: MatterDetail) => void;
}) {
  const [editing, setEditing] = useState(!m.legal && canEdit);
  const [category, setCategory] = useState(m.legal?.category ?? m.ai?.category ?? "");
  const [risk, setRisk] = useState<Risk>(m.legal?.risk ?? m.ai?.risk ?? "Medium");
  const [note, setNote] = useState(m.legal?.note ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (category.trim().length < 2) { setError("Enter a category."); return; }
    setSaving(true);
    setError(null);
    try {
      const updated = await api.classify(m.id, { category: category.trim(), risk, note });
      setEditing(false);
      onSaved(updated);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const changed = m.legal && m.ai && (m.legal.risk !== m.ai.risk || m.legal.category !== m.ai.category);

  return (
    <section className="card">
      <div className="card-h"><h2>Classification</h2></div>
      <div className="class-grid">
        <div className="class-box ai">
          <h3 className="mini">AI suggestion</h3>
          {m.ai ? (
            <>
              <p className="class-cat">{m.ai.category}</p>
              <span className={`chip risk-${m.ai.risk}`}>Risk: {m.ai.risk}</span>
              <p className="fine">{m.ai.rationale} · confidence {Math.round(m.ai.confidence * 100)}%</p>
            </>
          ) : <p className="fine">No suggestion.</p>}
        </div>

        <div className="class-box legal">
          <h3 className="mini">Legal classification</h3>
          {!editing && m.legal && (
            <>
              <p className="class-cat">{m.legal.category}</p>
              <span className={`chip risk-${m.legal.risk}`}>Risk: {m.legal.risk}</span>
              {m.legal.note && <p className="note">{m.legal.note}</p>}
              <p className="fine">By {m.legal.by} · {fmtDateTime(m.legal.at)}{changed ? " · differs from AI" : ""}</p>
              {canEdit && <button className="btn ghost small" onClick={() => setEditing(true)}>Change</button>}
            </>
          )}
          {!editing && !m.legal && <p className="fine">Not classified yet.</p>}
          {editing && (
            <form className="form" onSubmit={save} noValidate>
              <div className="field">
                <label htmlFor="cls-category">Category</label>
                <input id="cls-category" list="cls-categories" value={category}
                       onChange={(e) => { setCategory(e.target.value); setError(null); }} />
                <datalist id="cls-categories">{CATEGORIES.map((c) => <option key={c} value={c} />)}</datalist>
              </div>
              <div className="field">
                <label htmlFor="cls-risk">Risk</label>
                <select id="cls-risk" value={risk} onChange={(e) => setRisk(e.target.value as Risk)}>
                  {RISKS.map((r) => <option key={r}>{r}</option>)}
                </select>
              </div>
              <div className="field">
                <label htmlFor="cls-note">Note <span className="opt">optional</span></label>
                <textarea id="cls-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
              </div>
              {error && <p className="field-error">{error}</p>}
              <div className="row">
                <button className="btn primary" type="submit" disabled={saving}>{saving ? "Saving…" : "Save classification"}</button>
                {m.legal && <button type="button" className="btn ghost" onClick={() => setEditing(false)}>Cancel</button>}
              </div>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}

function TasksCard({ m, me, onChanged }: { m: MatterDetail; me: Me; onChanged: () => void }) {
  const canAssign = me.can_assign_to.length > 0 && m.status !== "held";
  const [title, setTitle] = useState("");
  const [assignee, setAssignee] = useState(me.can_assign_to[0]?.email ?? "");
  const [due, setDue] = useState(isoDatePlus(3));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function add(e: FormEvent) {
    e.preventDefault();
    if (title.trim().length < 3) { setError("Describe the task in a few words."); return; }
    if (!due) { setError("Pick a due date."); return; }
    setBusy(true);
    setError(null);
    try {
      await api.addTask(m.id, { title: title.trim(), assignee, due });
      setTitle("");
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function toggle(id: string, status: "open" | "done") {
    try {
      await api.setTask(id, status === "done" ? "open" : "done");
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="card">
      <div className="card-h"><h2>Tasks</h2></div>
      {m.tasks.length === 0 ? (
        <p className="fine">No tasks yet.</p>
      ) : (
        <ul className="task-list">
          {m.tasks.map((t) => {
            const editable = me.role === "super_admin" || t.assignee === me.email || t.assigned_by === me.email;
            return (
              <li key={t.id} className={t.status === "done" ? "is-done" : ""}>
                <input type="checkbox" id={`mt-${t.id}`} checked={t.status === "done"} disabled={!editable}
                       onChange={() => toggle(t.id, t.status)}
                       aria-label={`Mark "${t.title}" ${t.status === "done" ? "open" : "done"}`} />
                <div className="task-main">
                  <span className="t-title">{t.title}</span>
                  <span className="fine">{t.assignee_name} · from {t.assigned_by_name}</span>
                </div>
                <div className="task-due">
                  <span className={t.overdue ? "badge danger" : t.status === "done" ? "badge ok" : "badge"}>
                    {dueLabel(t.due, t.status === "done")}
                  </span>
                  <span className="date">{fmtDate(t.due)}</span>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {canAssign && (
        <form className="form task-form" onSubmit={add} noValidate>
          <h3 className="mini">Assign a task</h3>
          <div className="field">
            <label htmlFor="task-title">Task</label>
            <input id="task-title" value={title} placeholder="e.g. Review notice and advise on cure period"
                   onChange={(e) => { setTitle(e.target.value); setError(null); }} />
          </div>
          <div className="row wrap">
            <div className="field grow">
              <label htmlFor="task-assignee">Assign to</label>
              <select id="task-assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                {me.can_assign_to.map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="task-due">Due</label>
              <input id="task-due" type="date" value={due} onChange={(e) => { setDue(e.target.value); setError(null); }} />
            </div>
          </div>
          {error && <p className="field-error">{error}</p>}
          <button className="btn primary" type="submit" disabled={busy}>{busy ? "Assigning…" : "Assign task"}</button>
        </form>
      )}
      {m.status === "held" && me.role === "super_admin" && (
        <p className="fine">Sensitive matters follow the restricted review process and are not assigned here.</p>
      )}
    </section>
  );
}
