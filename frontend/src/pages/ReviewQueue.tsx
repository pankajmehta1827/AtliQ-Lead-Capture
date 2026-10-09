import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Draft, FIELD_LABELS, SERVICES, SOURCES, STAGES, api } from "../api";
import SourceView from "../components/SourceView";

const FIELD_ORDER = Object.keys(FIELD_LABELS);
const SELECT_OPTIONS: Record<string, string[]> = { stage: STAGES, service_interest: SERVICES, source: SOURCES };

function ConfidencePill({ value }: { value: number }) {
  const cls = value >= 0.75 ? "ok" : value >= 0.5 ? "mid" : "low";
  return <span className={`pill ${cls}`}>{Math.round(value * 100)}%</span>;
}

export default function ReviewQueue({ user, onChange }: { user: string; onChange: () => void }) {
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api<Draft[]>(`/api/drafts${scope === "mine" ? `?owner=${encodeURIComponent(user)}` : ""}`)
      .then((d) => {
        setDrafts(d);
        setSelectedId((cur) => (cur && d.some((x) => x.id === cur) ? cur : d[0]?.id ?? null));
      })
      .finally(() => setLoading(false));
  }, [scope, user]);

  useEffect(load, [load]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Review queue</h1>
          <p className="muted">Drafts from your conversations. Confirm, edit or discard. Nothing reaches the CRM without you.</p>
        </div>
        <div className="seg">
          <button className={scope === "mine" ? "on" : ""} onClick={() => setScope("mine")}>
            Mine
          </button>
          <button className={scope === "all" ? "on" : ""} onClick={() => setScope("all")}>
            Everyone
          </button>
        </div>
      </header>

      {!loading && drafts.length === 0 ? (
        <div className="empty blueprint">
          <h3>Queue is clear</h3>
          <p className="muted">
            New drafts appear here within minutes of a conversation. Try <Link to="/capture">Capture</Link> to sync the sample
            mailbox.
          </p>
        </div>
      ) : (
        <div className="split">
          <ul className="list">
            {drafts.map((d) => (
              <li key={d.id} className={d.id === selectedId ? "sel" : ""} onClick={() => setSelectedId(d.id)}>
                <div className="row-between">
                  <strong>{d.fields.company?.value ?? d.duplicate_candidates[0]?.company ?? "Unknown company"}</strong>
                  <ConfidencePill value={d.confidence} />
                </div>
                <div className="muted small ellipsis">{d.source?.subject}</div>
                <div className="tags">
                  <span className={`chip ${d.kind === "new_lead" ? "new" : "upd"}`}>
                    {d.kind === "new_lead" ? "New lead" : `Update ${d.deal_lead_code ?? ""}`}
                  </span>
                  {d.needs_review && <span className="chip warn">Needs review</span>}
                  {d.duplicate_candidates.length > 1 && <span className="chip dup">Possible duplicate</span>}
                  {d.source?.category === "internal_multi_deal" && <span className="chip ghost">From internal meeting</span>}
                  <span className="chip ghost">{d.owner}</span>
                </div>
              </li>
            ))}
          </ul>
          {selectedId && (
            <DraftEditor
              key={selectedId}
              id={selectedId}
              onDone={() => {
                load();
                onChange();
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}

function DraftEditor({ id, onDone }: { id: number; onDone: () => void }) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [focus, setFocus] = useState<string | null>(null);
  const [target, setTarget] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [discarding, setDiscarding] = useState(false);
  const [reason, setReason] = useState("");

  useEffect(() => {
    api<Draft>(`/api/drafts/${id}`).then((d) => {
      setDraft(d);
      const v: Record<string, string> = {};
      FIELD_ORDER.forEach((k) => (v[k] = d.fields[k]?.value ?? ""));
      setValues(v);
      setTarget(d.deal_id ? String(d.deal_id) : "new");
    });
  }, [id]);

  const highlight = useMemo(() => {
    if (!draft || !focus) return null;
    if (focus.startsWith("fu:")) return draft.followups[Number(focus.slice(3))]?.evidence;
    if (focus.startsWith("cs:")) return draft.crosssell[Number(focus.slice(3))]?.evidence;
    return draft.fields[focus]?.evidence ?? null;
  }, [draft, focus]);

  if (!draft) return <div className="editor">Loading…</div>;

  const edits: Record<string, string> = {};
  FIELD_ORDER.forEach((k) => {
    if ((values[k] ?? "") !== (draft.fields[k]?.value ?? "")) edits[k] = values[k];
  });

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/drafts/${id}/confirm`, {
        method: "POST",
        json: {
          edits,
          create_new: target === "new",
          target_deal_id: target !== "new" ? Number(target) : null,
        },
      });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    setBusy(true);
    try {
      await api(`/api/drafts/${id}/discard`, { method: "POST", json: { reason: reason || null } });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="editor-wrap">
      <div className="editor">
        <div className="row-between">
          <h2>{draft.kind === "new_lead" ? "New lead draft" : `Update to ${draft.deal_lead_code}`}</h2>
          <span className="muted small">
            Confidence <ConfidencePill value={draft.confidence} /> · {draft.llm_mode === "llm" ? "AI" : "rules"}
          </span>
        </div>

        {draft.needs_review && (
          <div className="notice warn">
            Needs review
            {draft.missing_fields.length > 0 && (
              <> — missing: {draft.missing_fields.map((f) => FIELD_LABELS[f] ?? f).join(", ")}</>
            )}
            . Empty fields were left empty rather than guessed.
          </div>
        )}

        <div className="target">
          <label>
            Save to
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              {draft.duplicate_candidates.map((m) => (
                <option key={m.deal_id} value={m.deal_id}>
                  Update {m.lead_code} · {m.company} ({m.status ?? "no status"}, {m.owner ?? "no owner"})
                </option>
              ))}
              <option value="new">Create a new lead</option>
            </select>
          </label>
          {draft.duplicate_candidates.length > 0 && (
            <ul className="match-reasons small muted">
              {draft.duplicate_candidates.slice(0, 3).map((m) => (
                <li key={m.deal_id}>
                  {m.lead_code}: {m.reasons.join("; ")} — score {Math.round(m.score * 100)}%
                </li>
              ))}
            </ul>
          )}
          {draft.duplicate_candidates.length > 1 && (
            <div className="notice dup">
              {draft.duplicate_candidates.length} existing records match this conversation — the CRM may already hold a
              duplicate. Pick the right one.
            </div>
          )}
        </div>

        <div className="fields">
          {FIELD_ORDER.map((k) => {
            const f = draft.fields[k];
            const opts = SELECT_OPTIONS[k];
            return (
              <div key={k} className={`field ${focus === k ? "focus" : ""}`} onClick={() => setFocus(k)}>
                <div className="row-between">
                  <label htmlFor={`f-${k}`}>{FIELD_LABELS[k]}</label>
                  {f?.value ? <ConfidencePill value={f.confidence} /> : <span className="muted small">not found</span>}
                </div>
                {opts ? (
                  <select id={`f-${k}`} value={values[k] ?? ""} onFocus={() => setFocus(k)} onChange={(e) => setValues({ ...values, [k]: e.target.value })}>
                    <option value="">—</option>
                    {opts.map((o) => (
                      <option key={o}>{o}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    id={`f-${k}`}
                    type={k === "next_step_date" ? "date" : "text"}
                    value={values[k] ?? ""}
                    onFocus={() => setFocus(k)}
                    onChange={(e) => setValues({ ...values, [k]: e.target.value })}
                  />
                )}
                {f?.evidence && <div className="evidence">“{f.evidence}”</div>}
                {f?.dropped_value && (
                  <div className="evidence dropped">Suggested “{f.dropped_value}” was removed: not found in the source.</div>
                )}
              </div>
            );
          })}
        </div>

        {draft.summary && (
          <section>
            <h3>Summary note</h3>
            <p>{draft.summary}</p>
          </section>
        )}

        {draft.followups.length > 0 && (
          <section>
            <h3>Follow-ups detected → reminders on confirm</h3>
            <ul className="plain">
              {draft.followups.map((f, i) => (
                <li key={i} className={focus === `fu:${i}` ? "focus" : ""} onClick={() => setFocus(`fu:${i}`)}>
                  <strong>{f.due_date ?? "no date"}</strong> — {f.reason}
                  <div className="muted small">Next: {f.suggested_next_step}</div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {draft.crosssell.length > 0 && (
          <section>
            <h3>Cross-sell ideas (this client's own history only)</h3>
            <ul className="plain">
              {draft.crosssell.map((c, i) => (
                <li key={i} className={focus === `cs:${i}` ? "focus" : ""} onClick={() => setFocus(`cs:${i}`)}>
                  <strong>{c.service ?? "New need"}</strong> — {c.rationale}
                </li>
              ))}
            </ul>
          </section>
        )}

        {error && <div className="error">{error}</div>}

        <div className="actions">
          {!discarding ? (
            <>
              <button className="primary" disabled={busy} onClick={confirm}>
                {Object.keys(edits).length ? `Confirm with ${Object.keys(edits).length} edit(s)` : "Confirm"}
              </button>
              <button disabled={busy} onClick={() => setDiscarding(true)}>
                Discard
              </button>
            </>
          ) : (
            <>
              <input placeholder="Reason (optional) — helps improve accuracy" value={reason} onChange={(e) => setReason(e.target.value)} />
              <button className="danger" disabled={busy} onClick={discard}>
                Discard draft
              </button>
              <button onClick={() => setDiscarding(false)}>Cancel</button>
            </>
          )}
        </div>
      </div>
      <SourceView source={draft.source} highlight={highlight} />
    </div>
  );
}
