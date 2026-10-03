import { useCallback, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { AppConfig, api, getSession, setSession } from "./api";
import Login from "./pages/Login";
import ReviewQueue from "./pages/ReviewQueue";
import Pipeline from "./pages/Pipeline";
import DealDetail from "./pages/DealDetail";
import Reminders from "./pages/Reminders";
import Capture from "./pages/Capture";
import Summary from "./pages/Summary";
import Settings from "./pages/Settings";

const NAV = [
  { to: "/review", label: "Review queue" },
  { to: "/pipeline", label: "Pipeline" },
  { to: "/reminders", label: "Reminders" },
  { to: "/summary", label: "Daily summary" },
  { to: "/capture", label: "Capture" },
  { to: "/settings", label: "Settings & log" },
];

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [user, setUser] = useState<string | null>(getSession()?.user ?? null);
  const [counts, setCounts] = useState<{ drafts: number; due: number }>({ drafts: 0, due: 0 });

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
    Promise.all([
      api<unknown[]>(`/api/drafts?owner=${encodeURIComponent(user)}`),
      api<unknown[]>(`/api/reminders?due_only=true&owner=${encodeURIComponent(user)}`),
    ])
      .then(([d, r]) => setCounts({ drafts: d.length, due: r.length }))
      .catch(() => undefined);
  }, [user]);

  useEffect(() => {
    refreshCounts();
    const t = setInterval(refreshCounts, 15000);
    return () => clearInterval(t);
  }, [refreshCounts]);

  if (!config) return <div className="boot">Connecting to the assistant…</div>;
  if (!user) return <Login config={config} onLogin={(u) => setUser(u)} />;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">A</span>
          <div>
            <strong>AtliQ</strong>
            <small>Lead Assistant</small>
          </div>
        </div>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : "")}>
              {n.label}
              {n.to === "/review" && counts.drafts > 0 && <span className="count">{counts.drafts}</span>}
              {n.to === "/reminders" && counts.due > 0 && <span className="count warn">{counts.due}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className={`mode ${config.llm_mode}`}>
            {config.llm_mode === "llm" ? `AI: ${config.model}` : "Rules mode (no LLM key)"}
          </div>
          {!config.processing_enabled && <div className="mode paused">Processing paused</div>}
          <div className="muted small">Today: {config.today}</div>
          <div className="user-row">
            <span>{user}</span>
            <button
              className="link"
              onClick={() => {
                setSession(null);
                setUser(null);
              }}
            >
              Switch
            </button>
          </div>
        </div>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/review" replace />} />
          <Route path="/review" element={<ReviewQueue user={user} onChange={refreshCounts} />} />
          <Route path="/pipeline" element={<Pipeline user={user} />} />
          <Route path="/deals/:id" element={<DealDetail />} />
          <Route path="/reminders" element={<Reminders user={user} onChange={refreshCounts} />} />
          <Route path="/summary" element={<Summary user={user} />} />
          <Route path="/capture" element={<Capture onChange={refreshCounts} />} />
          <Route path="/settings" element={<Settings config={config} onConfig={setConfig} />} />
          <Route path="*" element={<Navigate to="/review" replace />} />
        </Routes>
      </main>
    </div>
  );
}
