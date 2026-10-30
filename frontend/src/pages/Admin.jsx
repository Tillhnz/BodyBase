import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { Loading, confirmDialog, toast } from "../components/feedback.jsx";
import { CopyField, Kpi, ProviderLogo, Switch, useAsync } from "../components/ui.jsx";
import { fmtAgo, fmtNum } from "../fmt.js";

const TABS = [
  { value: "overview", label: "Übersicht" }, { value: "providers", label: "Anbieter" }, { value: "users", label: "Konten" },
  { value: "server", label: "Server" }, { value: "log", label: "Protokoll" },
];

function bytes(n) {
  if (n == null) return "–";
  if (n > 1e9) return `${fmtNum(n / 1e9, 1)} GB`;
  return `${fmtNum(n / 1e6, 0)} MB`;
}

function Overview() {
  const [{ data: st }] = useAsync(() => api.get("/admin/status"), []);
  const [upd, setUpd] = useState(null);
  const [checking, setChecking] = useState(false);
  const [{ data: backups }, setBackups] = useAsync(() => api.get("/admin/backups").catch(() => null), []);
  useEffect(() => {
    if (upd?.job?.state !== "running" && upd?.job?.state !== "restarting") return undefined;
    const id = setInterval(() => api.get("/admin/update").then(setUpd).catch(() => {}), 3000);
    return () => clearInterval(id);
  }, [upd?.job?.state]);
  async function check() {
    setChecking(true);
    try { setUpd(await api.get("/admin/update?check=true")); } catch (e) { toast(e.message, "error"); } finally { setChecking(false); }
  }
  async function update() {
    if (!(await confirmDialog("Vorher wird die Datenbank gesichert. BodyBase ist während des Updates ein paar Minuten nicht erreichbar.", { title: "Jetzt aktualisieren?", confirmLabel: "Aktualisieren", danger: false }))) return;
    try { await api.post("/admin/update"); setUpd(await api.get("/admin/update")); } catch (e) { toast(e.message, "error"); }
  }
  async function backup() {
    try { const r = await api.post("/admin/backups"); toast(`Gesichert: ${r.name}`); setBackups(await api.get("/admin/backups")); } catch (e) { toast(e.message, "error"); }
  }
  if (!st) return <Loading rows={1} />;
  const conns = st.connections || {};
  return (
    <>
      <div className="kpis">
        <Kpi label="Konten" value={fmtNum(st.users)} />
        <Kpi label="Messwerte" value={fmtNum(st.samples)} />
        <Kpi label="Aktivitäten" value={fmtNum(st.activities)} />
        <Kpi label="Nächte" value={fmtNum(st.sleep)} />
        <Kpi label="Datenbank" value={bytes(st.db_bytes)} />
        <Kpi label="Verbindungen" value={fmtNum(Object.values(conns).reduce((a, b) => a + b, 0))}
          sub={conns.error || conns.auth ? `${(conns.error || 0) + (conns.auth || 0)} mit Problemen` : "alle in Ordnung"} />
      </div>
      <div className="grid-2">
        <section className="panel">
          <div className="panel-head"><h2>Updates</h2></div>
          {!st.updater ? <p className="muted small">Der Update-Dienst ist nicht erreichbar. Im Container aktualisierst du mit <code>bodybase update</code>.</p> : (
            <>
              {upd?.version && <p className="small">Installiert: <code>{upd.version.commit}</code> vom {upd.version.date}</p>}
              {upd?.behind === 0 && <p className="ok small">BodyBase ist aktuell.</p>}
              {upd?.behind > 0 && (
                <>
                  <p><strong>{upd.behind} neue Änderungen</strong></p>
                  <ul className="small muted">{upd.changes.map((c) => <li key={c}>{c}</li>)}</ul>
                </>
              )}
              {upd?.check_error && <p className="error small">{upd.check_error}</p>}
              {upd?.job?.state === "running" || upd?.job?.state === "restarting" ? <p className="small"><span className="pill iris"><span className="live" />Update läuft</span></p> : null}
              {upd?.job?.state === "done" && <p className="ok small">Update abgeschlossen. Lade die Seite neu.</p>}
              {upd?.job?.state === "failed" && <p className="error small">{upd.job.error}</p>}
              <div className="actions">
                <button className="btn" onClick={check} disabled={checking}>{checking ? "Prüfe …" : "Nach Updates suchen"}</button>
                {upd?.behind > 0 && <button className="btn primary" onClick={update}>Jetzt aktualisieren</button>}
              </div>
            </>
          )}
        </section>
        <section className="panel">
          <div className="panel-head"><h2>Sicherungen</h2></div>
          {backups ? (
            <>
              <p className="muted small">Liegen auf dem Server im Ordner <code>backups/</code> des Projekts. Die letzten 14 bleiben erhalten.</p>
              <ul className="list small">{backups.items.slice(0, 6).map((b) => (
                <li key={b.name} style={{ display: "flex", justifyContent: "space-between", padding: "0.35rem 0" }}><code>{b.name}</code><span className="muted">{bytes(b.bytes)}</span></li>
              ))}</ul>
              <div className="actions"><button className="btn" onClick={backup}>Jetzt sichern</button></div>
            </>
          ) : <p className="muted small">Sicherungen gehen über den Update-Dienst. Im Container: <code>bodybase backup</code>.</p>}
        </section>
      </div>
      <p className="muted small">Adresse: <code>{st.public_url}</code> · Zeitzone {st.timezone} · läuft seit {fmtAgo(new Date(Date.now() - st.uptime_s * 1000).toISOString()).replace("vor ", "")}</p>
    </>
  );
}

