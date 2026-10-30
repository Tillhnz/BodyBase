import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import ApiKeys from "../components/ApiKeys.jsx";
import { toast } from "../components/feedback.jsx";
import { Segmented, useAsync } from "../components/ui.jsx";
import { fmtNum } from "../fmt.js";
import { CATEGORY_ORDER, useMeta } from "../meta.js";
import { getTheme, setTheme } from "../theme.js";
import { useProviders } from "./Sources.jsx";

const num = (s) => (s === "" || s == null ? null : Number(String(s).replace(",", ".")));
const DEFAULT_HOME = ["weight", "resting_hr", "hrv", "sleep_duration", "readiness", "vo2max"];

function Profile({ user, onChange }) {
  const [f, setF] = useState({ name: user.name || "", height_cm: user.height_cm ?? "", birth_year: user.birth_year ?? "", sex: user.sex || "" });
  async function save(e) {
    e.preventDefault();
    try {
      onChange(await api.put("/me/profile", { name: f.name, height_cm: num(f.height_cm), birth_year: num(f.birth_year), sex: f.sex }));
      toast("Profil gespeichert");
    } catch (err) { toast(err.message, "error"); }
  }
  return (
    <form className="panel" onSubmit={save}>
      <h2>Profil</h2>
      <div className="form-grid">
        <label>Name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} maxLength={80} /></label>
        <label>Größe (cm)<input inputMode="decimal" value={f.height_cm} onChange={(e) => setF({ ...f, height_cm: e.target.value })} /></label>
        <label>Geburtsjahr<input inputMode="numeric" value={f.birth_year} onChange={(e) => setF({ ...f, birth_year: e.target.value })} /></label>
        <label>Geschlecht
          <select value={f.sex} onChange={(e) => setF({ ...f, sex: e.target.value })}>
            <option value="">keine Angabe</option><option value="f">weiblich</option><option value="m">männlich</option><option value="d">divers</option>
          </select>
        </label>
      </div>
      <div className="actions"><button className="btn primary">Speichern</button></div>
    </form>
  );
}

function Goals({ user, onChange }) {
  const g = { steps: 8000, active_minutes: 30, sleep_duration: 450, weight: null, ...(user.prefs?.goals || {}) };
  const [f, setF] = useState({ steps: g.steps ?? "", active_minutes: g.active_minutes ?? "", sleep_h: g.sleep_duration ? String(g.sleep_duration / 60).replace(".", ",") : "",
    weight: g.weight ?? "" });
  async function save(e) {
    e.preventDefault();
    const goals = { ...(user.prefs?.goals || {}), steps: num(f.steps), active_minutes: num(f.active_minutes),
      sleep_duration: num(f.sleep_h) != null ? Math.round(num(f.sleep_h) * 60) : null, weight: num(f.weight) };
    try {
      onChange(await api.put("/me/prefs", { goals }));
      toast("Ziele gespeichert");
    } catch (err) { toast(err.message, "error"); }
  }
  return (
    <form className="panel" onSubmit={save}>
      <h2>Ziele</h2>
      <p className="muted small">Die Ringe auf der Übersicht füllen sich mit diesen Tageszielen.</p>
      <div className="form-grid">
        <label>Schritte pro Tag<input inputMode="numeric" value={f.steps} onChange={(e) => setF({ ...f, steps: e.target.value })} /></label>
        <label>Aktive Minuten pro Tag<input inputMode="numeric" value={f.active_minutes} onChange={(e) => setF({ ...f, active_minutes: e.target.value })} /></label>
        <label>Schlaf (Stunden)<input inputMode="decimal" value={f.sleep_h} onChange={(e) => setF({ ...f, sleep_h: e.target.value })} /></label>
        <label>Zielgewicht (kg)<input inputMode="decimal" value={f.weight} onChange={(e) => setF({ ...f, weight: e.target.value })} placeholder="kein Ziel" /></label>
      </div>
      <div className="actions"><button className="btn primary">Speichern</button></div>
    </form>
  );
}

