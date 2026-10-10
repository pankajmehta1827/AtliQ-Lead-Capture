import { useCallback, useEffect, useState } from "react";
import { EmailDraft, api } from "../api";
import Feedback from "./Feedback";
import { Icon } from "./ui";

/** #4 Follow-up email draft. The seller edits it and sends it from their own mailbox: the app never sends. */
export default function EmailDraftPanel({
  dealId,
  company,
  reminderIds,
  onClose,
}: {
  dealId: number;
  company: string | null;
  reminderIds?: number[];
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<EmailDraft | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const generate = useCallback(
    async (extra = "") => {
      setBusy(true);
      setError(null);
      try {
        const d = await api<EmailDraft>(`/api/deals/${dealId}/email-draft`, {
          method: "POST",
          json: { instructions: extra, reminder_ids: reminderIds ?? [] },
        });
        setDraft(d);
        setSubject(d.subject);
        setBody(d.body);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [dealId, reminderIds],
  );

  useEffect(() => {
    generate();
  }, [generate]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Copy failed: select the text and copy it manually.");
    }
  }

  const mailto = draft?.to_email
    ? `mailto:${encodeURIComponent(draft.to_email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
    : null;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} aria-label="Follow-up email draft">
        <header className="drawer-head">
          <div>
            <span className="kicker accent">
              <Icon name="sparkle" size={12} /> AI draft · you send it
            </span>
            <h2>Follow-up email</h2>
            <span className="muted small">
              {company} {draft?.lead_code ? `· ${draft.lead_code}` : ""}
            </span>
          </div>
          <button className="icon" onClick={onClose} title="Close (Esc)">
            ✕
          </button>
        </header>

        {busy && !draft && <div className="drawer-body muted">Writing a draft from the deal's history…</div>}
        {error && <div className="drawer-body error">{error}</div>}

        {draft && (
          <div className="drawer-body">
            <label>
              To
              <input value={draft.to_email ? `${draft.to_name ?? ""} <${draft.to_email}>` : "No contact email in the CRM"} readOnly />
            </label>
            <label>
              Subject
              <input value={subject} onChange={(e) => setSubject(e.target.value)} />
            </label>
            <label>
              Message
              <textarea rows={12} value={body} onChange={(e) => setBody(e.target.value)} />
            </label>

            {draft.facts.length > 0 && (
              <section className="facts">
                <h3>Facts used {draft.unverified > 0 && <span className="chip late">{draft.unverified} unverified</span>}</h3>
                <ul className="plain">
                  {draft.facts.map((f, i) => (
                    <li key={i} className={f.grounded ? "" : "unverified"}>
                      <span>{f.grounded ? "✓" : "⚠"} {f.fact}</span>
                      <span className="evidence">“{f.evidence}”</span>
                      {!f.grounded && <span className="small error">Not found in the deal's history: check or remove it.</span>}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <div className="regen">
              <input
                placeholder="Adjust: e.g. shorter, more formal, mention the SOW deadline…"
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && generate(instructions)}
              />
              <button disabled={busy} onClick={() => generate(instructions)}>
                {busy ? "Writing…" : "Regenerate"}
              </button>
            </div>
            <Feedback key={draft.subject + draft.body.length} feature="email_draft" dealId={dealId} refText={subject} />
          </div>
        )}

        {draft && (
          <footer className="drawer-foot">
            <span className="muted small">
              {draft.mode === "llm" ? "Written by AI from this deal's CRM record and conversations." : "Template (no AI key set)."} Nothing
              is sent from AtliQ Lead Assistant.
            </span>
            <div className="row">
              <button onClick={copy}>{copied ? "Copied" : "Copy"}</button>
              {mailto ? (
                <a className="button-link primary" href={mailto}>
                  Open in email app
                </a>
              ) : (
                <button className="primary" disabled title="No contact email in the CRM">
                  Open in email app
                </button>
              )}
            </div>
          </footer>
        )}
      </aside>
    </div>
  );
}