function ProviderApp({ p, onSaved, open, onToggle }) {
  const [values, setValues] = useState(p.values);
  const [busy, setBusy] = useState(false);
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.put(`/admin/providers/${p.key}`, { values });
      setValues(r.values);
      toast(r.ready ? `${p.name} ist eingerichtet` : "Gespeichert, es fehlen noch Angaben");
      onSaved();
    } catch (err) { toast(err.message, "error"); } finally { setBusy(false); }
  }
  async function clear() {
    if (!(await confirmDialog(`Die App-Zugangsdaten für ${p.name} werden entfernt. Bestehende Verbindungen können dann keine Tokens mehr erneuern.`))) return;
    await api.del(`/admin/providers/${p.key}`);
    onSaved();
  }
  return (
    <section className="panel" id={`p-${p.key}`}>
      <button type="button" className="link" style={{ width: "100%", color: "inherit" }} onClick={onToggle} aria-expanded={open}>
        <div className="source-top">
          <ProviderLogo provider={p} />
          <div style={{ flex: 1 }}><div className="source-name">{p.name}</div>
            <div className="tiny muted">{p.connections ? `${p.connections} Verbindungen` : "noch nicht genutzt"}</div></div>
          <span className={`pill ${p.app_ready ? "ok" : ""}`}>{p.app_ready ? "eingerichtet" : "nicht eingerichtet"}</span>
        </div>
      </button>
      {open && (
        <form className="stack" onSubmit={save} style={{ marginTop: "1rem" }}>
          <ol className="steps">{p.app_setup.map((s) => <li key={s}>{s}</li>)}</ol>
          <label>Rücksprung-Adresse (Redirect URI)<CopyField value={p.redirect_uri} /></label>
          <div className="form-grid">
            {p.app_fields.map((f) => (
              <label key={f.key}>{f.label}
                {f.type === "select" ? (
                  <select value={values[f.key] || f.default || ""} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}>
                    {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                ) : (
                  <input type={f.secret ? "password" : "text"} value={values[f.key] || ""} autoComplete="off"
                    placeholder={f.secret && values[`${f.key}__set`] ? "gespeichert – leer lassen zum Behalten" : ""}
                    onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
                )}
              </label>
            ))}
          </div>
          {p.note && <p className="hint">{p.note}</p>}
          <div className="actions">
            <button className="btn primary" disabled={busy}>Speichern</button>
            {p.app_ready && <button type="button" className="link danger small" onClick={clear}>Entfernen</button>}
          </div>
        </form>
      )}
    </section>
  );
}

