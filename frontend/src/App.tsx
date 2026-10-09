import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { AppConfig, Deal, api, getSession, setSession } from "./api";
import { Icon, initials } from "./components/ui";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import ReviewQueue from "./pages/ReviewQueue";
import Pipeline from "./pages/Pipeline";
import CRM from "./pages/CRM";
import DealDetail from "./pages/DealDetail";
import Reminders from "./pages/Reminders";
import Ask from "./pages/Ask";
import Capture from "./pages/Capture";
import Summary from "./pages/Summary";
import Settings from "./pages/Settings";

const ROLES: Record<string, string> = {
  Bhavin: "Founder",
  Dhaval: "Founder",
  Karandeep: "CEO",
  Jay: "Sales executive",
};

type Counts = { drafts: number; due: number; leads: number };

type NavItem = { to: string; label: string; icon: string; hint: string; count?: number; badge?: boolean; ai?: boolean };

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [user, setUser] = useState<string | null>(getSession()?.user ?? null);
  const [counts, setCounts] = useState<Counts>({ drafts: 0, due: 0, leads: 0 });

  useEffect(() => {
    api<AppConfig>("/api/config").then(setConfig).catch(() => setConfig(null));
    const onUnauthorized = () => {
      setSession(null);
      setUser(null);
    };
    window.addEventListener("atliq-unauthorized", onUnauthorized);
    return () => window.removeEventListener("atliq-unauthorized", onUnauthorized);
  }, []);

  const refreshCounts = useCallback(() => {
    if (!user) return;
    const u = encodeURIComponent(user);
    Promise.all([
      api<unknown[]>(`/api/drafts?owner=${u}`),
      api<unknown[]>(`/api/reminders?due_only=true&owner=${u}`),
      api<unknown[]>(`/api/deals?owner=${u}`),
    ])
      .then(([d, r, l]) => setCounts({ drafts: d.length, due: r.length, leads: l.length }))
      .catch(() => undefined);
  }, [user]);

  useEffect(() => {
    refreshCounts();
    const t = setInterval(refreshCounts, 15000);
    return () => clearInterval(t);
  }, [refreshCounts]);

  if (!config) return <div className="boot">Connecting to the assistant…</div>;
  if (!user) return <Login config={config} onLogin={(u) => setUser(u)} />;

  // Ordered the way a seller works: act on today's work, bring in new conversations, look up deals,
  // then insight and admin. Badges sit on the page where the work is done.
  const sections: { title: string; items: NavItem[] }[] = [
    {
      title: "My day",
      items: [
        { to: "/dashboard", label: "Dashboard", icon: "dashboard", hint: "Today at a glance" },
        { to: "/follow-ups", label: "Follow-ups", icon: "bell", count: counts.due, badge: true,
          hint: "Deals to chase, with live timers" },
        { to: "/review", label: "Review queue", icon: "inbox", count: counts.drafts, badge: true,
          hint: "AI drafts waiting for your confirmation" },
      ],
    },
    {
      title: "Capture",
      items: [
        { to: "/capture", label: "Add conversation", icon: "plus", hint: "Paste, upload or sync emails and meeting notes" },
      ],
    },
    {
      title: "Deals",
      items: [
        { to: "/leads", label: "Pipeline", icon: "leads", count: counts.leads, hint: "Your open deals, flagged first" },
        { to: "/crm", label: "CRM records", icon: "database", hint: "Every lead: open, won and lost; import and export" },
      ],
    },
    {
      title: "Insights",
      items: [
        { to: "/ask", label: "Ask AI", icon: "sparkle", ai: true, hint: "Ask questions about your pipeline" },
        { to: "/summary", label: "Daily summary", icon: "doc", hint: "New drafts, due follow-ups, deals going cold" },
      ],
    },
    {
      title: "Admin",
      items: [{ to: "/settings", label: "Settings & log", icon: "settings", hint: "Exclusions, pause switch, action log" }],
    },
  ];

  return (
    <div className="shell">
      <div className="brand-cell">
        <span className="brand-mark">A</span>
        <span className="brand-name">AtliQ</span>
        <span className="brand-sub">Leads</span>
      </div>

      <TopBar user={user} due={counts.due} />

      <aside className="sidebar">
        <nav aria-label="Main">
          {sections.map((sec) => (
            <div className="nav-group" key={sec.title}>
              <span className="nav-label">{sec.title}</span>
              {sec.items.map((n) => (
                <NavLink key={n.to} to={n.to} title={n.hint} className={({ isActive }) => (isActive ? "active" : "")}>
                  <Icon name={n.icon} size={17} />
                  <span className="label">{n.label}</span>
                  {n.ai ? <span className="ai-tag">AI</span> : null}
                  {n.count ? <span className={`count ${n.badge ? "badge" : ""}`}>{n.count}</span> : null}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-status">
          <span className={`mode ${config.llm_mode}`}>
            {config.llm_mode === "llm" ? `AI · ${config.model}` : "Rules mode · no LLM key"}
          </span>
          {!config.processing_enabled && <span className="mode paused">Processing paused</span>}
        </div>
        <div className="user-block">
          <div className="avatar">{initials(user)}</div>
          <div className="who">
            <strong>{user}</strong>
            <span className="small muted">{ROLES[user] ?? "Sales"}</span>
          </div>
          <button
            className="link small"
            onClick={() => {
              setSession(null);
              setUser(null);
            }}
          >
            Switch
          </button>
        </div>
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard user={user} today={config.today} onChange={refreshCounts} />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/review" element={<ReviewQueue user={user} onChange={refreshCounts} />} />
          <Route path="/leads" element={<Pipeline user={user} />} />
          <Route path="/crm" element={<CRM user={user} />} />
          <Route path="/deals/:id" element={<DealDetail />} />
          <Route path="/follow-ups" element={<Reminders user={user} onChange={refreshCounts} />} />
          <Route path="/summary" element={<Summary user={user} />} />
          <Route path="/capture" element={<Capture onChange={refreshCounts} />} />
          <Route path="/settings" element={<Settings config={config} onConfig={setConfig} />} />
          {/* old paths */}
          <Route path="/today" element={<Navigate to="/dashboard" replace />} />
          <Route path="/pipeline" element={<Navigate to="/leads" replace />} />
          <Route path="/reminders" element={<Navigate to="/follow-ups" replace />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function TopBar({ user, due }: { user: string; due: number }) {
  const navigate = useNavigate();
  return (
    <header className="topbar">
      <DealSearch />
      <div className="topbar-right">
        <button className="ask-ai" onClick={() => navigate("/ask")} title="Ask your pipeline">
          <Icon name="sparkle" size={15} />
          Ask AI
        </button>
        <button className="icon" title={`${due} follow-up(s) due`} onClick={() => navigate("/follow-ups")}>
          <Icon name="bell" size={18} />
          {due > 0 && <span className="dot" />}
        </button>
        <button className="primary blueprint" onClick={() => navigate("/capture")}>
          <Icon name="plus" size={15} />
          New lead
        </button>
        <div className="vsep" />
        <div className="initials-box" title={user}>
          {initials(user)}
        </div>
      </div>
    </header>
  );
}

function DealSearch() {
  const [q, setQ] = useState("");
  const [deals, setDeals] = useState<Deal[] | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const results = useMemo(() => {
    if (!deals || q.trim().length < 2) return [];
    const s = q.toLowerCase();
    return deals
      .filter((d) => `${d.company} ${d.contact_name ?? ""} ${d.lead_code}`.toLowerCase().includes(s))
      .slice(0, 8);
  }, [deals, q]);

  return (
    <div className="search" ref={box}>
      <Icon name="search" size={14} />
      <input
        placeholder="Search leads, companies…"
        value={q}
        onFocus={() => {
          setOpen(true);
          if (!deals) api<Deal[]>("/api/deals?open_only=false").then(setDeals).catch(() => setDeals([]));
        }}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
      />
      {open && results.length > 0 && (
        <div className="search-results">
          {results.map((d) => (
            <Link key={d.id} to={`/deals/${d.id}`} onClick={() => setOpen(false)}>
              <strong>{d.company}</strong>{" "}
              <span className="small muted">
                {d.lead_code} · {d.contact_name ?? "no contact"} · {d.status ?? "no status"}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
