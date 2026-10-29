import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import ThemeToggle from "../components/ThemeToggle.jsx";

const SOURCES = ["Garmin", "Apple Health", "Strava", "Withings", "Oura", "WHOOP", "Fitbit", "Polar", "Suunto", "Wahoo", "intervals.icu",
  "Concept2", "Hevy", "Home Assistant", "Nightscout", "Dexcom", "Health Connect", "FIT · GPX · TCX", "CSV"];

function Orbit() {
  const rings = [
    { r: 150, c: "var(--c-activity)", len: 0.78 },
    { r: 118, c: "var(--c-heart)", len: 0.64 },
    { r: 86, c: "var(--c-sleep)", len: 0.86 },
    { r: 54, c: "var(--c-body)", len: 0.52 },
  ];
  return (
    <div className="login-orbit" aria-hidden="true">
      <svg viewBox="-170 -170 340 340">
        {rings.map((g, i) => (
          <g key={g.r} transform={`rotate(${-90 + i * 34})`}>
            <circle r={g.r} fill="none" stroke="var(--line)" strokeWidth="14" />
            <circle className="orbit-ring" r={g.r} stroke={g.c} strokeWidth="14" pathLength="1"
              strokeDasharray={`${g.len} 1`} style={{ animationDelay: `${i * 160}ms` }} />
          </g>
        ))}
        <circle r="16" fill="var(--iris)" />
      </svg>
    </div>
  );
}

export default function Login({ onLoggedIn }) {
  const navigate = useNavigate();
  const params = new URLSearchParams(window.location.search);
  const inviteParam = params.get("invite") || "";
  const [cfg, setCfg] = useState({ allow_registration: false, first_user: false });
  const [mode, setMode] = useState(inviteParam ? "register" : "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [invite, setInvite] = useState(inviteParam);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/config").then((c) => { setCfg(c); if (c.first_user) setMode("register"); }).catch(() => {});
  }, []);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "login") await api.post("/auth/login", { email, password });
      else await api.post("/auth/register", { email, password, name: name || null, invite: invite.trim() || null });
      await onLoggedIn();
      navigate("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const title = mode === "login" ? "Anmelden" : cfg.first_user ? "Willkommen" : "Konto anlegen";
  return (
    <div className="login">
      <ThemeToggle className="theme-toggle-corner" />
      <div className="login-art">
        <Orbit />
        <h1>BodyBase</h1>
        <p>Alles, was deine Uhr, Waage, dein Ring und deine Apps über dich wissen, an einem Ort und auf deinem eigenen Server.</p>
        <div className="login-sources" aria-label="Unterstützte Quellen">{SOURCES.map((s) => <span key={s}>{s}</span>)}</div>
      </div>
      <form className="login-form" onSubmit={submit}>
        <h1>{title}</h1>
        {cfg.first_user && mode === "register" && (
          <p className="muted">Das erste Konto wird Administrator. Danach können nur Eingeladene ein Konto anlegen.</p>
        )}
        {mode === "register" && (
          <label>Name <span className="hint">(optional)</span>
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} autoComplete="given-name" />
          </label>
        )}
        <label>E-Mail
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus autoComplete="email" />
        </label>
        <label>Passwort
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
            minLength={mode === "register" ? 8 : undefined} autoComplete={mode === "login" ? "current-password" : "new-password"} />
          {mode === "register" && <span className="hint">Mindestens 8 Zeichen.</span>}
        </label>
        {mode === "register" && !cfg.allow_registration && (
          <label>Einladungscode
            <input value={invite} onChange={(e) => setInvite(e.target.value)} maxLength={32} autoComplete="off" />
            <span className="hint">Die Registrierung ist geschlossen. Den Code bekommst du vom Administrator.</span>
          </label>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn primary" disabled={busy}>{mode === "login" ? "Anmelden" : "Konto anlegen"}</button>
        {!cfg.first_user && (
          <button type="button" className="link" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
            {mode === "login" ? "Noch kein Konto? Konto anlegen" : "Schon ein Konto? Anmelden"}
          </button>
        )}
      </form>
    </div>
  );
}