function HomeCards({ user, onChange }) {
  const meta = useMeta();
  const [sel, setSel] = useState(user.prefs?.home?.length ? user.prefs.home : DEFAULT_HOME);
  if (!meta) return null;
  function toggle(k) {
    setSel((s) => (s.includes(k) ? s.filter((x) => x !== k) : s.length >= 12 ? s : [...s, k]));
  }
  async function save() {
    try {
      onChange(await api.put("/me/prefs", { home: sel }));
      toast("Startseite gespeichert");
    } catch (err) { toast(err.message, "error"); }
  }
  return (
    <section className="panel">
      <h2>Werte auf der Übersicht</h2>
      <p className="muted small">Bis zu 12 Messgrößen, in der Reihenfolge, in der du sie anklickst.</p>
      {CATEGORY_ORDER.map((c) => (
        <div key={c} style={{ marginBottom: "0.7rem" }}>
          <div className="tiny muted" style={{ marginBottom: "0.3rem" }}>{meta.categories[c]}</div>
          <div className="chips">
            {meta.metrics.filter((m) => m.category === c).map((m) => (
              <button key={m.key} type="button" className={`chip cat-${c}${sel.includes(m.key) ? " on" : ""}`} onClick={() => toggle(m.key)}>
                <i />{m.label}{sel.includes(m.key) ? ` ${sel.indexOf(m.key) + 1}` : ""}
              </button>
            ))}
          </div>
        </div>
      ))}
      <div className="actions">
        <button className="btn primary" onClick={save}>Speichern</button>
        <button className="btn" onClick={() => setSel(DEFAULT_HOME)}>Standard</button>
      </div>
    </section>
  );
}

function Priority({ user, onChange }) {
  const meta = useMeta();
  const providers = useProviders();
  const custom = user.prefs?.priority || {};
  const base = custom._activities || null;
  const defaults = ["garmin", "polar", "suunto", "coros", "wahoo", "concept2", "hevy", "file", "strava", "intervals", "apple_health",
    "health_connect", "fitbit", "whoop", "oura", "withings", "manual", "api"];
  const [order, setOrder] = useState(base || defaults);
  const name = (k) => providers?.find((p) => p.key === k)?.name || k;
  const used = new Set((providers || []).filter((p) => p.connection || p.has_data).map((p) => p.key));
  const visible = order.filter((k) => used.has(k));
  function move(k, dir) {
    const vis = [...visible];
    const i = vis.indexOf(k), j = i + dir;
    if (j < 0 || j >= vis.length) return;
    [vis[i], vis[j]] = [vis[j], vis[i]];
    setOrder([...vis, ...order.filter((x) => !vis.includes(x))]);
  }
  async function save() {
    try {
      onChange(await api.put("/me/prefs", { priority: { ...custom, _activities: order } }));
      toast("Reihenfolge gespeichert. Neue Einheiten werden danach zugeordnet.");
    } catch (err) { toast(err.message, "error"); }
  }
  async function resetAll() {
    onChange(await api.put("/me/prefs", { priority: {} }));
    setOrder(defaults);
    toast("Alle Reihenfolgen zurückgesetzt");
  }
  const customMetrics = Object.keys(custom).filter((k) => k !== "_activities");
  return (
    <section className="panel">
      <h2>Datenquellen</h2>
      <p className="muted small">Kommt dieselbe Einheit von mehreren Quellen (z. B. Garmin und Strava), zählt die obere. Für Messwerte wie Schritte oder Gewicht legst du die Reihenfolge direkt bei der jeweiligen Messgröße fest.</p>
      {visible.length > 1 ? (
        <ul className="list">
          {visible.map((k, i) => (
            <li key={k} style={{ display: "flex", alignItems: "center", gap: "0.7rem", padding: "0.45rem 0" }}>
              <span className="pill">{i + 1}</span><span style={{ flex: 1 }}>{name(k)}</span>
              <button className="btn small" onClick={() => move(k, -1)} disabled={i === 0} aria-label="Nach oben">↑</button>
              <button className="btn small" onClick={() => move(k, 1)} disabled={i === visible.length - 1} aria-label="Nach unten">↓</button>
            </li>
          ))}
        </ul>
      ) : <p className="muted small">Erst mit mehreren Quellen für Aktivitäten gibt es hier etwas zu ordnen.</p>}
      {customMetrics.length > 0 && meta && (
        <p className="small">Eigene Reihenfolge für: {customMetrics.map((k, i) => <span key={k}>{i ? ", " : ""}<Link className="link" to={`/metric/${k}`}>{meta.byKey[k]?.label || k}</Link></span>)}</p>
      )}
      <div className="actions">
        {visible.length > 1 && <button className="btn primary" onClick={save}>Speichern</button>}
        {(customMetrics.length > 0 || base) && <button className="btn" onClick={resetAll}>Alles zurücksetzen</button>}
      </div>
    </section>
  );
}

