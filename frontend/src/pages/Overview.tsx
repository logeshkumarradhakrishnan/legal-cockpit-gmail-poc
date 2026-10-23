import { useEffect, useState } from "react";
import { api } from "../api";
import type { Dashboard } from "../types";

const RISK_ORDER = ["High", "Medium", "Low", "Sensitive"];

export default function Overview({ version, onOpenMatters }: { version: number; onOpenMatters: () => void }) {
  const [d, setD] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.dashboard().then(setD).catch((e) => setError(e.message));
  }, [version]);

  if (error) return <div className="notice error">{error}</div>;
  if (!d) return <div className="empty">Loading…</div>;

  const s = d.by_status;
  const scanned = d.total - (s.duplicate ?? 0) - (s.excluded ?? 0);
  const passedGate = scanned - (s.dropped ?? 0);
  const funnel = [
    { label: "Scanned", value: scanned, tone: "muted" },
    { label: "Passed keyword gate", value: passedGate, tone: "teal" },
    { label: "Reached Legal", value: d.forwarded_to_legal + d.held_sensitive, tone: "navy" },
  ];
  const max = Math.max(scanned, 1);
  const categories = Object.entries(d.by_category).sort((a, b) => b[1] - a[1]);

  if (d.total === 0) {
    return (
      <div className="card empty-state">
        <h2>No emails yet</h2>
        <p>
          Once the service is connected to the in-scope mailboxes, counts appear here as emails arrive. In demo
          sign-in, a Super Admin can choose <b>Load sample data</b> at the top right.
        </p>
      </div>
    );
  }

  return (
    <div className="stack">
      <section className="tiles" aria-label="Headline numbers">
        <button className="tile tile-link" onClick={onOpenMatters}>
          <span className="n">{d.forwarded_to_legal}</span>
          <span className="l">Forwarded to Legal</span>
          <span className="sub">{d.awaiting_legal_classification} need classification</span>
        </button>
        <div className="tile">
          <span className="n warn">{d.held_sensitive}</span>
          <span className="l">Held as sensitive</span>
          <span className="sub">Restricted review</span>
        </div>
        <div className="tile">
          <span className="n">{d.tasks.open}</span>
          <span className="l">Open tasks</span>
          <span className={d.tasks.overdue ? "sub danger" : "sub"}>
            {d.tasks.overdue} overdue · {d.tasks.due_this_week} due this week
          </span>
        </div>
        <div className="tile">
          <span className="n">{d.ai_risk_agreement === null ? "—" : `${Math.round(d.ai_risk_agreement * 100)}%`}</span>
          <span className="l">AI risk kept by Legal</span>
          <span className="sub">Across {d.legal_classified} classified matters</span>
        </div>
      </section>

      <div className="two-col">
        <section className="card">
          <div className="card-h"><h2>Pipeline</h2></div>
          <div className="funnel">
            {funnel.map((f) => (
              <div className="frow" key={f.label}>
                <span className="fl">{f.label}</span>
                <span className="ft"><span className={`ff ${f.tone}`} style={{ width: `${(f.value / max) * 100}%` }} /></span>
                <span className="fv">{f.value}</span>
              </div>
            ))}
          </div>
          <dl className="kv">
            <div><dt>Dropped at keyword gate</dt><dd>{s.dropped ?? 0}</dd></div>
            <div><dt>Waiting for owner consent</dt><dd>{d.awaiting_consent}</dd></div>
            <div><dt>Declined by owner</dt><dd>{s.declined ?? 0}</dd></div>
            <div><dt>Duplicates removed</dt><dd>{s.duplicate ?? 0}</dd></div>
          </dl>
          <p className="fine">
            Emails that were dropped, declined or are still waiting for consent are counted here only. Their content
            never reaches Legal.
          </p>
        </section>

        <section className="card">
          <div className="card-h"><h2>What reached Legal</h2></div>
          <h3 className="mini">By risk</h3>
          <div className="chips">
            {RISK_ORDER.filter((r) => d.by_risk[r]).map((r) => (
              <span key={r} className={`chip risk-${r}`}>{r} <b>{d.by_risk[r]}</b></span>
            ))}
          </div>
          <h3 className="mini">By category</h3>
          <dl className="kv">
            {categories.map(([c, n]) => (
              <div key={c}><dt>{c}</dt><dd>{n}</dd></div>
            ))}
          </dl>
          <p className="fine">Risk and category here are the AI's suggestions at intake.</p>
        </section>
      </div>
    </div>
  );
}
