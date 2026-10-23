import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { getDevUser, setDevUser, signOut } from "./auth";
import { roleLabel } from "./format";
import Matters from "./pages/Matters";
import Overview from "./pages/Overview";
import Tasks from "./pages/Tasks";
import Gmail from "./pages/Gmail";
import type { Me } from "./types";

type Page = "overview" | "matters" | "tasks" | "gmail";

function pageFromHash(): Page {
  const h = window.location.hash.replace("#", "");
  return h === "matters" || h === "tasks" || h === "gmail" ? h : "overview";
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState<Page>(pageFromHash());
  const [openMatter, setOpenMatter] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [seeding, setSeeding] = useState(false);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    setError(null);
    api.me().then(setMe).catch((e) => setError(e.message));
  }, [version]);

  // Users have no dashboard; start them on their tasks.
  useEffect(() => {
    if (me?.role === "user" && page === "overview") go("tasks");
  }, [me]); // eslint-disable-line react-hooks/exhaustive-deps

  function go(p: Page) {
    setPage(p);
    window.location.hash = p;
  }

  function openMatterFromTask(id: string) {
    setOpenMatter(id);
    go("matters");
  }

  function switchDevUser(email: string) {
    setDevUser(email);
    setOpenMatter(null);
    refresh();
  }

  async function loadSample() {
    setSeeding(true);
    try {
      await api.seed();
      setOpenMatter(null);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSeeding(false);
    }
  }

  const staff = me?.role === "super_admin" || me?.role === "admin";

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-name">Legal Cockpit</span>
          {me?.auth_mode === "dev" && <span className="demo-pill">Demo sign-in</span>}
        </div>

        <nav className="nav" aria-label="Sections">
          {staff && (
            <button className={page === "overview" ? "on" : ""} onClick={() => go("overview")}>
              Overview
            </button>
          )}
          <button className={page === "matters" ? "on" : ""} onClick={() => go("matters")}>
            Matters
          </button>
          <button className={page === "tasks" ? "on" : ""} onClick={() => go("tasks")}>
            Tasks
          </button>
          {staff && (
            <button className={page === "gmail" ? "on" : ""} onClick={() => go("gmail")}>
              Gmail
            </button>
          )}
        </nav>

        <div className="who">
          {me?.auth_mode === "dev" ? (
            <>
              <label className="sr-only" htmlFor="devUser">Signed in as</label>
              <select id="devUser" value={getDevUser()} onChange={(e) => switchDevUser(e.target.value)}>
                {me.dev_users.map((u) => (
                  <option key={u.email} value={u.email}>
                    {u.name} · {roleLabel[u.role]}
                  </option>
                ))}
              </select>
              {me.role === "super_admin" && (
                <button className="btn ghost small" onClick={loadSample} disabled={seeding}>
                  {seeding ? "Loading…" : "Load sample data"}
                </button>
              )}
            </>
          ) : me ? (
            <>
              <span className="who-name">{me.name}</span>
              <span className="rolepill">{roleLabel[me.role]}</span>
              <button className="btn ghost small" onClick={signOut}>Sign out</button>
            </>
          ) : null}
        </div>
      </header>

      <main className="main">
        {error && <div className="notice error">{error}</div>}
        {!me && !error && <div className="empty">Loading…</div>}
        {me && page === "overview" && staff && <Overview version={version} onOpenMatters={() => go("matters")} />}
        {me && page === "matters" && (
          <Matters me={me} openId={openMatter} onOpen={setOpenMatter} version={version} onChanged={refresh} />
        )}
        {me && page === "tasks" && (
          <Tasks me={me} version={version} onChanged={refresh} onOpenMatter={openMatterFromTask} />
        )}
        {me && page === "gmail" && staff && <Gmail onChanged={refresh} />}
      </main>
    </div>
  );
}
