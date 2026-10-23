import { useEffect, useState } from "react";
import { api } from "../api";
import MatterPanel from "../components/MatterPanel";
import { fmtDateTime } from "../format";
import type { MatterSummary, Me } from "../types";

type View = "all" | "unclassified" | "held";

interface Props {
  me: Me;
  openId: string | null;
  onOpen: (id: string | null) => void;
  version: number;
  onChanged: () => void;
}

export default function Matters({ me, openId, onOpen, version, onChanged }: Props) {
  const [view, setView] = useState<View>("all");
  const [items, setItems] = useState<MatterSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const staff = me.role !== "user";

  useEffect(() => {
    setError(null);
    api.matters(view).then((rows) => {
      setItems(rows);
      if (!openId && rows.length && window.matchMedia("(min-width: 960px)").matches) onOpen(rows[0].id);
    }).catch((e) => setError(e.message));
  }, [view, version]); // eslint-disable-line react-hooks/exhaustive-deps

  const views: { id: View; label: string }[] = [
    { id: "all", label: "All" },
    ...(staff ? [{ id: "unclassified" as View, label: "Needs classification" }] : []),
    ...(me.role === "super_admin" ? [{ id: "held" as View, label: "Held" }] : []),
  ];

  return (
    <div className={`split ${openId ? "has-open" : ""}`}>
      <section className="card list-card" aria-label="Matters">
        <div className="card-h">
          <h2>Matters</h2>
          {views.length > 1 && (
            <div className="seg" role="group" aria-label="Filter matters">
              {views.map((v) => (
                <button key={v.id} className={view === v.id ? "on" : ""} onClick={() => setView(v.id)}>{v.label}</button>
              ))}
            </div>
          )}
        </div>
        {error && <div className="notice error">{error}</div>}
        {!items ? (
          <div className="empty">Loading…</div>
        ) : items.length === 0 ? (
          <div className="empty">
            {me.role === "user"
              ? "Matters appear here when a task on them is assigned to you."
              : "Nothing here yet. Matters appear once an email is forwarded to Legal."}
          </div>
        ) : (
          <ul className="mlist">
            {items.map((m) => {
              const risk = m.legal?.risk ?? m.ai?.risk;
              return (
                <li key={m.id}>
                  <button className={`mrow ${openId === m.id ? "on" : ""}`} onClick={() => onOpen(m.id)}
                          aria-current={openId === m.id}>
                    <span className="mrow-top">
                      <span className="mrow-subj">{m.subject}</span>
                      <span className="mrow-time">{fmtDateTime(m.received)}</span>
                    </span>
                    <span className="mrow-from">{m.sender}</span>
                    <span className="chips">
                      {m.status === "held" ? (
                        <span className="chip risk-Sensitive">Held · sensitive</span>
                      ) : risk ? (
                        <span className={`chip risk-${risk}`}>{m.legal ? risk : `AI: ${risk}`}</span>
                      ) : null}
                      {staff && m.status === "forwarded" && !m.legal && (
                        <span className="chip plain">Needs classification</span>
                      )}
                      {m.open_tasks > 0 && (
                        <span className={m.overdue_tasks ? "chip danger" : "chip plain"}>
                          {m.open_tasks} open task{m.open_tasks > 1 ? "s" : ""}
                          {m.overdue_tasks ? ` · ${m.overdue_tasks} overdue` : ""}
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="detail-col" aria-label="Matter detail">
        {openId ? (
          <MatterPanel key={openId} id={openId} me={me} version={version} onChanged={onChanged}
                       onClose={() => onOpen(null)} />
        ) : (
          <div className="card empty">Select a matter to see the email, classify it and assign tasks.</div>
        )}
      </section>
    </div>
  );
}
