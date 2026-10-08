import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Reminder, api, money } from "../api";
import DealTimer, { useNow } from "../components/DealTimer";

const KIND_LABEL: Record<string, string> = {
  commitment: "Commitment",
  proposal_unanswered: "Proposal unanswered",
  inactive: "Inactive deal",
  no_next_step: "No next step",
};

type DealGroup = {
  deal_id: number;
  company: string | null;
  lead_code: string | null;
  owner: string | null;
  est_value_usd: number | null;
  due_date: string; // earliest due date among the deal's reminders (Due now / Upcoming)
  deadline: string; // earliest real deadline: drives the timer
  priority: number;
  items: Reminder[];
};

export default function Reminders({ user, onChange }: { user: string; onChange: () => void }) {
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [items, setItems] = useState<Reminder[]>([]);
  const [today, setToday] = useState<string>("");
  const now = useNow();

  const load = useCallback(() => {
    api<{ today: string }>("/api/config").then((c) => setToday(c.today));
    api<Reminder[]>(`/api/reminders${scope === "mine" ? `?owner=${encodeURIComponent(user)}` : ""}`).then(setItems);
  }, [scope, user]);
  useEffect(load, [load]);

  async function act(ids: number[], action: string, days = 3) {
    await Promise.all(ids.map((id) => api(`/api/reminders/${id}`, { method: "POST", json: { action, days } })));
    load();
    onChange();
  }

  async function scan() {
    await api("/api/reminders/scan", { method: "POST" });
    load();
    onChange();
  }

  // One card per deal: a deal can carry several signals (e.g. inactive + no next step).
  const groups = useMemo(() => {
    const byDeal = new Map<number, Reminder[]>();
    items.forEach((r) => byDeal.set(r.deal_id, [...(byDeal.get(r.deal_id) ?? []), r]));
    return [...byDeal.values()]
      .map<DealGroup>((rs) => {
        const sorted = [...rs].sort((a, b) => b.priority - a.priority);
        return {
          deal_id: rs[0].deal_id,
          company: rs[0].company,
          lead_code: rs[0].lead_code,
          owner: rs[0].owner,
          est_value_usd: rs[0].est_value_usd,
          due_date: rs.reduce((m, r) => (r.due_date < m ? r.due_date : m), rs[0].due_date),
          deadline: rs.reduce((m, r) => (r.deadline < m ? r.deadline : m), rs[0].deadline),
          priority: sorted[0].priority,
          items: sorted,
        };
      })
      // most overdue first
      .sort((a, b) => (a.deadline === b.deadline ? b.priority - a.priority : a.deadline < b.deadline ? -1 : 1));
  }, [items]);

  const due = groups.filter((g) => g.due_date <= today);
  const upcoming = groups.filter((g) => g.due_date > today);
  const overdue = due.filter((g) => g.deadline < today).length;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Follow-ups</h1>
          <p className="muted">
            Live timers show how long each deal has until its follow-up is due, or how long it has been overdue. The assistant
            never contacts the client; you decide what to do.
          </p>
        </div>
        <div className="row">
          <div className="seg">
            <button className={scope === "mine" ? "on" : ""} onClick={() => setScope("mine")}>
              Mine
            </button>
            <button className={scope === "all" ? "on" : ""} onClick={() => setScope("all")}>
              Everyone
            </button>
          </div>
          <button onClick={scan}>Scan pipeline now</button>
        </div>
      </header>

      {[
        { title: `Due now (${due.length} deal${due.length === 1 ? "" : "s"}${overdue ? `, ${overdue} overdue` : ""})`, list: due },
        { title: `Upcoming (${upcoming.length})`, list: upcoming },
      ].map((section) => (
        <section key={section.title}>
          <h3>{section.title}</h3>
          {section.list.length === 0 && <p className="muted">Nothing here.</p>}
          <div className="cards">
            {section.list.map((g) => (
              <div key={g.deal_id} className="card reminder">
                {today && <DealTimer dueDate={g.deadline} today={today} now={now} />}
                <h4>
                  <Link to={`/deals/${g.deal_id}`}>
                    {g.company} <span className="muted small">{g.lead_code}</span>
                  </Link>
                  {g.est_value_usd ? <span className="deal-value">{money(g.est_value_usd)}</span> : null}
                </h4>
                <ul className="reasons">
                  {g.items.map((r) => (
                    <li key={r.id}>
                      <span className={`chip k-${r.kind}`}>{KIND_LABEL[r.kind] ?? r.kind}</span>
                      <span>{r.reason}</span>
                      {r.suggested_next_step && (
                        <span className="small">
                          <strong>Suggested:</strong> {r.suggested_next_step}
                        </span>
                      )}
                      {r.evidence && <span className="evidence">“{r.evidence}”</span>}
                      {r.source && (
                        <span className="muted small">
                          From {r.source.channel}: {r.source.subject} ({r.source.occurred_at})
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
                <div className="actions">
                  <button className="primary" onClick={() => act(g.items.map((r) => r.id), "done")}>
                    Done
                  </button>
                  <button onClick={() => act(g.items.map((r) => r.id), "snooze", 3)}>Snooze 3d</button>
                  <button onClick={() => act(g.items.map((r) => r.id), "dismiss")}>Dismiss</button>
                  <span className="muted small">{g.owner ?? "no owner"}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
