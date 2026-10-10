import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Deal, Reminder, api, money } from "../api";
import { Icon } from "../components/ui";
import DealTimer, { useNow } from "../components/DealTimer";
import EmailDraftPanel from "../components/EmailDraftPanel";
import AssistantIntro from "../components/AssistantIntro";

type DraftLite = { id: number; needs_review: boolean; created_at: string };
type Idea = { id: number };

const STAGE_ORDER = ["New", "Contacted", "Proposal Sent"];

function daysBetween(a: string, b: string) {
  return Math.round((new Date(a).getTime() - new Date(b).getTime()) / 86400000);
}

function initialsOf(text: string | null) {
  const parts = (text ?? "?").replace(/^(Dr|Mr|Mrs|Ms)\.?\s+/i, "").split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}

function longDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
}

export default function Dashboard({ user, today, onChange }: { user: string; today: string; onChange: () => void }) {
  const [items, setItems] = useState<Reminder[] | null>(null);
  const [drafts, setDrafts] = useState<DraftLite[]>([]);
  const [mine, setMine] = useState<Deal[]>([]);
  const [team, setTeam] = useState<Deal[]>([]);
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [done, setDone] = useState(0);
  const navigate = useNavigate();
  const now = useNow();
  const [emailFor, setEmailFor] = useState<{ dealId: number; company: string | null; ids: number[] } | null>(null);

  const load = useCallback(() => {
    const u = encodeURIComponent(user);
    api<Reminder[]>(`/api/reminders?due_only=true&owner=${u}`).then((r) =>
      setItems([...r].sort((a, b) => b.priority - a.priority)),
    );
    api<DraftLite[]>(`/api/drafts?owner=${u}`).then(setDrafts);
    api<Deal[]>(`/api/deals?owner=${u}`).then(setMine);
    api<Deal[]>("/api/deals?open_only=false").then(setTeam);
    api<Idea[]>("/api/crosssell").then(setIdeas);
  }, [user]);
  useEffect(load, [load]);

  async function act(ids: number[], action: "done" | "snooze") {
    await Promise.all(ids.map((id) => api(`/api/reminders/${id}`, { method: "POST", json: { action, days: 1 } })));
    if (action === "done") setDone((n) => n + 1);
    load();
    onChange();
  }

  // ---- KPIs (all from real data; the mockup's reply-rate / first-response need email sending we don't do)
  // One row per deal: a deal can have several signals (inactive + no next step); show them together.
  const due = useMemo(() => {
    const byDeal = new Map<number, Reminder[]>();
    (items ?? []).forEach((r) => byDeal.set(r.deal_id, [...(byDeal.get(r.deal_id) ?? []), r]));
    return [...byDeal.values()]
      .map((rs) => {
        const sorted = [...rs].sort((a, b) => b.priority - a.priority);
        const oldest = rs.reduce((m, r) => (r.due_date < m ? r.due_date : m), rs[0].due_date);
        const deadline = rs.reduce((m, r) => (r.deadline < m ? r.deadline : m), rs[0].deadline);
        return { ...sorted[0], due_date: oldest, deadline, ids: rs.map((r) => r.id), reasons: sorted.map((r) => r.reason) };
      })
      .sort((a, b) => b.priority - a.priority);
  }, [items]);
  const overdue = due.filter((r) => r.deadline < today).length;
  const newLeads = (from: number, to: number) =>
    team.filter((d) => d.created_date && daysBetween(today, d.created_date) >= from && daysBetween(today, d.created_date) < to).length;
  const leads7 = newLeads(0, 7);
  const leadsPrev7 = newLeads(7, 14);
  const leadsDelta = leads7 - leadsPrev7;
  const flaggedDrafts = drafts.filter((d) => d.needs_review).length;
  const oldestDraft = drafts.reduce((m, d) => Math.max(m, daysBetween(new Date().toISOString(), d.created_at)), 0);
  const withNext = mine.filter((d) => !d.flags.includes("no_next_step")).length;
  const hygiene = mine.length ? Math.round((100 * withNext) / mine.length) : null;

  // ---- pipeline by stage (your open deals)
  const stages = useMemo(() => {
    const counts = new Map<string, number>();
    mine.forEach((d) => counts.set(d.status ?? "No status", (counts.get(d.status ?? "No status") ?? 0) + 1));
    const order = [...STAGE_ORDER, ...[...counts.keys()].filter((k) => !STAGE_ORDER.includes(k))];
    const max = Math.max(1, ...counts.values());
    return order.filter((k) => counts.has(k)).map((k) => ({ name: k, n: counts.get(k)!, pct: (100 * counts.get(k)!) / max }));
  }, [mine]);

  // ---- insights derived from captured conversations + pipeline rules
  const insights = useMemo(() => {
    const out: { title: string; body: string; to: string }[] = [];
    const cold = mine
      .filter((d) => d.flags.includes("inactive") && d.est_value_usd)
      .sort((a, b) => (b.est_value_usd ?? 0) - (a.est_value_usd ?? 0))[0];
    if (cold)
      out.push({
        title: `${cold.company} (${money(cold.est_value_usd)}) is going cold`,
        body: `${cold.days_since_contact == null ? "No contact recorded" : `No contact for ${cold.days_since_contact} days`}. Your largest inactive deal.`,
        to: `/deals/${cold.id}`,
      });
    const unanswered = mine.filter((d) => d.flags.includes("proposal_unanswered"));
    if (unanswered.length)
      out.push({
        title: `${unanswered.length} proposal${unanswered.length > 1 ? "s" : ""} unanswered for 7+ days`,
        body: `${money(unanswered.reduce((s, d) => s + (d.est_value_usd ?? 0), 0))} waiting on a client decision. Chase for feedback or a decision date.`,
        to: "/follow-ups",
      });
    if (drafts.length)
      out.push({
        title: `${drafts.length} conversation${drafts.length > 1 ? "s" : ""} not yet in the CRM`,
        body: `AI drafts are waiting for your confirmation${oldestDraft ? `; the oldest is ${oldestDraft} day(s) old` : ""}.`,
        to: "/review",
      });
    const noNext = mine.length - withNext;
    if (noNext)
      out.push({
        title: `${noNext} open deal${noNext > 1 ? "s" : ""} without a next step`,
        body: "Every open deal should have a dated next step so nothing slips.",
        to: "/leads",
      });
    if (ideas.length)
      out.push({
        title: `${ideas.length} cross-sell idea${ideas.length > 1 ? "s" : ""} from existing clients`,
        body: "Suggested from each client's own conversations, with the quote as evidence.",
        to: "/leads",
      });
    return out.slice(0, 4);
  }, [mine, drafts, ideas, oldestDraft, withNext]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="crumb">Home</span>
          <h1>Dashboard</h1>
          <span className="muted">
            {longDate(today)} · {due.length} deal{due.length === 1 ? "" : "s"} need{due.length === 1 ? "s" : ""} a follow-up today
          </span>
        </div>
      </div>

      <AssistantIntro user={user} />

      <div className="kpi-cards">
        <div className="kpi-card blueprint">
          <span className="label">Deals to follow up</span>
          <div className="line">
            <span className="value">{items ? due.length : "—"}</span>
            {overdue > 0 && <span className="delta bad">{overdue} overdue</span>}
          </div>
          <span className="sub">
            {items?.length ?? 0} reminders · {done} done this session
          </span>
        </div>
        <div className="kpi-card blueprint">
          <span className="label">New leads · 7d</span>
          <div className="line">
            <span className="value">{leads7}</span>
            <span className={`delta ${leadsDelta < 0 ? "bad" : ""}`}>
              {leadsDelta >= 0 ? "+" : "−"}
              {Math.abs(leadsDelta)}
            </span>
          </div>
          <span className="sub">vs. previous 7 days · whole team</span>
        </div>
        <div className="kpi-card blueprint">
          <span className="label">Drafts to review</span>
          <div className="line">
            <span className="value">{drafts.length}</span>
            {flaggedDrafts > 0 && <span className="delta">{flaggedDrafts} flagged</span>}
          </div>
          <span className="sub">Captured conversations awaiting you</span>
        </div>
        <div className="kpi-card blueprint">
          <span className="label">Deals with a next step</span>
          <div className="line">
            <span className={`value ${hygiene == null ? "" : hygiene >= 100 ? "good" : "bad"}`}>
              {hygiene == null ? "—" : `${hygiene}%`}
            </span>
            <span className="delta">target 100%</span>
          </div>
          <span className="sub">
            {withNext} of {mine.length} of your open deals
          </span>
        </div>
      </div>

      <div className="dash-cols">
        <section className="panel blueprint dash-main">
          <div className="panel-head">
            <div>
              <h2>Follow-up queue</h2>
              <span className="sub">Ranked by deal value and lateness. You act; the assistant never contacts clients.</span>
            </div>
            <button onClick={() => navigate("/follow-ups")}>View all follow-ups</button>
          </div>

          {items && due.length === 0 && <div className="empty-row">Nothing due today.</div>}
          {due.map((r) => {
            const heat = r.priority >= 75 ? "Hot" : r.priority >= 55 ? "Warm" : "Cool";
            return (
              <div className="q-row" key={r.deal_id}>
                <div className="q-avatar">{initialsOf(r.contact_name ?? r.company)}</div>
                <div className="q-body">
                  <div className="q-top">
                    <span className="name">{r.contact_name ?? r.company}</span>
                    {r.contact_name && <span className="co">{r.company}</span>}
                    <span className={`chip ${heat === "Hot" ? "hot" : heat === "Warm" ? "warm" : ""}`} title="Priority: signal type + days overdue + deal value">
                      {heat} · {r.priority}
                    </span>
                  </div>
                  <span className="q-why">{r.reasons.join(" · ")}</span>
                  <span className="q-next">
                    Next · {r.suggested_next_step ?? "Follow up"}
                    {r.est_value_usd ? ` · ${money(r.est_value_usd)} deal` : ""}
                  </span>
                </div>
                <div className="q-actions">
                  <DealTimer dueDate={r.deadline} today={today} now={now} compact />
                  <button className="icon" title="Snooze 1 day" onClick={() => act(r.ids, "snooze")}>
                    <Icon name="clock" size={16} />
                  </button>
                  <button className="ai-action" onClick={() => setEmailFor({ dealId: r.deal_id, company: r.company, ids: r.ids })}>
                    Draft reply
                  </button>
                  <button onClick={() => navigate(`/deals/${r.deal_id}`)}>Open deal</button>
                  <button className="primary" onClick={() => act(r.ids, "done")}>
                    Mark done
                  </button>
                </div>
              </div>
            );
          })}
        </section>

        <div className="dash-side">
          <section className="panel blueprint">
            <div className="panel-head">
              <div>
                <h2>Pipeline by stage</h2>
                <span className="sub">Your open deals</span>
              </div>
            </div>
            <div className="panel-body">
              {stages.length === 0 && <span className="muted small">No open deals.</span>}
              {stages.map((s) => (
                <div className="stage-row" key={s.name}>
                  <span className="name">{s.name}</span>
                  <span className="track">
                    <span className="fill" style={{ width: `${s.pct}%` }} />
                  </span>
                  <span className="n">{s.n}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="panel blueprint">
            <div className="panel-head">
              <Icon name="sparkle" size={17} />
              <div>
                <h2>Insights</h2>
                <span className="sub">From captured conversations and pipeline rules</span>
              </div>
            </div>
            {insights.length === 0 && <div className="empty-row">All clear.</div>}
            {insights.map((i) => (
              <button className="insight" key={i.title} onClick={() => navigate(i.to)}>
                <strong>{i.title}</strong>
                <span>{i.body}</span>
              </button>
            ))}
          </section>
        </div>
      </div>
      {emailFor && (
        <EmailDraftPanel dealId={emailFor.dealId} company={emailFor.company} reminderIds={emailFor.ids} onClose={() => setEmailFor(null)} />
      )}
    </div>
  );
}
