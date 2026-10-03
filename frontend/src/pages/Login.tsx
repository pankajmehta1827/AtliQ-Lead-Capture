import { useState } from "react";
import { AppConfig, api, setSession } from "../api";
import { Corners, Icon } from "../components/ui";

export default function Login({ config, onLogin }: { config: AppConfig; onLogin: (u: string) => void }) {
  const [user, setUser] = useState(config.users[0] ?? "");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSession({ user, code });
    try {
      await api("/api/me");
      onLogin(user);
    } catch (err) {
      setSession(null);
      setError((err as Error).message);
    }
  }

  return (
    <div className="login">
      <form className="blueprint login-card" onSubmit={submit}>
        <Corners />
        <div>
          <div className="brand">
            <span className="brand-mark" />
            AtliQ
          </div>
          <div className="brand-sub">Lead Assistant</div>
        </div>
        <label>
          I am
          <select value={user} onChange={(e) => setUser(e.target.value)}>
            {config.users.map((u) => (
              <option key={u}>{u}</option>
            ))}
          </select>
        </label>
        {config.requires_access_code && (
          <label>
            Access code
            <input type="password" value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
          </label>
        )}
        {error && <div className="error">{error}</div>}
        <button className="primary blueprint wide" type="submit">
          <Corners />
          Continue
          <Icon name="arrow" size={14} />
        </button>
        <p className="muted small">
          The assistant drafts CRM records from your conversations. Nothing is saved to the CRM until you confirm it,
          and it never contacts clients.
        </p>
      </form>
    </div>
  );
}
