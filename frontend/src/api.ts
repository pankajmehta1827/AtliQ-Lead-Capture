export type Field = { value: string | null; evidence: string | null; confidence: number; dropped_value?: string };

export type SourceItem = {
  id: number;
  channel: string;
  external_ref: string | null;
  subject: string | null;
  sender_name: string | null;
  sender_email: string | null;
  participants: { name: string | null; email: string | null }[];
  occurred_at: string | null;
  status: string;
  category: string | null;
  skip_reason: string | null;
  attempts: number;
  last_error: string | null;
  ingested_by: string | null;
  created_at: string;
  body?: string | null;
};

export type Match = {
  deal_id: number;
  lead_code: string;
  company: string | null;
  contact: string | null;
  status: string | null;
  owner: string | null;
  service_interest: string | null;
  score: number;
  reasons: string[];
};

export type FollowUp = { reason: string; due_date: string | null; suggested_next_step: string; evidence: string };
export type Idea = { service: string | null; rationale: string; evidence: string };

export type Draft = {
  id: number;
  kind: "new_lead" | "update";
  category: string;
  deal_id: number | null;
  deal_lead_code: string | null;
  fields: Record<string, Field>;
  summary: string | null;
  confidence: number;
  needs_review: boolean;
  missing_fields: string[];
  duplicate_candidates: Match[];
  followups: FollowUp[];
  crosssell: Idea[];
  owner: string | null;
  status: string;
  llm_mode: string;
  created_at: string;
  source: SourceItem | null;
};

export type Deal = {
  id: number;
  lead_code: string;
  company: string | null;
  contact_name: string | null;
  contact_email: string | null;
  source: string | null;
  service_interest: string | null;
  requirement: string | null;
  status: string | null;
  est_value_usd: number | null;
  owner: string | null;
  created_date: string | null;
  last_contact_date: string | null;
  next_followup_date: string | null;
  next_step: string | null;
  notes: string | null;
  flags: string[];
  days_since_contact: number | null;
  is_open: boolean;
};

export type Reminder = {
  id: number;
  deal_id: number;
  lead_code: string | null;
  company: string | null;
  kind: string;
  reason: string;
  due_date: string;
  suggested_next_step: string | null;
  evidence: string | null;
  owner: string | null;
  status: string;
  source: SourceItem | null;
  last_message: string | null;
  contact_name: string | null;
  deal_status: string | null;
  est_value_usd: number | null;
  priority: number;
  deadline: string; // when the follow-up actually fell due (drives the live timer)
};

export type AppConfig = {
  users: string[];
  requires_access_code: boolean;
  llm_mode: "llm" | "rules";
  today: string;
  processing_enabled: boolean;
  inactive_days: number;
};

const KEY = "atliq-session";

export type Session = { user: string; code: string };

export function getSession(): Session | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function setSession(s: Session | null) {
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: session lasts for this tab only */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const s = getSession();
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (s) {
    headers["X-User"] = s.user;
    if (s.code) headers["X-Access-Code"] = s.code;
  }
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const res = await fetch(path, { ...init, headers, body });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const data = await res.json();
      msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {
      /* non-JSON error */
    }
    if (res.status === 401) window.dispatchEvent(new Event("atliq-unauthorized"));
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const FIELD_LABELS: Record<string, string> = {
  company: "Company",
  contact_name: "Contact",
  contact_email: "Contact email",
  source: "Source",
  service_interest: "Service",
  requirement: "Requirement",
  budget: "Budget",
  timeline: "Timeline",
  stage: "Stage",
  next_step: "Next step",
  next_step_date: "Next step date",
};

export const FLAG_LABELS: Record<string, string> = {
  proposal_unanswered: "Proposal unanswered",
  followup_overdue: "Follow-up overdue",
  inactive: "Inactive",
  no_next_step: "No next step",
  no_owner: "No owner",
  no_status: "No status",
};

export const STAGES = ["New", "Contacted", "Proposal Sent", "Won", "Lost"];
export const SERVICES = ["Power BI Dashboards", "Data Engineering", "AI/ML Solutions", "Custom Web App", "Staff Augmentation"];
export const SOURCES = ["Referral", "LinkedIn", "Conference", "Website", "Cold Outreach", "Existing Client", "Partner"];

export const money = (v: number | null) =>
  v == null ? "—" : `$${v >= 1000 ? `${Math.round(v / 1000)}k` : v.toFixed(0)}`;

// ---------------------------------------------------------------- AI assist (#4 email drafts, #5 ask)

export type GroundedFact = { fact: string; evidence: string; grounded: boolean };

export type EmailDraft = {
  deal_id: number;
  lead_code: string;
  to_name: string | null;
  to_email: string | null;
  subject: string;
  body: string;
  facts: GroundedFact[];
  mode: "llm" | "rules";
  unverified: number;
};

export type AskAnswer = {
  answer: string;
  deals: { lead_code: string; deal_id: number; company: string | null }[];
  citations: { lead_code: string | null; quote: string; grounded: boolean }[];
  mode: "llm" | "rules";
};

export const REMINDER_KIND_LABEL: Record<string, string> = {
  commitment: "Commitment",
  revisit: "Revisit date",
  proposal_unanswered: "Proposal unanswered",
  inactive: "Inactive deal",
  no_next_step: "No next step",
};
