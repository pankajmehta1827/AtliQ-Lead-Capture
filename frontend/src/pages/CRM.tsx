import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Deal, SERVICES, SOURCES, STAGES, api, getSession, money } from "../api";
import { Corners, Icon } from "../components/ui";

type CrmLead = Deal & {
  origin: "crm_export" | "ai_capture" | "manual" | "import";
  ai_updates: number;
  last_ai_update: string | null;
  pending_ai_drafts: number;
};

type Sync = {
  ai_created: number;
  ai_updated: number;
  writes: number;
  last_sync: string | null;
  pending_drafts: number;
  recent: {
    deal_id: number;
    lead_code: string;
    company: string;
    kind: "created" | "updated";
    fields: string[];
    actor: string;
    at: string;
    source: string | null;
    channel: string | null;
  }[];
};

const ORIGIN: Record<CrmLead["origin"], { label: string; cls: string }> = {
  crm_export: { label: "CRM export", cls: "" },
  ai_capture: { label: "AI capture", cls: "hot" },
  manual: { label: "Manual", cls: "ghost" },
  import: { label: "Import", cls: "ghost" },
};

const COLS: { key: keyof CrmLead; label: string; num?: boolean }[] = [
  { key: "lead_code", label: "Lead" },
  { key: "company", label: "Company / contact" },
  { key: "source", label: "Source" },
  { key: "service_interest", label: "Service" },
  { key: "status", label: "Status" },
  { key: "est_value_usd", label: "Value", num: true },
  { key: "owner", label: "Owner" },
  { key: "last_contact_date", label: "Last contact" },
  { key: "next_followup_date", label: "Next follow-up" },
  { key: "origin", label: "Origin" },
];

