import { useEffect, useState } from "react";
import { api } from "../api";

type GmailMessage = {
  id: string;
  thread_id?: string | null;
  message_id: string;
  sender: string;
  recipients: string[];
  subject: string;
  date: string;
  snippet: string;
};

export default function Gmail({ onChanged }: { onChanged: () => void }) {
  const [connected, setConnected] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const [messages, setMessages] = useState<GmailMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const status = await api.gmailStatus();
      setConnected(status.connected);
      setEmail(status.email);
      if (status.connected) setMessages(await api.gmailMessages(25));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => { void load(); }, []);

  async function connect() {
    setLoading(true);
    setError(null);
    try {
      const result = await api.gmailAuth();
      window.location.assign(result.authorization_url);
    } catch (e) {
      setError((e as Error).message);
      setLoading(false);
    }
  }

  async function ingest(id: string) {
    setIngesting(id);
    setError(null);
    try {
      await api.gmailIngest(id);
      onChanged();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setIngesting(null);
    }
  }

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h2>Gmail</h2>
          <div className="muted">Connect one Gmail mailbox and select emails for Legal Cockpit triage.</div>
        </div>
        {connected ? (
          <button className="btn ghost small" onClick={load} disabled={loading}>Refresh</button>
        ) : (
          <button className="btn small" onClick={connect} disabled={loading}>{loading ? "Opening…" : "Connect Gmail"}</button>
        )}
      </div>

      {error && <div className="notice error">{error}</div>}
      {connected && <div className="notice">Connected as <b>{email}</b>.</div>}
      {!connected ? (
        <div className="empty">Connect Gmail to see recent Inbox messages.</div>
      ) : messages.length === 0 ? (
        <div className="empty">No Inbox messages found.</div>
      ) : (
        <ul className="mlist">
          {messages.map((m) => (
            <li key={m.id}>
              <div className="mrow" style={{ cursor: "default" }}>
                <span className="mrow-top">
                  <span className="mrow-subj">{m.subject || "(no subject)"}</span>
                  <span className="mrow-time">{m.date}</span>
                </span>
                <span className="mrow-from">{m.sender}</span>
                <span className="muted">{m.snippet}</span>
                <span style={{ display: "block", marginTop: 10 }}>
                  <button className="btn small" onClick={() => ingest(m.id)} disabled={ingesting === m.id}>
                    {ingesting === m.id ? "Ingesting…" : "Ingest into Legal Cockpit"}
                  </button>
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
