import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Reminder, api } from "../api";

const KIND_LABEL: Record<string, string> = {
  commitment: "Commitment",
  proposal_unanswered: "Proposal unanswered",
  inactive: "Inactive deal",
  no_next_step: "No next step",
};

export default function Reminders({ user, onChange }: { user: string; onChange: () => void }) {
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [items, setItems] = useState<Reminder[]>([]);
  const [today, setToday] = useState<string>("");

  const load = useCallback(() => {
    api<{ today: string }>("/api/config").then((c) => setToday(c.today));
    api<Reminder[]>(`/api/reminders${scope === "mine" ? `?owner=${encodeURIComponent(user)}` : ""}`).then(setItems);
  }, [scope, user]);
  useEffect(load, [load]);

  async function act(id: number, action: string, days = 3) {
    await api(`/api/reminders/${id}`, { method: "POST", json: { action, days } });
    load();
    onChange();
  }

  async function scan() {
    await api("/api/reminders/scan", { method: "POST" });
    load();
    onChange();
  }

  const due = items.filter((r) => r.due_date <= today);
  const upcoming = items.filter((r) => r.due_date > today);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Follow-ups</h1>
          <p className="muted">The assistant reminds you. It never contacts the client — you decide what to do.</p>
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
        { title: `Due now (${due.length})`, list: due },
        { title: `Upcoming (${upcoming.length})`, list: upcoming },
      ].map((g) => (
        <section key={g.title}>
          <h3>{g.title}</h3>
          {g.list.length === 0 && <p className="muted">Nothing here.</p>}
          <div className="cards">
            {g.list.map((r) => (
              <div key={r.id} className="card reminder">
                <div className="row-between">
                  <span className={`chip k-${r.kind}`}>{KIND_LABEL[r.kind] ?? r.kind}</span>
                  <span className={r.due_date < today ? "overdue small" : "muted small"}>due {r.due_date}</span>
                </div>
                <h4>
                  <Link to={`/deals/${r.deal_id}`}>
                    {r.company} <span className="muted small">{r.lead_code}</span>
                  </Link>
                </h4>
                <p>{r.reason}</p>
                {r.suggested_next_step && (
                  <p className="small">
                    <strong>Suggested:</strong> {r.suggested_next_step}
                  </p>
                )}
                {r.evidence && <div className="evidence">“{r.evidence}”</div>}
                {r.source && (
                  <div className="muted small">
                    From {r.source.channel}: {r.source.subject} ({r.source.occurred_at})
                  </div>
                )}
                <div className="actions">
                  <button className="primary" onClick={() => act(r.id, "done")}>
                    Done
                  </button>
                  <button onClick={() => act(r.id, "snooze", 3)}>Snooze 3d</button>
                  <button onClick={() => act(r.id, "dismiss")}>Dismiss</button>
                  <span className="muted small">{r.owner}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
