import { useEffect, useState } from "react";
import { api } from "../api";
import { dueLabel, fmtDate } from "../format";
import type { Me, Task } from "../types";

interface Props {
  me: Me;
  version: number;
  onChanged: () => void;
  onOpenMatter: (id: string) => void;
}

export default function Tasks({ me, version, onChanged, onOpenMatter }: Props) {
  const canSeeTeam = me.role !== "user";
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTasks(null);
    api.tasks(scope).then(setTasks).catch((e) => setError(e.message));
  }, [scope, version]);

  async function toggle(t: Task) {
    try {
      await api.setTask(t.id, t.status === "done" ? "open" : "done");
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const canEdit = (t: Task) =>
    me.role === "super_admin" || t.assignee === me.email || t.assigned_by === me.email;

  return (
    <section className="card">
      <div className="card-h">
        <h2>Tasks</h2>
        {canSeeTeam && (
          <div className="seg" role="group" aria-label="Which tasks">
            <button className={scope === "mine" ? "on" : ""} onClick={() => setScope("mine")}>Assigned to me</button>
            <button className={scope === "all" ? "on" : ""} onClick={() => setScope("all")}>
              {me.role === "super_admin" ? "Everyone" : "My team"}
            </button>
          </div>
        )}
      </div>
      {error && <div className="notice error">{error}</div>}
      {!tasks ? (
        <div className="empty">Loading…</div>
      ) : tasks.length === 0 ? (
        <div className="empty">
          {scope === "mine" ? "Nothing is assigned to you." : "No tasks for your team yet."}
        </div>
      ) : (
        <div className="table-wrap">
          <table className="tasks">
            <thead>
              <tr>
                <th>Done</th><th>Task</th><th>Matter</th>
                {scope === "all" && <th>Assignee</th>}
                <th>Assigned by</th><th>Due</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id} className={t.status === "done" ? "is-done" : ""}>
                  <td>
                    <input
                      type="checkbox"
                      id={`task-${t.id}`}
                      aria-label={`Mark "${t.title}" ${t.status === "done" ? "open" : "done"}`}
                      checked={t.status === "done"}
                      disabled={!canEdit(t)}
                      onChange={() => toggle(t)}
                    />
                  </td>
                  <td className="t-title">{t.title}</td>
                  <td><button className="linkish" onClick={() => onOpenMatter(t.matter_id)}>{t.matter_subject}</button></td>
                  {scope === "all" && <td>{t.assignee_name}</td>}
                  <td>{t.assigned_by_name}</td>
                  <td>
                    <span className={t.overdue ? "badge danger" : t.status === "done" ? "badge ok" : "badge"}>
                      {dueLabel(t.due, t.status === "done")}
                    </span>
                    <span className="date">{fmtDate(t.due)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
