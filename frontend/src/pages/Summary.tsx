import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, money } from "../api";

type SummaryData = {
  date: string;
  new_drafts: { id: number; kind: string; company: string | null; subject: string | null; needs_review: boolean; age_days: number | null }[];
  due_reminders: { id: number; deal_id: number; lead_code: string; company: string | null; reason: string; due_date: string; suggested_next_step: string | null }[];
  inactive_deals: { deal_id: number; lead_code: string; company: string | null; owner: string | null; flags: string[]; days_since_contact: number | null; est_value_usd: number | null }[];
  integration_failures: number;
};

export default function Summary({ user }: { user: string }) {
  const [owner, setOwner] = useState(user);
  const [data, setData] = useState<SummaryData | null>(null);

  useEffect(() => {
    api<SummaryData>(`/api/summary/daily${owner ? `?owner=${encodeURIComponent(owner)}` : ""}`).then(setData);
  }, [owner]);

  if (!data) return <div className="page">Loading…</div>;
  return (
    <div className="page narrow">
      <header className="page-head">
        <div>
          <h1>Daily summary — {data.date}</h1>
          <p className="muted">New drafts, due follow-ups and deals going cold.</p>
        </div>
        <select value={owner} onChange={(e) => setOwner(e.target.value)}>
          <option value="">Whole team</option>
          {["Bhavin", "Dhaval", "Karandeep", "Jay"].map((u) => (
            <option key={u}>{u}</option>
          ))}
        </select>
      </header>

      {data.integration_failures > 0 && (
        <div className="notice warn">{data.integration_failures} captured item(s) could not be processed — see Capture.</div>
      )}

      <section className="card">
        <h3>
          {data.new_drafts.length} draft(s) to review <Link to="/review" className="small">open queue →</Link>
        </h3>
        <ul className="plain">
          {data.new_drafts.slice(0, 15).map((d) => (
            <li key={d.id}>
              <strong>{d.company ?? "Unknown"}</strong> — {d.subject} {d.needs_review && <span className="chip warn">needs review</span>}
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h3>{data.due_reminders.length} follow-up(s) due</h3>
        <ul className="plain">
          {data.due_reminders.map((r) => (
            <li key={r.id}>
              <Link to={`/deals/${r.deal_id}`}>
                <strong>{r.company}</strong>
              </Link>{" "}
              <span className="muted small">due {r.due_date}</span> — {r.reason}
              {r.suggested_next_step && <div className="muted small">→ {r.suggested_next_step}</div>}
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h3>{data.inactive_deals.length} open deal(s) inactive or without a next step</h3>
        <ul className="plain">
          {data.inactive_deals.map((d) => (
            <li key={d.deal_id}>
              <Link to={`/deals/${d.deal_id}`}>
                <strong>{d.company}</strong>
              </Link>{" "}
              {money(d.est_value_usd)} · {d.owner ?? "no owner"} ·{" "}
              {d.days_since_contact == null ? "never contacted" : `${d.days_since_contact} days since contact`}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