function Providers() {
  const [params] = useSearchParams();
  const [{ data }, setData] = useAsync(() => api.get("/admin/providers"), []);
  const [open, setOpen] = useState(params.get("p"));
  if (!data) return <Loading rows={2} />;
  const reload = async () => setData(await api.get("/admin/providers"));
  return (
    <>
      <p className="muted">Für Anbieter mit Anmeldung per Weiterleitung legst du einmal eine eigene Entwickler-App an. Danach kann sich jedes Konto auf diesem Server selbst verbinden.
        Die Rücksprung-Adressen hängen von <code>{data.public_url}</code> ab.</p>
      {!data.https && <div className="notice"><p className="small">Viele Anbieter (z. B. Withings, Oura, WHOOP) verlangen eine HTTPS-Adresse. Stelle BodyBase dafür über deinen Proxy (z. B. Nginx Proxy Manager) mit Zertifikat bereit und setze die Adresse im Container mit <code>bodybase url https://…</code>.</p></div>}
      {data.providers.map((p) => <ProviderApp key={p.key} p={p} onSaved={reload} open={open === p.key} onToggle={() => setOpen(open === p.key ? null : p.key)} />)}
    </>
  );
}

function Users({ user }) {
  const [{ data: users }, setUsers] = useAsync(() => api.get("/admin/users"), []);
  const [{ data: invites }, setInvites] = useAsync(() => api.get("/admin/invites"), []);
  const [note, setNote] = useState("");
  async function invite(e) {
    e.preventDefault();
    await api.post("/admin/invites", { note });
    setNote("");
    setInvites(await api.get("/admin/invites"));
  }
  async function upd(u, body) {
    try { await api.put(`/admin/users/${u.id}`, body); setUsers(await api.get("/admin/users")); toast("Gespeichert"); } catch (e) { toast(e.message, "error"); }
  }
  async function remove(u) {
    if (!(await confirmDialog(`${u.email} und alle zugehörigen Daten werden gelöscht.`))) return;
    try { await api.del(`/admin/users/${u.id}`); setUsers(await api.get("/admin/users")); } catch (e) { toast(e.message, "error"); }
  }
  if (!users) return <Loading rows={1} />;
  return (
    <>
      <section className="panel">
        <div className="panel-head"><h2>Konten</h2></div>
        <div className="table-wrap"><table className="table">
          <thead><tr><th>E-Mail</th><th>Rolle</th><th className="num">Quellen</th><th className="num">Messwerte</th><th className="num">Aktivitäten</th><th /></tr></thead>
          <tbody>{users.map((u) => (
            <tr key={u.id}>
              <td>{u.email}{u.name ? <div className="tiny muted">{u.name}</div> : null}{!u.active && <span className="pill bad">gesperrt</span>}</td>
              <td><select value={u.role} onChange={(e) => upd(u, { role: e.target.value })} style={{ width: "auto" }}>
                <option value="user">Nutzer</option><option value="admin">Administrator</option></select></td>
              <td className="num">{u.connections}</td><td className="num">{fmtNum(u.samples)}</td><td className="num">{fmtNum(u.activities)}</td>
              <td className="nowrap">{u.email !== user.email && <>
                <button className="link small" onClick={() => upd(u, { active: !u.active })}>{u.active ? "Sperren" : "Entsperren"}</button>{" · "}
                <button className="link danger small" onClick={() => remove(u)}>Löschen</button></>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      </section>
      <section className="panel">
        <div className="panel-head"><h2>Einladungen</h2></div>
        <form className="copy-row" onSubmit={invite}>
          <input placeholder="Notiz, z. B. für wen" value={note} onChange={(e) => setNote(e.target.value)} maxLength={120} />
          <button className="btn primary">Einladung erstellen</button>
        </form>
        <ul className="list" style={{ marginTop: "0.8rem" }}>
          {(invites || []).map((i) => (
            <li key={i.id} style={{ padding: "0.6rem 0" }}>
              {i.used_by ? <span className="muted small"><code>{i.code}</code> eingelöst von {i.used_by}</span> : (
                <div className="stack" style={{ gap: "0.4rem" }}>
                  <span className="small">{i.note || "Einladung"} · {fmtAgo(i.created_at)}</span>
                  <CopyField value={i.link} />
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function Server() {
  const [{ data }, setData] = useAsync(() => api.get("/admin/settings"), []);
  const [v, setV] = useState(null);
  useEffect(() => { if (data) setV(data.values); }, [data]);
  if (!v) return <Loading rows={1} />;
  async function save(e) {
    e.preventDefault();
    try { setData(await api.put("/admin/settings", { values: v })); toast("Gespeichert"); } catch (err) { toast(err.message, "error"); }
  }
  return (
    <form className="panel" onSubmit={save}>
      <h2>Server</h2>
      <div className="stack">
        <Switch checked={v.allow_registration} onChange={(x) => setV({ ...v, allow_registration: x })}>Jeder darf ein Konto anlegen (sonst nur mit Einladung)</Switch>
        <label>Öffentliche Adresse<input type="url" value={v.public_url} onChange={(e) => setV({ ...v, public_url: e.target.value })} placeholder="https://body.deine-domain.de" />
          <span className="hint">Unter dieser Adresse ist BodyBase von außen erreichbar. Daraus entstehen die Rücksprung-Adressen für Strava, Withings &amp; Co.
            ({(v.public_url || "https://…").replace(/\/+$/, "")}/api/oauth/&lt;anbieter&gt;/callback). Die meisten Anbieter verlangen HTTPS.
            Nach einer Änderung die Callback-URLs bei den Anbietern anpassen.</span>
          {v.public_url && !v.public_url.startsWith("https://") && <span className="hint warn">Ohne HTTPS lehnen Withings, Strava, Fitbit und andere die Anmeldung ab.</span>}
        </label>
        <div className="form-grid">
          <label>Abgleich alle … Minuten<input inputMode="numeric" value={v.sync_interval_minutes} onChange={(e) => setV({ ...v, sync_interval_minutes: e.target.value })} />
            <span className="hint">15 bis 1440. Fitbit erlaubt nur 150 Anfragen pro Stunde, 60 ist ein guter Wert.</span></label>
          <label>Erster Abgleich holt … Tage<input inputMode="numeric" value={v.backfill_days} onChange={(e) => setV({ ...v, backfill_days: e.target.value })} />
            <span className="hint">Wie weit eine neue Verbindung zurückgeht. Später per „Alles neu holen“ änderbar.</span></label>
          <label>Zeitzone<input value={v.timezone} onChange={(e) => setV({ ...v, timezone: e.target.value })} placeholder="Europe/Berlin" /></label>
          <label>Karten: CARTO-Schlüssel (optional)<input value={v.carto_api_key || ""} onChange={(e) => setV({ ...v, carto_api_key: e.target.value })} placeholder="leer = OpenStreetMap" />
            <span className="hint">Für die dunkle CARTO-Karte, kostenlos unter carto.com/basemaps. Ohne Schlüssel kommt OpenStreetMap (im dunklen Design abgedunkelt).</span></label>
          <label>Karten: eigene Kachel-Adresse (optional)<input value={v.map_tile_url || ""} onChange={(e) => setV({ ...v, map_tile_url: e.target.value })} placeholder="https://…/{z}/{x}/{y}.png" />
            <span className="hint">Hat Vorrang vor CARTO und OpenStreetMap. Muss mit https:// beginnen und {"{z}"}, {"{x}"}, {"{y}"} enthalten.</span></label>
          <label>In andere Seiten einbetten<input value={v.frame_ancestors} onChange={(e) => setV({ ...v, frame_ancestors: e.target.value })} placeholder="https://ha.example.de" />
            <span className="hint">Adressen, die BodyBase einbetten dürfen (z. B. Home Assistant), mit Leerzeichen getrennt.</span></label>
        </div>
      </div>
      <div className="actions"><button className="btn primary">Speichern</button></div>
    </form>
  );
}

function Log() {
  const [{ data }] = useAsync(() => api.get("/admin/audit?limit=200"), []);
  if (!data) return <Loading rows={1} />;
  return (
    <section className="panel">
      <div className="table-wrap"><table className="table">
        <thead><tr><th>Wann</th><th>Wer</th><th>Was</th><th>Details</th></tr></thead>
        <tbody>{data.map((e) => (
          <tr key={e.id}><td className="nowrap small">{new Date(e.at).toLocaleString("de-DE")}</td><td className="small">{e.actor}</td>
            <td className="small"><code>{e.action}</code></td><td className="small muted">{e.text}</td></tr>
        ))}</tbody>
      </table></div>
    </section>
  );
}

export default function Admin({ user }) {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "overview";
  return (
    <>
      <div className="page-head"><div><h1>Administration</h1><p>Server, Anbieter-Apps und Konten.</p></div></div>
      <div className="tabs" role="tablist">
        {TABS.map((t) => <button key={t.value} role="tab" aria-selected={tab === t.value} className={`tab${tab === t.value ? " on" : ""}`}
          onClick={() => setParams({ tab: t.value })}>{t.label}</button>)}
      </div>
      {tab === "overview" && <Overview />}
      {tab === "providers" && <Providers />}
      {tab === "users" && <Users user={user} />}
      {tab === "server" && <Server />}
      {tab === "log" && <Log />}
    </>
  );
}
