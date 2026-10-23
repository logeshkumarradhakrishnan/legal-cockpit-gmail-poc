import { authHeaders } from "./auth";
import { config } from "./config";
import type { AuditEntry, Dashboard, MatterDetail, MatterSummary, Me, Risk, Task } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(await authHeaders()) };
  if (init.body) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${config.apiBase}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, `Can't reach the Legal Cockpit service at ${config.apiBase}.`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => call<Me>("/api/me"),
  dashboard: () => call<Dashboard>("/api/dashboard"),
  matters: (view: "all" | "unclassified" | "held") => call<MatterSummary[]>(`/api/matters?view=${view}`),
  matter: (id: string) => call<MatterDetail>(`/api/matters/${id}`),
  audit: (id: string) => call<AuditEntry[]>(`/api/matters/${id}/audit`),
  classify: (id: string, body: { category: string; risk: Risk; note: string }) =>
    call<MatterDetail>(`/api/matters/${id}/classify`, { method: "POST", body: JSON.stringify(body) }),
  addTask: (id: string, body: { title: string; assignee: string; due: string }) =>
    call<Task>(`/api/matters/${id}/tasks`, { method: "POST", body: JSON.stringify(body) }),
  tasks: (scope: "mine" | "all") => call<Task[]>(`/api/tasks?scope=${scope}`),
  setTask: (id: string, status: "open" | "done") =>
    call<Task>(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  seed: () => call<{ matters: number; tasks: number }>("/api/dev/seed", { method: "POST" }),
  gmailStatus: () => call<{ configured: boolean; connected: boolean; email: string | null }>("/gmail/status"),
  gmailAuth: () => call<{ authorization_url: string }>("/gmail/auth"),
  gmailMessages: (limit = 25) => call<any[]>(`/gmail/messages?limit=${limit}`),
  gmailIngest: (id: string) => call<any>(`/gmail/ingest/${encodeURIComponent(id)}`, { method: "POST" }),
};
