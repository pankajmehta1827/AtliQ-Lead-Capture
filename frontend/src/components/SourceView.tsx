import { SourceItem } from "../api";

function normalize(s: string) {
  return s.toLowerCase().replace(/\s+/g, " ");
}

/** Shows the original (masked) conversation and highlights the evidence for the focused field (FR-8). */
export default function SourceView({ source, highlight }: { source: SourceItem | null; highlight?: string | null }) {
  if (!source) return null;
  const body = source.body ?? "";
  let content: React.ReactNode = body;
  if (highlight && body) {
    // map normalised index back to the raw text by collapsing whitespace the same way
    const flat = body.replace(/\s+/g, " ");
    const idx = normalize(flat).indexOf(normalize(highlight).trim());
    if (idx >= 0) {
      const end = idx + normalize(highlight).trim().length;
      content = (
        <>
          {flat.slice(0, idx)}
          <mark ref={(el) => el?.scrollIntoView({ block: "center", behavior: "smooth" })}>{flat.slice(idx, end)}</mark>
          {flat.slice(end)}
        </>
      );
    }
  }
  return (
    <div className="source">
      <div className="source-head">
        <span className={`chip ch-${source.channel}`}>{source.channel}</span>
        <strong>{source.subject ?? "(no subject)"}</strong>
        <span className="muted small">
          {source.occurred_at} · {source.external_ref}
        </span>
      </div>
      <pre className="source-body">{content}</pre>
    </div>
  );
}
