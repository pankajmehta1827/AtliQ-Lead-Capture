import { useCallback, useEffect, useState } from "react";
import { SourceItem, api } from "../api";

type Items = { items: SourceItem[]; counts: Record<string, number> };

export default function Capture({ onChange }: { onChange: () => void }) {
  const [data, setData] = useState<Items>({ items: [], counts: {} });
  const [rerun, setRerun] = useState<{ rules_drafts: number; queued: number; llm_enabled: boolean } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ channel: "email", subject: "", contact_name: "", contact_email: "", text: "" });

  const load = useCallback(() => {
    api<Items>("/api/capture/items").then(setData);
    api<{ rules_drafts: number; queued: number; llm_enabled: boolean }>("/api/capture/rerun").then(setRerun);
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  async function run<T>(fn: () => Promise<T>, done: (r: T) => string) {
    setBusy(true);
    setMsg(null);
    try {
      setMsg(done(await fn()));
      load();
      onChange();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const rerunWithAi = (limit: number) =>
    run(
      () => api<{ requeued: number }>(`/api/capture/rerun?limit=${limit}`, { method: "POST" }),
      (r) =>
        `Re-running ${r.requeued} conversation(s) with AI. New drafts replace the rules-mode ones in the review queue as they finish (about 1–2 per minute on the Groq free tier).`,
    );

  const syncSample = () =>
    run(
      () => api<{ queued: number; already_captured: number }>("/api/capture/sample", { method: "POST" }),
      (r) => `Queued ${r.queued} conversations (${r.already_captured} already captured). Processing runs in the background.`,
    );

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    run(
      () =>
        api("/api/capture", {
          method: "POST",
          json: {
            channel: form.channel,
            text: form.text,
            subject: form.subject || null,
            contact_name: form.contact_name || null,
            contact_email: form.contact_email || null,
          },
        }),
      () => {
        setForm({ ...form, text: "", subject: "" });
        return "Captured. The draft will appear in your review queue shortly.";
      },
    );
  };

  const upload = (files: FileList | null) => {
    if (!files?.length) return;
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    run(
      () => api<{ results: unknown[] }>("/api/capture/upload", { method: "POST", body: fd }),
      (r) => `Uploaded ${r.results.length} file(s).`,
    );
  };

  const retry = (id: number) => run(() => api(`/api/capture/items/${id}/retry`, { method: "POST" }), () => "Re-queued.");

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Capture</h1>
          <p className="muted">
            Connect conversations to the assistant. Personal and excluded items are skipped and never stored.
          </p>
        </div>
      </header>
      {msg && <div className="notice">{msg}</div>}
      {(data.counts.failed ?? 0) > 0 && (
        <div className="notice warn">
          {data.counts.failed} item(s) failed processing after retries (integration or AI unavailable). They are kept and can be retried below.
        </div>
      )}

      {rerun && rerun.rules_drafts > 0 && (
        <div className="blueprint card">
          <div className="row-between">
            <div>
              <h3>Re-run with AI</h3>
              <p className="muted small" style={{ margin: 0 }}>
                {rerun.rules_drafts} draft(s) in the review queue were made in rules mode (before an AI key was set), so their
                confidence is low. Re-running replaces them with AI drafts. Each conversation uses about 3–5k Groq tokens; the free
                tier allows roughly 200k a day, so run it in batches.
                {rerun.queued > 0 && <strong> {rerun.queued} conversation(s) are processing now.</strong>}
              </p>
            </div>
            <div className="row">
              <button className="primary blueprint" disabled={busy || !rerun.llm_enabled} onClick={() => rerunWithAi(20)}>
                Re-run next {Math.min(20, rerun.rules_drafts)}
              </button>
              <button disabled={busy || !rerun.llm_enabled} onClick={() => rerunWithAi(100)}>
                Re-run all {rerun.rules_drafts}
              </button>
            </div>
          </div>
          {!rerun.llm_enabled && <p className="error small">Set GROQ_API_KEY to enable re-running with AI.</p>}
        </div>
      )}

      <div className="grid-2">
        <div className="card">
          <h3>Mailbox & calendar sync</h3>
          <p className="muted small">
            Demo connector: syncs the AtliQ sample dataset (34 email threads and 16 meeting notes) as if read from
            the sellers' work mailboxes and calendars.
          </p>
          <button className="primary" disabled={busy} onClick={syncSample}>
            Sync sample mailbox & calendar
          </button>
          <h3 style={{ marginTop: 24 }}>Upload files</h3>
          <p className="muted small">Email threads or meeting notes as .md / .txt.</p>
          <input type="file" multiple accept=".md,.txt" onChange={(e) => upload(e.target.files)} />
          <div className="counts">
            {["queued", "processing", "processed", "skipped", "failed"].map((k) => (
              <div key={k}>
                <strong>{data.counts[k] ?? 0}</strong>
                <span className="muted small">{k}</span>
              </div>
            ))}
          </div>
        </div>

        <form className="card" onSubmit={submit}>
          <h3>Share a conversation</h3>
          <p className="muted small">Paste an email, your meeting notes, or a LinkedIn conversation (one-click share — no scraping).</p>
          <div className="form-grid">
            <label>
              Channel
              <select value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}>
                <option value="email">Email</option>
                <option value="meeting">Meeting notes</option>
                <option value="linkedin">LinkedIn</option>
              </select>
            </label>
            <label>
              Subject / title
              <input value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
            </label>
            <label>
              Contact name
              <input value={form.contact_name} onChange={(e) => setForm({ ...form, contact_name: e.target.value })} />
            </label>
            <label>
              Contact email
              <input type="email" value={form.contact_email} onChange={(e) => setForm({ ...form, contact_email: e.target.value })} />
            </label>
            <label className="span-2">
              Conversation
              <textarea rows={9} required minLength={10} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
            </label>
          </div>
          <button className="primary" disabled={busy || form.text.length < 10}>
            Capture
          </button>
        </form>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Channel</th>
              <th>Item</th>
              <th>Date</th>
              <th>Status</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((i) => (
              <tr key={i.id}>
                <td>{i.id}</td>
                <td>
                  <span className={`chip ch-${i.channel}`}>{i.channel}</span>
                </td>
                <td>
                  {i.subject ?? <span className="muted">(content not stored)</span>}
                  <div className="muted small">{i.external_ref}</div>
                </td>
                <td>{i.occurred_at}</td>
                <td>
                  <span className={`chip st-${i.status}`}>{i.status}</span>
                </td>
                <td className="small">
                  {i.skip_reason ?? i.category ?? ""}
                  {i.last_error && <div className="error small">{i.last_error.slice(0, 140)}</div>}
                  {i.status === "failed" && <button onClick={() => retry(i.id)}>Retry</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
