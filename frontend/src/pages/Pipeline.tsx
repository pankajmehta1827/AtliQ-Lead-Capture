import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Deal, FLAG_LABELS, api, money } from "../api";

type Metric = { label: string; value: number | null; target: number };
type Metrics = {
  north_star: Metric & { n: number };
  pipeline_hygiene: Metric & { open_deals: number; inactive_deals: number };
  trust: Metric & { reviewed: number };
  queue: { pending_drafts: number; oldest_pending_days: number };
  kill_switch_warnings: string[];
};

function Tile({ label, value, target, sub }: { label: string; value: number | null; target: number; sub: string }) {
  const ok = value != null && value >= target;
  return (
    <div className="kpi">
      <span className="label">{label}</span>
      <span className={`value ${value == null ? "" : ok ? "good" : "bad"}`}>{value == null ? "—" : `${value}%`}</span>
      <span className="sub">
        target {target}% · {sub}
      </span>
    </div>
  );
}

export default function Pipeline({ user }: { user: string }) {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [owner, setOwner] = useState<string>("");
  const [query, setQuery] = useState("");
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api<Deal[]>(`/api/deals${owner ? `?owner=${encodeURIComponent(owner)}` : ""}`).then(setDeals);
  }, [owner]);
  useEffect(() => {
    api<Metrics>("/api/metrics").then(setMetrics);
  }, []);

  const shown = deals.filter(
    (d) =>
      (!flaggedOnly || d.flags.length > 0) &&
      (!query || `${d.company} ${d.contact_name} ${d.lead_code}`.toLowerCase().includes(query.toLowerCase())),
  );
  const flagged = deals.filter((d) => d.flags.some((f) => f === "inactive" || f === "no_next_step"));
  const atRisk = flagged.reduce((s, d) => s + (d.est_value_usd ?? 0), 0);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Pipeline</h1>
          <p className="muted">Open deals, flagged first: inactive for more than 14 days, missing next step or proposals unanswered.</p>
        </div>
      </header>

      {metrics && (
        <div className="kpis blueprint">
          <Tile label={metrics.pipeline_hygiene.label} value={metrics.pipeline_hygiene.value} target={100}
            sub={`${metrics.pipeline_hygiene.open_deals} open deals`} />
          <Tile label={metrics.north_star.label} value={metrics.north_star.value} target={95} sub={`${metrics.north_star.n} new leads confirmed`} />
          <Tile label={metrics.trust.label} value={metrics.trust.value} target={80} sub={`${metrics.trust.reviewed} drafts reviewed`} />
          <div className="kpi">
            <span className="label">Flagged deals / value at risk</span>
            <span className="value bad">
              {flagged.length} <small>/ {money(atRisk)}</small>
            </span>
            <span className="sub">{metrics.queue.pending_drafts} drafts waiting review</span>
          </div>
        </div>
      )}
      {metrics?.kill_switch_warnings.map((w) => (
        <div key={w} className="notice warn">
          {w}
        </div>
      ))}

      <div className="toolbar">
        <input placeholder="Search company, contact or lead id" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select value={owner} onChange={(e) => setOwner(e.target.value)}>
          <option value="">All owners</option>
          {["Bhavin", "Dhaval", "Karandeep", "Jay"].map((u) => (
            <option key={u} value={u}>
              {u === user ? `${u} (me)` : u}
            </option>
          ))}
        </select>
        <label className="check">
          <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} /> Flagged only
        </label>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Deal</th>
              <th>Status</th>
              <th>Owner</th>
              <th className="num">Value</th>
              <th>Last contact</th>
              <th>Next step</th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((d) => (
              <tr key={d.id} onClick={() => navigate(`/deals/${d.id}`)} className="clickable">
                <td>
                  <strong>{d.company}</strong>
                  <div className="muted small">
                    {d.lead_code} · {d.service_interest ?? "service unknown"}
                  </div>
                </td>
                <td>{d.status ?? <span className="muted">—</span>}</td>
                <td>{d.owner ?? <span className="muted">—</span>}</td>
                <td className="num value-cell">{money(d.est_value_usd)}</td>
                <td>
                  {d.last_contact_date ?? "never"}
                  {d.days_since_contact != null && <div className="muted small">{d.days_since_contact} days ago</div>}
                </td>
                <td className="next">
                  {d.next_step ?? <span className="muted">—</span>}
                  {d.next_followup_date && <div className="muted small">{d.next_followup_date}</div>}
                </td>
                <td>
                  <div className="tags">
                    {d.flags.map((f) => (
                      <span key={f} className={`chip flag-${f}`}>
                        {FLAG_LABELS[f] ?? f}
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
