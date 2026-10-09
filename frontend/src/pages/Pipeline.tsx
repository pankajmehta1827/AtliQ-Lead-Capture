import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Deal, FLAG_LABELS, api, money } from "../api";
import EmailDraftPanel from "../components/EmailDraftPanel";
import { Icon, initials } from "../components/ui";

// Layout from the "Lead Pipeline Redesign" canvas: A · stage board (default) and B · action queue.

type Metric = { label: string; value: number | null; target: number };
type Metrics = {
  north_star: Metric & { n: number };
  pipeline_hygiene: Metric & { open_deals: number; inactive_deals: number };
  trust: Metric & { reviewed: number };
  queue: { pending_drafts: number; oldest_pending_days: number };
  kill_switch_warnings: string[];
};

const OWNERS = ["Bhavin", "Dhaval", "Karandeep", "Jay"];
const OPEN_STAGES = ["New", "Contacted", "Proposal Sent"];
const ATTENTION = ["inactive", "no_next_step", "proposal_unanswered", "followup_overdue", "no_owner"];
const FLAG_ORDER = ["proposal_unanswered", "followup_overdue", "inactive", "no_next_step", "no_owner", "no_status"];

const needsAttention = (d: Deal) => d.flags.some((f) => ATTENTION.includes(f));
const byValue = (a: Deal, b: Deal) => (b.est_value_usd ?? 0) - (a.est_value_usd ?? 0);
const sum = (ds: Deal[]) => ds.reduce((s, d) => s + (d.est_value_usd ?? 0), 0);
const pctWidth = (v: number | null) => `${Math.max(0, Math.min(100, v ?? 0))}%`;

export default function Pipeline({ user }: { user: string }) {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [owner, setOwner] = useState("all");
  const [query, setQuery] = useState("");
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [view, setView] = useState<"board" | "queue">(() => {
    try {
      return localStorage.getItem("pipeline-view") === "queue" ? "queue" : "board";
    } catch {
      return "board";
    }
  });
  const [emailFor, setEmailFor] = useState<Deal | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Deal[]>("/api/deals").then(setDeals).catch((e) => setError((e as Error).message));
    api<Metrics>("/api/metrics").then(setMetrics).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  const switchView = (v: "board" | "queue") => {
    setView(v);
    try {
      localStorage.setItem("pipeline-view", v);
    } catch {
      /* per-viewer convenience only */
    }
  };

  // Writes go through the same audited PATCH as the deal page: the owner sees the change in the action log.
  const patch = async (d: Deal, body: Partial<Pick<Deal, "owner" | "next_step" | "next_followup_date">>) => {
    setError(null);
    try {
      const updated = await api<Deal>(`/api/deals/${d.id}`, { method: "PATCH", json: body });
      setDeals((all) => all.map((x) => (x.id === d.id ? updated : x)));
      api<Metrics>("/api/metrics").then(setMetrics).catch(() => undefined);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return deals.filter((d) => {
      if (owner === "none" && d.owner) return false;
      if (owner !== "all" && owner !== "none" && d.owner !== owner) return false;
      if (q && !`${d.company ?? ""} ${d.contact_name ?? ""} ${d.lead_code}`.toLowerCase().includes(q)) return false;
      return !flaggedOnly || needsAttention(d);
    });
  }, [deals, owner, query, flaggedOnly]);

  const flagged = deals.filter(needsAttention);
  const hygiene = metrics?.pipeline_hygiene;
  const missingNext = deals.filter((d) => d.flags.includes("no_next_step")).length;

  return (
    <div className="page pipeline-page">
      <header className="pl-head">
        <div>
          <h1>{view === "board" ? "Pipeline" : "Today's pipeline work"}</h1>
          <p className="muted">
            {view === "board"
              ? `${deals.length} open deals by stage. Cards needing attention sit at the top of each column.`
              : "Flagged deals grouped by the action that clears them, biggest value first."}
          </p>
        </div>
        <div className="pl-controls">
          {view === "board" && (
            <>
              <label className="sr-only" htmlFor="pl-q">Search deals</label>
              <input id="pl-q" type="search" placeholder="Search company, contact or lead id" value={query}
                onChange={(e) => setQuery(e.target.value)} />
              <label className="sr-only" htmlFor="pl-owner">Owner</label>
              <select id="pl-owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
                <option value="all">All owners</option>
                {OWNERS.map((u) => (
                  <option key={u} value={u}>{u === user ? `${u} (me)` : u}</option>
                ))}
                <option value="none">Unassigned</option>
              </select>
              <button type="button" className={`pl-toggle ${flaggedOnly ? "on" : ""}`} aria-pressed={flaggedOnly}
                onClick={() => setFlaggedOnly((v) => !v)}>
                Needs attention only
              </button>
            </>
          )}
          <nav className="pl-views" aria-label="View">
            <button type="button" aria-current={view === "board" ? "page" : undefined} onClick={() => switchView("board")}>Board</button>
            <button type="button" aria-current={view === "queue" ? "page" : undefined} onClick={() => switchView("queue")}>Queue</button>
          </nav>
        </div>
      </header>

      {error && <div className="notice warn">{error}</div>}
      {metrics?.kill_switch_warnings.map((w) => (
        <div key={w} className="notice warn">{w}</div>
      ))}

      {view === "board" ? (
        <>
          {metrics && (
            <section className="pl-metrics" aria-label="Health metrics">
              <MetricCard label="Deals with a next step" value={hygiene!.value} target={100}
                of={`of ${hygiene!.open_deals}`} foot={`Target 100% · ${missingNext} deal${missingNext === 1 ? "" : "s"} need one`} />
              <MetricCard label="New leads logged in 24h" value={metrics.north_star.value} target={95}
                of={`${metrics.north_star.n} confirmed`} foot="Target 95% · with source, need and next step" />
              <MetricCard label="Drafts approved as written" value={metrics.trust.value} target={80}
                of={`of ${metrics.trust.reviewed} reviewed`}
                foot={<>Target 80% · <Link to="/review">{metrics.queue.pending_drafts} drafts waiting review</Link></>} />
              <RiskCard deals={deals} flagged={flagged} />
            </section>
          )}
          <Board deals={shown} onPatch={patch} />
        </>
      ) : (
        <Queue deals={deals} flagged={flagged} metrics={metrics} onPatch={patch} onDraft={setEmailFor} />
      )}

      {emailFor && (
        <EmailDraftPanel dealId={emailFor.id} company={emailFor.company} onClose={() => setEmailFor(null)} />
      )}
    </div>
  );
}