function ago(iso: string | null) {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(1, mins)} min ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`;
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

async function download(path: string, fallbackName: string) {
  const s = getSession();
  const res = await fetch(path, { headers: { "X-User": s?.user ?? "", "X-Access-Code": s?.code ?? "" } });
  if (!res.ok) throw new Error(res.statusText);
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export default function CRM({ user }: { user: string }) {
  const [leads, setLeads] = useState<CrmLead[] | null>(null);
  const [sync, setSync] = useState<Sync | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [owner, setOwner] = useState("");
  const [origin, setOrigin] = useState("");
  const [sort, setSort] = useState<{ key: keyof CrmLead; dir: 1 | -1 }>({ key: "lead_code", dir: 1 });
  const [msg, setMsg] = useState<{ text: string; warn?: boolean } | null>(null);
  const [adding, setAdding] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    api<CrmLead[]>("/api/crm/leads").then(setLeads);
    api<Sync>("/api/crm/sync").then(setSync);
  }, []);
  useEffect(load, [load]);

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    const rows = (leads ?? []).filter((l) => {
      if (s && !`${l.lead_code} ${l.company} ${l.contact_name ?? ""} ${l.contact_email ?? ""} ${l.notes ?? ""}`.toLowerCase().includes(s)) return false;
      if (status === "open" && !l.is_open) return false;
      if (status === "none" && l.status) return false;
      if (!["all", "open", "none"].includes(status) && l.status !== status) return false;
      if (owner && l.owner !== owner) return false;
      if (origin === "ai" && l.origin !== "ai_capture" && !l.ai_updates) return false;
      if (origin && origin !== "ai" && l.origin !== origin) return false;
      return true;
    });
    return rows.sort((a, b) => {
      const x = a[sort.key] ?? "";
      const y = b[sort.key] ?? "";
      return (x > y ? 1 : x < y ? -1 : 0) * sort.dir;
    });
  }, [leads, q, status, owner, origin, sort]);

  const totals = useMemo(() => {
    const all = leads ?? [];
    const open = all.filter((l) => l.is_open);
    return {
      all: all.length,
      open: open.length,
      won: all.filter((l) => l.status === "Won").length,
      openValue: open.reduce((s, l) => s + (l.est_value_usd ?? 0), 0),
    };
  }, [leads]);

  async function onImport(file: File | undefined) {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("update_existing", "true");
    try {
      const r = await api<{ created: number; updated: number; skipped: number; errors: string[] }>("/api/crm/import", {
        method: "POST",
        body: fd,
      });
      setMsg({
        text: `Imported ${file.name}: ${r.created} new, ${r.updated} updated, ${r.skipped} skipped.${r.errors.length ? " " + r.errors.slice(0, 3).join("; ") : ""}`,
        warn: r.errors.length > 0,
      });
      load();
    } catch (e) {
      setMsg({ text: (e as Error).message, warn: true });
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="crumb">Home</span>
          <h1>CRM</h1>
          <span className="muted">
            {totals.all} leads · {totals.open} open ({money(totals.openValue)}) · {totals.won} won. The system of record the AI Lead
            app writes into.
          </span>
        </div>
        <div className="row">
          <button onClick={() => download("/api/crm/export?format=csv", "atliq_crm.csv")}>Export CSV</button>
          <button onClick={() => download("/api/crm/export?format=xlsx", "atliq_crm.xlsx")}>Export Excel</button>
          <button onClick={() => fileRef.current?.click()}>Import CSV / Excel</button>
          <input ref={fileRef} type="file" accept=".csv,.xlsx" hidden onChange={(e) => onImport(e.target.files?.[0])} />
          <button className="primary blueprint" onClick={() => setAdding(true)}>
            <Corners />
            <Icon name="plus" size={15} />
            Add lead
          </button>
        </div>
      </div>

      {msg && <div className={`notice ${msg.warn ? "warn" : ""}`}>{msg.text}</div>}
      {adding && (
        <AddLead
          user={user}
          onClose={() => setAdding(false)}
          onCreated={(d) => {
            setAdding(false);
            setMsg({ text: `${d.lead_code} · ${d.company} added to the CRM.` });
            load();
          }}
        />
      )}

      {sync && (
        <section className="panel blueprint">
          <Corners />
          <div className="panel-head">
            <Icon name="sparkle" size={17} />
            <div>
              <h2>AI Lead app → CRM</h2>
              <span className="sub">
                The AI never writes on its own: every change below is a draft an owner confirmed in the Review queue.
              </span>
            </div>
            <Link to="/review">
              <button>
                {sync.pending_drafts} draft{sync.pending_drafts === 1 ? "" : "s"} waiting
              </button>
            </Link>
          </div>
          <div className="sync-grid">
            <div className="sync-stats">
              <div>
                <span className="label">Leads created by AI</span>
                <span className="value">{sync.ai_created}</span>
              </div>
              <div>
                <span className="label">Leads updated by AI</span>
                <span className="value">{sync.ai_updated}</span>
              </div>
              <div>
                <span className="label">Last sync</span>
                <span className="value small-value">{ago(sync.last_sync)}</span>
              </div>
            </div>
            <ul className="sync-feed">
              {sync.recent.length === 0 && <li className="muted small">No AI writes yet. Confirm a draft in the Review queue.</li>}
              {sync.recent.slice(0, 6).map((r, i) => (
                <li key={i}>
                  <span className={`chip ${r.kind === "created" ? "hot" : ""}`}>{r.kind}</span>{" "}
                  <Link to={`/deals/${r.deal_id}`}>
                    <strong>{r.lead_code}</strong> {r.company}
                  </Link>
                  {r.fields.length > 0 && <span className="muted small"> · {r.fields.join(", ")}</span>}
                  <div className="muted small">
                    {r.channel && `from ${r.channel}: ${r.source ?? ""} · `}confirmed by {r.actor} · {ago(r.at)}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      <div className="toolbar">
        <input placeholder="Search lead id, company, contact, notes…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="all">All statuses</option>
          <option value="open">Open only</option>
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
          <option value="none">No status</option>
        </select>
        <select value={owner} onChange={(e) => setOwner(e.target.value)}>
          <option value="">All owners</option>
          {["Bhavin", "Dhaval", "Karandeep", "Jay"].map((u) => (
            <option key={u}>{u}</option>
          ))}
        </select>
        <select value={origin} onChange={(e) => setOrigin(e.target.value)}>
          <option value="">Any origin</option>
          <option value="ai">Touched by AI</option>
          <option value="ai_capture">Created by AI</option>
          <option value="crm_export">CRM export</option>
          <option value="manual">Manual</option>
          <option value="import">Import</option>
        </select>
        <span className="muted small">{shown.length} shown</span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {COLS.map((c) => (
                <th
                  key={c.key}
                  className={`sortable ${c.num ? "num" : ""}`}
                  onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? (-s.dir as 1 | -1) : 1 }))}
                >
                  {c.label}
                  {sort.key === c.key ? (sort.dir === 1 ? " ↑" : " ↓") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((l) => (
              <tr key={l.id} className="clickable" onClick={() => navigate(`/deals/${l.id}`)}>
                <td className="mono">{l.lead_code}</td>
                <td>
                  <strong>{l.company}</strong>
                  <div className="muted small">
                    {l.contact_name ?? "no contact"}
                    {l.contact_email ? ` · ${l.contact_email}` : ""}
                  </div>
                </td>
                <td>{l.source ?? <span className="muted">—</span>}</td>
                <td>{l.service_interest ?? <span className="muted">—</span>}</td>
                <td>
                  <span className={`chip ${l.status === "Won" ? "st-processed" : l.status === "Lost" ? "st-skipped" : l.status ? "" : "warn"}`}>
                    {l.status ?? "No status"}
                  </span>
                </td>
                <td className="num value-cell">{money(l.est_value_usd)}</td>
                <td>{l.owner ?? <span className="muted">—</span>}</td>
                <td>
                  {l.last_contact_date ?? <span className="muted">never</span>}
                  {l.is_open && l.flags.includes("inactive") && <div className="small overdue">inactive</div>}
                </td>
                <td>{l.next_followup_date ?? (l.is_open ? <span className="small overdue">none</span> : <span className="muted">—</span>)}</td>
                <td>
                  <div className="tags">
                    <span className={`chip ${ORIGIN[l.origin].cls}`}>{ORIGIN[l.origin].label}</span>
                    {l.ai_updates > 0 && <span className="chip hot">AI updated ×{l.ai_updates}</span>}
                    {l.pending_ai_drafts > 0 && <span className="chip warn">{l.pending_ai_drafts} draft pending</span>}
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

function AddLead({ user, onClose, onCreated }: { user: string; onClose: () => void; onCreated: (d: Deal) => void }) {
  const [f, setF] = useState({
    company: "", contact_name: "", contact_email: "", source: "", service_interest: "", status: "New",
    est_value_usd: "", owner: user, next_step: "", next_followup_date: "", notes: "",
  });
  const [dupes, setDupes] = useState<{ lead_code: string; company: string; deal_id: number; reasons: string[] }[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function save(force: boolean) {
    setError(null);
    const s = getSession();
    const res = await fetch("/api/crm/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-User": s?.user ?? "", "X-Access-Code": s?.code ?? "" },
      body: JSON.stringify({
        ...f,
        est_value_usd: f.est_value_usd ? Number(f.est_value_usd) : null,
        next_followup_date: f.next_followup_date || null,
        force,
      }),
    });
    const data = await res.json();
    if (res.status === 409) return setDupes(data.detail.matches);
    if (!res.ok) return setError(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
    onCreated(data);
  }

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value });

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <form
        className="dialog"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          save(false);
        }}
      >
        <h2>Add lead</h2>
        <div className="form-grid">
          <label className="span-2">
            Company *
            <input required minLength={2} value={f.company} onChange={set("company")} autoFocus />
          </label>
          <label>
            Contact name
            <input value={f.contact_name} onChange={set("contact_name")} />
          </label>
          <label>
            Contact email
            <input type="email" value={f.contact_email} onChange={set("contact_email")} />
          </label>
          <label>
            Source
            <select value={f.source} onChange={set("source")}>
              <option value="">—</option>
              {SOURCES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label>
            Service
            <select value={f.service_interest} onChange={set("service_interest")}>
              <option value="">—</option>
              {SERVICES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label>
            Status
            <select value={f.status} onChange={set("status")}>
              {STAGES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label>
            Value (USD)
            <input type="number" min={0} value={f.est_value_usd} onChange={set("est_value_usd")} />
          </label>
          <label>
            Owner
            <select value={f.owner} onChange={set("owner")}>
              {["Bhavin", "Dhaval", "Karandeep", "Jay"].map((u) => (
                <option key={u}>{u}</option>
              ))}
            </select>
          </label>
          <label>
            Next follow-up
            <input type="date" value={f.next_followup_date} onChange={set("next_followup_date")} />
          </label>
          <label className="span-2">
            Next step
            <input value={f.next_step} onChange={set("next_step")} />
          </label>
          <label className="span-2">
            Notes
            <textarea rows={3} value={f.notes} onChange={set("notes")} />
          </label>
        </div>
        {dupes && (
          <div className="notice dup">
            This looks like an existing lead:
            <ul>
              {dupes.map((d) => (
                <li key={d.deal_id}>
                  <Link to={`/deals/${d.deal_id}`}>
                    {d.lead_code} {d.company}
                  </Link>{" "}
                  <span className="small muted">({d.reasons.join("; ")})</span>
                </li>
              ))}
            </ul>
            <button type="button" onClick={() => save(true)}>
              Create anyway
            </button>
          </div>
        )}
        {error && <div className="error">{error}</div>}
        <div className="actions" style={{ justifyContent: "flex-end" }}>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" type="submit">
            Save lead
          </button>
        </div>
      </form>
    </div>
  );
}
