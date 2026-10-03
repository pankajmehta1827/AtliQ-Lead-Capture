import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Deal, FLAG_LABELS, Reminder, STAGES, SourceItem, api, money } from "../api";

type Detail = {
  deal: Deal;
  activities: {
    id: number;
    occurred_at: string | null;
    summary: string | null;
    changes: Record<string, unknown>;
    actor: string;
    source: SourceItem | null;
  }[];
  reminders: Reminder[];
  crosssell: { id: number; service: string; rationale: string; evidence: string | null; status: string }[];
  pending_drafts: number[];
};

export default function DealDetail() {
  const { id } = useParams();
  const [data, setData] = useState<Detail | null>(null);
  const [edit, setEdit] = useState<Partial<Deal>>({});
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Detail>(`/api/deals/${id}`).then((d) => {
      setData(d);
      setEdit({
        status: d.deal.status,
        next_step: d.deal.next_step,
        next_followup_date: d.deal.next_followup_date,
        owner: d.deal.owner,
      });
    });
  }, [id]);
  useEffect(load, [load]);

  if (!data) return <div className="page">Loading…</div>;
  const d = data.deal;

  async function save() {
    try {
      await api(`/api/deals/${id}`, {
        method: "PATCH",
        json: { ...edit, next_followup_date: edit.next_followup_date || null },
      });
      setMsg("Saved");
      load();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  async function setIdea(ideaId: number, status: string) {
    await api(`/api/crosssell/${ideaId}`, { method: "POST", json: { status } });
    load();
  }

  return (
    <div className="page">
      <Link to="/pipeline" className="muted small">
        ← Pipeline
      </Link>
      <header className="page-head">
        <div>
          <h1>{d.company}</h1>
          <p className="muted">
            {d.lead_code} · {d.contact_name ?? "no contact"} {d.contact_email && `<${d.contact_email}>`} · {d.source ?? "source unknown"} ·{" "}
            {d.service_interest ?? "service unknown"} · {money(d.est_value_usd)}
          </p>
          <div className="tags">
            {d.flags.map((f) => (
              <span key={f} className={`chip flag-${f}`}>
                {FLAG_LABELS[f] ?? f}
              </span>
            ))}
          </div>
        </div>
      </header>

      {data.pending_drafts.length > 0 && (
        <div className="notice">
          {data.pending_drafts.length} draft update(s) waiting in the <Link to="/review">review queue</Link>.
        </div>
      )}

      <div className="grid-2">
        <div className="card">
          <h3>Deal</h3>
          <div className="form-grid">
            <label>
              Status
              <select value={edit.status ?? ""} onChange={(e) => setEdit({ ...edit, status: e.target.value || null })}>
                <option value="">—</option>
                {STAGES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <label>
              Owner
              <select value={edit.owner ?? ""} onChange={(e) => setEdit({ ...edit, owner: e.target.value || null })}>
                <option value="">—</option>
                {["Bhavin", "Dhaval", "Karandeep", "Jay"].map((u) => (
                  <option key={u}>{u}</option>
                ))}
              </select>
            </label>
            <label className="span-2">
              Next step
              <input value={edit.next_step ?? ""} onChange={(e) => setEdit({ ...edit, next_step: e.target.value })} />
            </label>
            <label>
              Next follow-up
              <input
                type="date"
                value={edit.next_followup_date ?? ""}
                onChange={(e) => setEdit({ ...edit, next_followup_date: e.target.value })}
              />
            </label>
            <div className="actions">
              <button className="primary" onClick={save}>
                Save
              </button>
              {msg && <span className="muted small">{msg}</span>}
            </div>
          </div>
          {d.requirement && (
            <>
              <h4>Requirement</h4>
              <p>{d.requirement}</p>
            </>
          )}
          <h4>Notes</h4>
          <pre className="notes">{d.notes ?? "—"}</pre>
        </div>

        <div>
          <div className="card">
            <h3>Reminders</h3>
            {data.reminders.length === 0 && <p className="muted">None</p>}
            <ul className="plain">
              {data.reminders.map((r) => (
                <li key={r.id}>
                  <strong>{r.due_date}</strong> — {r.reason} <span className="chip ghost">{r.status}</span>
                </li>
              ))}
            </ul>
          </div>
          {data.crosssell.length > 0 && (
            <div className="card">
              <h3>Cross-sell ideas</h3>
              <ul className="plain">
                {data.crosssell.map((c) => (
                  <li key={c.id}>
                    <strong>{c.service}</strong> — {c.rationale}
                    {c.evidence && <div className="evidence">“{c.evidence}”</div>}
                    {c.status === "open" ? (
                      <div className="actions">
                        <button onClick={() => setIdea(c.id, "accepted")}>Pursue</button>
                        <button onClick={() => setIdea(c.id, "dismissed")}>Dismiss</button>
                      </div>
                    ) : (
                      <span className="chip ghost">{c.status}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="card">
            <h3>Activity</h3>
            {data.activities.length === 0 && <p className="muted">No assistant activity yet.</p>}
            <ul className="timeline">
              {data.activities.map((a) => (
                <li key={a.id}>
                  <div className="muted small">
                    {a.occurred_at ?? ""} · confirmed by {a.actor}
                    {a.source && ` · ${a.source.channel}: ${a.source.subject ?? ""}`}
                  </div>
                  {a.summary && <p>{a.summary}</p>}
                  {Object.keys(a.changes).length > 0 && (
                    <div className="muted small">Changed: {Object.keys(a.changes).join(", ")}</div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
