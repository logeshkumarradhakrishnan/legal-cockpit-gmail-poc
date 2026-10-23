import type { Role } from "./types";

export const roleLabel: Record<Role, string> = {
  super_admin: "Super Admin",
  admin: "Admin",
  user: "User",
};

export function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

export function fmtDate(iso: string): string {
  return new Date(iso + (iso.length === 10 ? "T00:00:00" : "")).toLocaleDateString(undefined, {
    day: "numeric", month: "short", year: "numeric",
  });
}

export function dueLabel(iso: string, done: boolean): string {
  if (done) return "Done";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(iso + "T00:00:00");
  const days = Math.round((due.getTime() - today.getTime()) / 86_400_000);
  if (days < 0) return `${-days} day${days === -1 ? "" : "s"} overdue`;
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  return `Due in ${days} days`;
}

export function isoDatePlus(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

const ACTION_LABELS: Record<string, string> = {
  scanned: "Received and scanned",
  classified: "AI suggestion recorded",
  awaiting_consent: "Consent requested from mailbox owner",
  approved_and_forwarded: "Owner approved; forwarded to Legal",
  forwarded_auto: "Forwarded automatically",
  declined: "Owner declined",
  held: "Held as sensitive",
  legal_classified: "Legal classification saved",
  task_assigned: "Task assigned",
  task_done: "Task marked done",
  task_open: "Task reopened",
};

export function actionLabel(a: string): string {
  return ACTION_LABELS[a] ?? a.replace(/_/g, " ");
}
