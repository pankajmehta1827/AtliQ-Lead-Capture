import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AskAnswer, api } from "../api";
import { Icon } from "../components/ui";

type Msg = { role: "user" | "assistant"; content: string; result?: AskAnswer };

const SUGGESTIONS = [
  "Which deals need my attention today and why?",
  "What's blocking FinEdge and what should I do next?",
  "Which proposals have had no reply for more than 30 days?",
  "What did Acme ask for recently?",
  "Which existing clients mentioned a new need?",
  "Summarise NovaPharma: stakeholders, deadlines, risks.",
];

/** Minimal formatting for answers: paragraphs, "- " bullets and **bold**. */
function Formatted({ text }: { text: string }) {
  const blocks: JSX.Element[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) blocks.push(<ul key={`l${blocks.length}`}>{list.map((l, i) => <li key={i}>{bold(l)}</li>)}</ul>);
    list = [];
  };
  text.split("\n").forEach((line) => {
    const t = line.trim();
    if (/^[-*•]\s+/.test(t)) list.push(t.replace(/^[-*•]\s+/, ""));
    else {
      flush();
      if (t) blocks.push(<p key={`p${blocks.length}`}>{bold(t)}</p>);
    }
  });
  flush();
  return <>{blocks}</>;
}

function bold(s: string) {
  return s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part,
  );
}

export default function Ask() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // braces matter: newer browsers return a Promise from scrollIntoView, which React would treat as a cleanup
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, busy]);

  async function send(question: string) {
    const text = question.trim();
    if (!text || busy) return;
    const history = msgs.map((m) => ({ role: m.role, content: m.content }));
    setMsgs((m) => [...m, { role: "user", content: text }]);
    setQ("");
    setBusy(true);
    setError(null);
    try {
      const r = await api<AskAnswer>("/api/ask", { method: "POST", json: { question: text, history } });
      setMsgs((m) => [...m, { role: "assistant", content: r.answer, result: r }]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page ask-page">
      <div className="page-head">
        <div>
          <span className="crumb">Home</span>
          <h1>Ask your pipeline</h1>
          <p>Answers come only from your CRM and saved conversations, with the deals and quotes they rely on. Read-only.</p>
        </div>
        {msgs.length > 0 && <button onClick={() => setMsgs([])}>New chat</button>}
      </div>

      <div className="chat">
        {msgs.length === 0 && (
          <div className="chat-empty">
            <Icon name="sparkle" size={22} />
            <h3>What do you want to know about your deals?</h3>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="suggestion" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {msgs.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="msg user">
              {m.content}
            </div>
          ) : (
            <div key={i} className="msg assistant">
              <div className="msg-kicker">
                <Icon name="sparkle" size={12} /> {m.result?.mode === "llm" ? "AI answer" : "CRM lookup (no AI key)"}
              </div>
              <Formatted text={m.content} />
              {m.result && m.result.deals.length > 0 && (
                <div className="tags">
                  {m.result.deals.map((d) => (
                    <Link key={d.lead_code} to={`/deals/${d.deal_id}`} className="chip hot deal-chip">
                      {d.lead_code} · {d.company}
                    </Link>
                  ))}
                </div>
              )}
              {m.result && m.result.citations.length > 0 && (
                <details className="sources">
                  <summary>
                    Sources ({m.result.citations.length})
                    {m.result.citations.some((c) => !c.grounded) && " · some unverified"}
                  </summary>
                  <ul className="plain">
                    {m.result.citations.map((c, j) => (
                      <li key={j} className={c.grounded ? "" : "unverified"}>
                        <span className="small muted">{c.grounded ? "✓" : "⚠ not found in the records"} {c.lead_code ?? ""}</span>
                        <span className="evidence">“{c.quote}”</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          ),
        )}
        {busy && <div className="msg assistant thinking">Looking through the pipeline…</div>}
        {error && <div className="error">{error}</div>}
        <div ref={end} />
      </div>

      <form
        className="ask-box"
        onSubmit={(e) => {
          e.preventDefault();
          send(q);
        }}
      >
        <input
          autoFocus
          placeholder="Ask about a deal, an owner, a deadline… e.g. 'What's blocking FinEdge?'"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          maxLength={1000}
        />
        <button className="primary" disabled={busy || q.trim().length < 2}>
          Ask
        </button>
      </form>
    </div>
  );
}
