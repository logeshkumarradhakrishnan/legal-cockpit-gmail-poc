export type Role = "super_admin" | "admin" | "user";
export type Risk = "High" | "Medium" | "Low" | "Sensitive";

export interface Person {
  email: string;
  name: string;
  role: Role;
  manager?: string | null;
}

export interface Me extends Person {
  auth_mode: "dev" | "entra";
  can_assign_to: Person[];
  dev_users: Person[];
}

export interface AiClassification {
  category: string;
  risk: Risk;
  rationale: string;
  confidence: number;
}

export interface LegalClassification {
  category: string;
  risk: Risk;
  note: string;
  by: string;
  at: string;
}

export interface MatterSummary {
  id: string;
  subject: string;
  sender: string;
  owner: string;
  received: string;
  status: "forwarded" | "held";
  sensitive: boolean;
  ai: AiClassification | null;
  legal: LegalClassification | null;
  classification_method?: string | null;
  urgency_matches?: string[];
  stakeholder_matches?: string[];
  open_tasks: number;
  overdue_tasks: number;
}

export interface Task {
  id: string;
  matter_id: string;
  title: string;
  assignee: string;
  assignee_name: string;
  assigned_by: string;
  assigned_by_name: string;
  due: string;
  status: "open" | "done";
  overdue: boolean;
  matter_subject: string;
}

export interface MatterDetail extends MatterSummary {
  body: string;
  attachments: { filename: string; text?: string | null }[];
  gate_matched: string[];
  personal_exclusion_matches?: string[];
  negative_exclusion_matches?: string[];
  decided_by: string | null;
  mode: "auto" | "human_in_loop";
  tasks: Task[];
}

export interface AuditEntry {
  ts: string;
  actor: string;
  action: string;
  detail: unknown;
}

export interface Dashboard {
  total: number;
  forwarded_to_legal: number;
  held_sensitive: number;
  dropped_at_gate: number;
  awaiting_consent: number;
  by_status: Record<string, number>;
  by_risk: Record<string, number>;
  by_category: Record<string, number>;
  tasks: { open: number; overdue: number; due_this_week: number; done: number };
  legal_classified: number;
  awaiting_legal_classification: number;
  ai_risk_agreement: number | null;
}
