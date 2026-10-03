import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { AppConfig, Deal, api, getSession, setSession } from "./api";
import { Corners, Icon, initials } from "./components/ui";
import Login from "./pages/Login";
import Today from "./pages/Today";
import ReviewQueue from "./pages/ReviewQueue";
import Pipeline from "./pages/Pipeline";
import DealDetail from "./pages/DealDetail";
import Reminders from "./pages/Reminders";
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

function greeting(today: Date) {
  // the dataset runs on a fixed "today"; the greeting follows the real clock
  const h = new Date().getHours();
  const part = h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
  return { part, date: today.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }) };
}

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

  const g = greeting(new Date(config.today));
  const nav = [
    { to: "/today", label: "Today", icon: "today", count: counts.due, hot: true },
    { to: "/review", label: "Review queue", icon: "inbox", count: counts.drafts, hot: true },
    { to: "/leads", label: "Leads", icon: "leads", count: counts.leads },
    { to: "/follow-ups", label: "Follow-ups", icon: "bell" },
    { to: "/capture", label: "Capture", icon: "plus" },
  ];
  const navSecondary = [
    { to: "/summary", label: "Daily summary", icon: "doc" },
    { to: "/settings", label: "Settings & log", icon: "settings" },
  ];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand">
            <span className="brand-mark" />
            AtliQ
          </div>
          <div className="brand-sub">Lead Assistant</div>
        </div>
        <nav>
          {nav.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon name={n.icon} />
              <span className="label">{n.label}</span>
              {n.count ? <span className={`count ${n.hot ? "hot" : ""}`}>{n.count}</span> : null}
            </NavLink>
          ))}
          <div className="nav-sep" />
          {navSecondary.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon name={n.icon} />
              <span className="label">{n.label}</span>
            </NavLink>
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

      <div className="main">
        <header className="topbar">
          <div className="title">
            <span className="kicker">{g.date}</span>
            <h1>
              Good {g.part}, {user}
            </h1>
          </div>
          <DealSearch />
          <CaptureButton />
        </header>
        <div className="scroll">
          <Routes>
            <Route path="/" element={<Navigate to="/today" replace />} />
            <Route path="/today" element={<Today user={user} onChange={refreshCounts} />} />
            <Route path="/review" element={<ReviewQueue user={user} onChange={refreshCounts} />} />
            <Route path="/leads" element={<Pipeline user={user} />} />
            <Route path="/deals/:id" element={<DealDetail />} />
            <Route path="/follow-ups" element={<Reminders user={user} onChange={refreshCounts} />} />
            <Route path="/summary" element={<Summary user={user} />} />
            <Route path="/capture" element={<Capture onChange={refreshCounts} />} />
            <Route path="/settings" element={<Settings config={config} onConfig={setConfig} />} />
            {/* old paths */}
            <Route path="/pipeline" element={<Navigate to="/leads" replace />} />
            <Route path="/reminders" element={<Navigate to="/follow-ups" replace />} />
            <Route path="*" element={<Navigate to="/today" replace />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}

function CaptureButton() {
  const navigate = useNavigate();
  return (
    <button className="primary blueprint wide" onClick={() => navigate("/capture")}>
      <Corners />
      Capture lead
      <Icon name="arrow" size={14} />
    </button>
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