function Account() {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [del, setDel] = useState("");
  async function changePw(e) {
    e.preventDefault();
    try {
      await api.put("/auth/password", { current_password: cur, new_password: next });
      setCur(""); setNext("");
      toast("Passwort geändert. Andere Geräte sind abgemeldet.");
    } catch (err) { toast(err.message, "error"); }
  }
  async function logoutAll() {
    await api.post("/auth/logout-all");
    toast("Alle anderen Geräte sind abgemeldet.");
  }
  async function remove(e) {
    e.preventDefault();
    try {
      await api.post("/me/delete", { password: del });
      window.location.href = "/login";
    } catch (err) { toast(err.message, "error"); }
  }
  return (
    <>
      <form className="panel" onSubmit={changePw}>
        <h2>Passwort</h2>
        <div className="form-grid">
          <label>Aktuelles Passwort<input type="password" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" required /></label>
          <label>Neues Passwort<input type="password" value={next} onChange={(e) => setNext(e.target.value)} minLength={8} autoComplete="new-password" required /></label>
        </div>
        <div className="actions"><button className="btn primary">Passwort ändern</button>
          <button type="button" className="btn" onClick={logoutAll}>Überall abmelden</button></div>
      </form>
      <section className="panel">
        <h2>Daten herunterladen</h2>
        <p className="muted small">Alle Messwerte, Aktivitäten und Nächte. Gehört dir, jederzeit.</p>
        <div className="actions">
          <a className="btn" href="/api/me/export?fmt=json" download>Als JSON</a>
          <a className="btn" href="/api/me/export?fmt=csv" download>Messwerte als CSV</a>
        </div>
      </section>
      <form className="panel" onSubmit={remove} style={{ borderColor: "color-mix(in srgb, var(--signal) 40%, var(--line))" }}>
        <h2>Konto löschen</h2>
        <p className="muted small">Löscht dein Konto mit allen Daten und Verbindungen. Das lässt sich nicht rückgängig machen.</p>
        <div className="copy-row">
          <input type="password" placeholder="Passwort zur Bestätigung" value={del} onChange={(e) => setDel(e.target.value)} required autoComplete="current-password" />
          <button className="btn danger">Konto löschen</button>
        </div>
      </form>
    </>
  );
}

export default function Settings({ user, onChange }) {
  const [theme, setThemeState] = useState(getTheme());
  const [{ data: overview }] = useAsync(() => api.get("/overview"), []);
  const total = overview ? Object.values(overview.metrics).reduce((s, m) => s + m.count, 0) : null;
  return (
    <>
      <div className="page-head">
        <div><h1>Einstellungen</h1><p>{user.email}{total != null ? ` · ${fmtNum(total)} gespeicherte Messwerte` : ""}</p></div>
        {user.is_admin && <div className="actions"><Link className="btn" to="/admin">Administration</Link></div>}
      </div>
      <div className="grid-2">
        <div>
          <Profile user={user} onChange={onChange} />
          <Goals user={user} onChange={onChange} />
          <section className="panel">
            <h2>Darstellung</h2>
            <Segmented value={theme} onChange={(v) => { setTheme(v); setThemeState(v); }} label="Darstellung"
              options={[{ value: "auto", label: "Wie das Gerät" }, { value: "light", label: "Hell" }, { value: "dark", label: "Dunkel" }]} />
          </section>
          <Priority user={user} onChange={onChange} />
        </div>
        <div>
          <HomeCards user={user} onChange={onChange} />
          <ApiKeys />
          <Account />
        </div>
      </div>
    </>
  );
}