function MetricCard({ label, value, target, of, foot }: {
  label: string; value: number | null; target: number; of: string; foot: React.ReactNode;
}) {
  const tone = value == null ? "" : value >= target ? "good" : "bad";
  return (
    <div className="pl-metric">
      <div className="pl-label">{label}</div>
      <div className="pl-figure">
        <span className={`pl-big ${tone}`}>{value == null ? "—" : `${value}%`}</span>
        <span className="muted">{of}</span>
      </div>
      <div className="pl-bar"><div className={tone} style={{ width: pctWidth(value) }} /></div>
      <div className="pl-foot">{foot}</div>
    </div>
  );
}

function RiskCard({ deals, flagged }: { deals: Deal[]; flagged: Deal[] }) {
  const count = (f: string) => deals.filter((d) => d.flags.includes(f)).length;
  return (
    <div className="pl-metric dark">
      <div className="pl-label">Value at risk</div>
      <div className="pl-figure">
        <span className="pl-big">{money(sum(flagged))}</span>
        <span>in {flagged.length} flagged deals</span>
      </div>
      <div className="pl-risk-chips">
        <span className="r-bad">Inactive 14d+ · {count("inactive")}</span>
        <span className="r-warn">No next step · {count("no_next_step")}</span>
        <span className="r-neutral">Unanswered · {count("proposal_unanswered")}</span>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- A · stage board */

function Board({ deals, onPatch }: { deals: Deal[]; onPatch: (d: Deal, b: Partial<Deal>) => void }) {
  const extra = deals.some((d) => !d.status || !OPEN_STAGES.includes(d.status)) ? ["No status"] : [];
  const stages = [...OPEN_STAGES, ...extra];
  return (
    <div className="pl-board-scroll">
      <div className="pl-board" style={{ gridTemplateColumns: `repeat(${stages.length}, minmax(280px, 1fr))` }}>
        {stages.map((name) => {
          const ds = deals
            .filter((d) => (name === "No status" ? !d.status || !OPEN_STAGES.includes(d.status) : d.status === name))
            .sort((a, b) => Number(needsAttention(b)) - Number(needsAttention(a)) || byValue(a, b));
          const risky = ds.filter(needsAttention).length;
          return (
            <section key={name} className="pl-col" aria-label={name}>
              <div className="pl-col-head">
                <div className="row-between">
                  <h2>{name} <span className="muted">{ds.length || ""}</span></h2>
                  <span className="pl-col-total">{sum(ds) ? money(sum(ds)) : "—"}</span>
                </div>
                <div className="small muted">{ds.length ? `${risky} of ${ds.length} need attention` : "No deals shown"}</div>
                <div className="pl-risk-bar"><div style={{ width: ds.length ? `${Math.round((risky / ds.length) * 100)}%` : 0 }} /></div>
              </div>
              {ds.length === 0 && <div className="pl-empty">No deals in this stage</div>}
              {ds.map((d) => (
                <DealCard key={d.id} d={d} onPatch={onPatch} />
              ))}
            </section>
          );
        })}
      </div>
    </div>
  );
}

function idleChip(d: Deal) {
  const days = d.days_since_contact;
  const tone = days == null || days > 60 ? "bad" : days > 14 ? "warn" : "good";
  return <span className={`pl-idle ${tone}`}>{days == null ? "Never contacted" : `${days}d idle`}</span>;
}

function DealCard({ d, onPatch }: { d: Deal; onPatch: (d: Deal, b: Partial<Deal>) => void }) {
  const [adding, setAdding] = useState(false);
  const [step, setStep] = useState("");
  const [due, setDue] = useState("");
  const overdue = d.flags.includes("followup_overdue");
  const flags = FLAG_ORDER.filter((f) => d.flags.includes(f) && f !== "no_next_step" && f !== "no_owner" && f !== "inactive");

  return (
    <article className="pl-card">
      <div className="row-between top">
        <div className="pl-card-title">
          <Link to={`/deals/${d.id}`}>{d.company ?? "Unknown company"}</Link>
          <span className="small muted">{d.lead_code} · {d.service_interest ?? "service unknown"}</span>
        </div>
        <span className="pl-value">{d.est_value_usd ? money(d.est_value_usd) : "—"}</span>
      </div>

      <div className="row-between">
        {d.owner ? (
          <span className="pl-owner">
            <span className="pl-avatar">{initials(d.owner)}</span>
            {d.owner}
          </span>
        ) : (
          <label className="pl-owner unassigned">
            <span className="pl-avatar empty">?</span>
            <select aria-label={`Assign owner for ${d.company}`} value="" onChange={(e) => e.target.value && onPatch(d, { owner: e.target.value })}>
              <option value="">Assign owner</option>
              {OWNERS.map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
          </label>
        )}
        {idleChip(d)}
      </div>

      {d.next_step || d.next_followup_date ? (
        <div className="pl-next">
          <span>{d.next_step ?? "Follow up"}</span>
          {d.next_followup_date && (
            <span className={`small ${overdue ? "overdue" : "muted"}`}>
              Due {d.next_followup_date}{overdue ? " · overdue" : ""}
            </span>
          )}
        </div>
      ) : adding ? (
        <form
          className="pl-add-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!step.trim()) return;
            onPatch(d, { next_step: step.trim(), ...(due ? { next_followup_date: due } : {}) });
            setAdding(false);
          }}
        >
          <input autoFocus aria-label="Next step" placeholder="e.g. Call Priya about scope" value={step}
            onChange={(e) => setStep(e.target.value)} maxLength={300} />
          <div className="row">
            <input type="date" aria-label="Due date" value={due} onChange={(e) => setDue(e.target.value)} />
            <button className="primary" disabled={!step.trim()}>Save</button>
            <button type="button" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </form>
      ) : (
        <button type="button" className="pl-add-next" onClick={() => setAdding(true)}>
          <Icon name="plus" size={14} /> Add next step
        </button>
      )}

      {flags.length > 0 && (
        <div className="tags">
          {flags.map((f) => (
            <span key={f} className={`chip flag-${f}`}>{FLAG_LABELS[f] ?? f}</span>
          ))}
        </div>
      )}
    </article>
  );
}

/* ---------------------------------------------------------------- B · action queue */

function Queue({ deals, flagged, metrics, onPatch, onDraft }: {
  deals: Deal[];
  flagged: Deal[];
  metrics: Metrics | null;
  onPatch: (d: Deal, b: Partial<Deal>) => void;
  onDraft: (d: Deal) => void;
}) {
  const [showOther, setShowOther] = useState(false);
  const proposals = deals.filter((d) => d.flags.includes("proposal_unanswered")).sort(byValue);
  const ownerless = deals.filter((d) => !d.owner).sort(byValue);
  const handled = new Set([...proposals, ...ownerless].map((d) => d.id));
  const other = deals.filter((d) => d.flags.includes("no_next_step") && !handled.has(d.id)).sort(byValue);

  const owners = [...OWNERS, null].map((o) => {
    const ds = flagged.filter((d) => d.owner === o);
    return { owner: o, n: ds.length, value: sum(ds) };
  }).filter((r) => r.n > 0).sort((a, b) => b.value - a.value);
  const maxValue = Math.max(1, ...owners.map((r) => r.value));

  return (
    <div className="pl-queue">
      <main className="pl-queue-main">
        <section className="pl-panel">
          <div className="pl-panel-head">
            <div>
              <h2>Proposals awaiting a reply <span className="muted">{proposals.length} · {money(sum(proposals))}</span></h2>
              <span className="small muted">Draft a follow-up for each, edit it, then send it from your own mailbox.</span>
            </div>
          </div>
          {proposals.length === 0 ? (
            <p className="pl-panel-empty muted">No proposals waiting on the client.</p>
          ) : (
            <div className="table-wrap flat">
              <table>
                <thead>
                  <tr>
                    <th>Deal</th>
                    <th>Owner</th>
                    <th className="num">Value</th>
                    <th>Silent for</th>
                    <th className="num">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {proposals.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <Link to={`/deals/${d.id}`}><strong>{d.company}</strong></Link>
                        <div className="small muted">
                          {d.lead_code} · {d.service_interest ?? "service unknown"}
                          {d.flags.includes("followup_overdue") && " · follow-up overdue"}
                        </div>
                      </td>
                      <td>{d.owner ?? <span className="muted">Unassigned</span>}</td>
                      <td className="num pl-value">{money(d.est_value_usd)}</td>
                      <td>{d.days_since_contact == null ? idleChip(d) : (
                        <span className={`pl-idle ${d.days_since_contact > 60 ? "bad" : "warn"}`}>{d.days_since_contact} days</span>
                      )}</td>
                      <td className="num">
                        <button type="button" className="ai-action" onClick={() => onDraft(d)}>
                          Draft reply
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="pl-panel">
          <div className="pl-panel-head">
            <div>
              <h2>Deals without an owner <span className="muted">{ownerless.length}</span></h2>
              <span className="small muted">Nobody gets follow-up reminders for these. Assign today so the 24-hour target holds.</span>
            </div>
          </div>
          {ownerless.length === 0 ? (
            <p className="pl-panel-empty muted">Every open deal has an owner.</p>
          ) : (
            ownerless.map((d) => (
              <div key={d.id} className="pl-assign-row">
                <div>
                  <Link to={`/deals/${d.id}`}><strong>{d.company}</strong></Link>
                  <div className="small muted">
                    {d.lead_code} · {d.service_interest ?? "service unknown"} ·{" "}
                    {d.days_since_contact == null ? "never contacted" : `${d.days_since_contact} days since contact`}
                  </div>
                </div>
                <label className="row">
                  <span className="small muted">Owner</span>
                  <select value="" onChange={(e) => e.target.value && onPatch(d, { owner: e.target.value })}>
                    <option value="">Choose…</option>
                    {OWNERS.map((u) => <option key={u} value={u}>{u}</option>)}
                  </select>
                </label>
              </div>
            ))
          )}
        </section>

        <section className="pl-panel">
          <div className="pl-panel-head">
            <div>
              <h2>Other deals missing a next step <span className="muted">{other.length}</span></h2>
              <span className="small muted">
                {showOther ? "Add a next step from the deal page or the board." : "Collapsed until the two groups above are cleared."}
              </span>
            </div>
            {other.length > 0 && (
              <button type="button" onClick={() => setShowOther((v) => !v)} aria-expanded={showOther}>
                {showOther ? "Hide" : "Show"}
              </button>
            )}
          </div>
          {showOther && other.map((d) => (
            <div key={d.id} className="pl-assign-row">
              <div>
                <Link to={`/deals/${d.id}`}><strong>{d.company}</strong></Link>
                <div className="small muted">{d.lead_code} · {d.status ?? "no status"} · {d.owner ?? "unassigned"}</div>
              </div>
              <span className="pl-value">{money(d.est_value_usd)}</span>
            </div>
          ))}
        </section>
      </main>

      <aside className="pl-queue-side">
        <section className="pl-metric dark">
          <div className="pl-label">Value at risk</div>
          <div className="pl-big xl">{money(sum(flagged))}</div>
          <div>{flagged.length} flagged of {deals.length} open deals</div>
          {metrics && (
            <>
              <div className="pl-rule" />
              <SideStat label="Next step set" value={metrics.pipeline_hygiene.value} target={100} />
              <SideStat label="Leads logged in 24h" value={metrics.north_star.value} target={95} />
              <SideStat label="Drafts approved as written" value={metrics.trust.value} target={80} />
            </>
          )}
        </section>

        <section className="pl-panel pad">
          <h2 className="pl-side-title">Flagged by owner</h2>
          {owners.map((r) => (
            <div key={r.owner ?? "none"} className="pl-owner-bar">
              <div className="row-between">
                <span className={r.owner ? "" : "unassigned-text"}>{r.owner ?? "Unassigned"}</span>
                <strong>{r.n} · {money(r.value)}</strong>
              </div>
              <div className="pl-bar thick"><div className={r.owner ? "ink" : "warn"} style={{ width: `${(r.value / maxValue) * 100}%` }} /></div>
            </div>
          ))}
        </section>
      </aside>
    </div>
  );
}

function SideStat({ label, value, target }: { label: string; value: number | null; target: number }) {
  const ok = value != null && value >= target;
  return (
    <div className="row-between">
      <span className="pl-dim">{label}</span>
      <span className={ok ? "pl-ok" : "pl-miss"}>{value == null ? "—" : `${value}%`} · target {target}%</span>
    </div>
  );
}
