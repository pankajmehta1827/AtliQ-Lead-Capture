import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Reminder, api, money } from "../api";
import { Corners } from "../components/ui";

type Metrics = {
  pipeline_hygiene: { value: number | null; open_deals: number; inactive_deals: number };
  trust: { value: number | null; reviewed: number };
  queue: { pending_drafts: number; oldest_pending_days: number };
};
type DraftLite = { id: number; needs_review: boolean };
type DealLite = { flags: string[]; est_value_usd: number | null };

function daysBetween(a: string, b: string) {
  return Math.round((new Date(a).getTime() - new Date(b).getTime()) / 86400000);
}

function dueTag(due: string, today: string) {
  const d = daysBetween(today, due);
  if (d > 0) return { text: `Overdue · ${d}d`, cls: "late" };
  if (d === 0) return { text: "Today", cls: "" };
  return { text: `In ${-d}d`, cls: "" };
}

export default function Today({ user, onChange }: { user: string; onChange: () => void }) {
  const [today, setToday] = useState("");
  const [items, setItems] = useState<Reminder[] | null>(null);
  const [drafts, setDrafts] = useState<DraftLite[]>([]);
  const [deals, setDeals] = useState<DealLite[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [doneToday, setDoneToday] = useState(0);
  const navigate = useNavigate();

  const load = useCallback(() => {
    const u = encodeURIComponent(user);
    api<{ today: string }>("/api/config").then((c) => setToday(c.today));
    api<Reminder[]>(`/api/reminders?due_only=true&owner=${u}`).then((r) =>
      setItems([...r].sort((a, b) => b.priority - a.priority)),
    );
    api<DraftLite[]>(`/api/drafts?owner=${u}`).then(setDrafts);
    api<DealLite[]>(`/api/deals?owner=${u}`).then(setDeals);
    api<Metrics>("/api/metrics").then(setMetrics);
  }, [user]);
  useEffect(load, [load]);

  async function act(id: number, action: "done" | "snooze") {
    await api(`/api/reminders/${id}`, { method: "POST", json: { action, days: 1 } });
    if (action === "done") setDoneToday((n) => n + 1);
    load();
    onChange();
  }

  const atRisk = deals.filter((d) => d.flags.includes("inactive") || d.flags.includes("no_next_step"));
  const atRiskValue = atRisk.reduce((s, d) => s + (d.est_value_usd ?? 0), 0);
  const overdue = (items ?? []).filter((r) => r.due_date < today).length;
  const hygiene = metrics?.pipeline_hygiene.value;

  return (
    <div className="page">
      <div className="kpis blueprint">
        <Corners />
        <div className="kpi">
          <span className="label">Follow-ups due</span>
          <span className="value">{items?.length ?? "—"}</span>
          <span className="sub">
            {overdue} overdue · {doneToday} done this session
          </span>
        </div>
        <div className="kpi">
          <span className="label">Drafts to review</span>
          <span className="value">{drafts.length}</span>
          <span className="sub">{drafts.filter((d) => d.needs_review).length} need a closer look</span>
        </div>
        <div className="kpi">
          <span className="label">Deals with a next step</span>
          <span className={`value ${hygiene == null ? "" : hygiene >= 100 ? "good" : "bad"}`}>
            {hygiene == null ? "—" : `${Math.round(hygiene)}%`}
          </span>
          <span className="sub">Team-wide · target 100%</span>
        </div>
        <div className="kpi">
          <span className="label">Value going cold</span>
          <span className="value">{money(atRiskValue)}</span>
          <span className="sub">{atRisk.length} of your open deals inactive or without a next step</span>
        </div>
      </div>

      <section>
        <div className="section-head">
          <h2>Follow-up queue</h2>
          <p>Ranked by what is at stake and how late it is. You decide and act — the assistant never contacts clients.</p>
        </div>

        {items && items.length === 0 && (
          <div className="empty">
            <h3>Nothing due</h3>
            <p className="muted">
              No follow-ups due today. {drafts.length > 0 && <Link to="/review">Review {drafts.length} new draft(s) →</Link>}
            </p>
          </div>
        )}

        {(items ?? []).map((r) => {
          const tag = dueTag(r.due_date, today);
          const heat = r.priority >= 75 ? { t: "Hot", c: "hot" } : r.priority >= 55 ? { t: "Warm", c: "warm" } : { t: "Cool", c: "" };
          return (
            <div className="queue-row" key={r.id}>
              <span className="score" title="Priority: signal type + days overdue + deal value">
                {r.priority}
              </span>
              <div className="who">
                <strong>{r.contact_name ?? r.company}</strong>
                <span className="role">
                  {r.contact_name ? `${r.company} · ` : ""}
                  {r.lead_code} · {r.deal_status ?? "no status"}
                  {r.est_value_usd ? ` · ${money(r.est_value_usd)}` : ""}
                </span>
                <span className="tags">
                  <span className={`chip ${heat.c}`}>{heat.t}</span>
                  <span className={`chip ${tag.cls}`}>{tag.text}</span>
                </span>
              </div>
              <div className="why">
                <span className="kicker accent">Why now</span>
                <span>{r.reason}</span>
                {r.evidence && <span className="evidence">“{r.evidence}”</span>}
                {r.suggested_next_step && <span className="draft">Next: {r.suggested_next_step}</span>}
              </div>
              <div className="row-actions">
                <button className="ghost" onClick={() => act(r.id, "snooze")}>
                  Snooze 1d
                </button>
                <button onClick={() => navigate(`/deals/${r.deal_id}`)}>Open deal</button>
                <button className="primary blueprint" onClick={() => act(r.id, "done")}>
                  <Corners />
                  Mark done
                </button>
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}
