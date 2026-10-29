import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, uploadRaw } from "../api.js";
import { Loading, confirmDialog, toast } from "../components/feedback.jsx";
import { CopyField, Modal, ProviderLogo, Switch, useAsync } from "../components/ui.jsx";
import { fmtAgo, fmtNum } from "../fmt.js";

const CAT_LABEL = { activity: "Bewegung", sleep: "Schlaf", body: "Körper", heart: "Herz", recovery: "Erholung", nutrition: "Ernährung",
  metabolic: "Blutzucker", workouts: "Training" };
const CAT_CLASS = { workouts: "activity" };
const FILTERS = [
  { value: "all", label: "Alle" }, { value: "workouts", label: "Training" }, { value: "sleep", label: "Schlaf" },
  { value: "body", label: "Körper" }, { value: "recovery", label: "Erholung" }, { value: "metabolic", label: "Blutzucker" },
];

let providerCache = null;
export function useProviders() {
  const [list, setList] = useState(providerCache);
  useEffect(() => {
    if (!providerCache) api.get("/providers").then((l) => { providerCache = l; setList(l); }).catch(() => {});
  }, []);
  return list;
}

function statusOf(p) {
  const c = p.connection;
  if (!c) return p.has_data ? { cls: "ok", text: "Daten vorhanden" } : null;
  if (c.syncing) return { cls: "iris", text: "gleicht ab", live: true };
  if (!c.enabled) return { cls: "", text: "pausiert" };
  if (c.status === "auth") return { cls: "bad", text: "Zugang abgelaufen" };
  if (c.status === "error") return { cls: "bad", text: "Fehler" };
  if (c.status === "pending") return { cls: "warn", text: "wartet" };
  return { cls: "ok", text: "verbunden" };
}

function isConnected(p) {
  return !!p.connection || p.has_data;
}

function CatDots({ delivers }) {
  return (
    <span className="cat-dots" title={delivers.map((d) => CAT_LABEL[d]).join(", ")}>
      {delivers.map((d) => <i key={d} className={`cat-${CAT_CLASS[d] || d}`} />)}
    </span>
  );
}

function SourceCard({ p, onOpen }) {
  const st = statusOf(p);
  const c = p.connection;
  return (
    <button type="button" className={`source-card${isConnected(p) ? " connected" : ""}${st?.cls === "bad" ? " problem" : ""}`} onClick={() => onOpen(p.key)}>
      <div className="source-top">
        <ProviderLogo provider={p} />
        <div style={{ minWidth: 0 }}>
          <div className="source-name">{p.name}</div>
          {c?.account ? <div className="tiny muted">{c.account}</div> : !p.official && <div className="tiny muted">inoffiziell</div>}
        </div>
      </div>
      <p className="source-sum">{p.summary}</p>
      <div className="source-foot">
        <CatDots delivers={p.delivers} />
        {st ? <span className={`pill ${st.cls}`}>{st.live && <span className="live" />}{st.text}{c?.last_success_at && st.cls === "ok" ? ` · ${fmtAgo(c.last_success_at)}` : ""}</span>
          : <span className="pill">{p.kind === "file" ? "Import" : p.kind === "push" ? "Weiterleitung" : "verbinden"}</span>}
      </div>
    </button>
  );
}

export default function Sources({ user }) {
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState("all");
  const [{ data: list, loading }, setList] = useAsync(() => api.get("/providers"), []);
  const [{ data: jobs }, setJobs] = useAsync(() => api.get("/imports/jobs"), []);
  const open = params.get("provider");

  useEffect(() => {
    if (params.get("connected")) toast("Verbunden. Der erste Abgleich läuft.");
    if (params.get("error")) toast(params.get("error"), "error");
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Solange etwas abgleicht oder importiert, regelmäßig nachladen
  const busy = list?.some((p) => p.connection?.syncing) || jobs?.some((j) => j.status === "running" || j.status === "queued");
  useEffect(() => {
    if (!busy) return undefined;
    const id = setInterval(async () => {
      try {
        const [l, j] = await Promise.all([api.get("/providers"), api.get("/imports/jobs")]);
        providerCache = l;
        setList(l);
        setJobs(j);
      } catch { /* nächster Versuch */ }
    }, 3000);
    return () => clearInterval(id);
  }, [busy, setList, setJobs]);

  async function refresh() {
    const l = await api.get("/providers");
    providerCache = l;
    setList(l);
    setJobs(await api.get("/imports/jobs"));
  }

  if (loading && !list) return <Loading rows={3} />;
  const connected = list.filter(isConnected);
  const rest = list.filter((p) => !isConnected(p) && (filter === "all" || p.delivers.includes(filter)));
  const current = list.find((p) => p.key === open);
  const activeJob = jobs?.find((j) => j.status === "running" || j.status === "queued");
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Quellen</h1>
          <p>Jede Quelle liefert, was sie am besten kann. Doppelte Werte (etwa dieselbe Laufeinheit von Garmin und Strava) erkennt BodyBase und zählt sie nur einmal.</p>
        </div>
        <div className="actions"><button className="btn primary" onClick={() => setParams({ provider: "file" })}>Datei importieren</button></div>
      </div>
      {activeJob && (
        <div className="notice info">
          <div style={{ flex: 1 }}>
            <p><strong>Apple-Health-Export wird eingelesen</strong> ({activeJob.filename})</p>
            <div className="progress" aria-label="Fortschritt"><span style={{ width: `${Math.round((activeJob.progress || 0) * 100)}%` }} /></div>
          </div>
        </div>
      )}
      {connected.length > 0 && (
        <>
          <div className="section-title" style={{ marginTop: 0 }}><h2>Verbunden</h2></div>
          <div className="source-grid">{connected.map((p) => <SourceCard key={p.key} p={p} onOpen={(k) => setParams({ provider: k })} />)}</div>
        </>
      )}
      <div className="section-title">
        <h2>{connected.length ? "Weitere Quellen" : "Quelle verbinden"}</h2>
        <div className="chips">
          {FILTERS.map((f) => <button key={f.value} className={`chip${filter === f.value ? " on" : ""}`} onClick={() => setFilter(f.value)}>{f.label}</button>)}
        </div>
      </div>
      <div className="source-grid">{rest.map((p) => <SourceCard key={p.key} p={p} onOpen={(k) => setParams({ provider: k })} />)}</div>
      {current && <SourceDialog p={current} user={user} onClose={() => setParams({})} onChange={refresh} jobs={jobs} />}
    </>
  );
}

// ---------- Dialog je Quelle ----------

function SourceDialog({ p, user, onClose, onChange, jobs }) {
  const c = p.connection;
  const head = (
    <div className="modal-head">
      <ProviderLogo provider={p} size="lg" />
      <div>
        <h3>{p.name}</h3>
        <div className="small muted">{p.delivers.map((d) => CAT_LABEL[d]).join(" · ")}{!p.official && " · inoffizielle Schnittstelle"}</div>
      </div>
    </div>
  );
  return (
    <Modal title={p.name} onClose={onClose} wide head={head}>
      <div className="source-detail">
        <p className="muted" style={{ margin: 0 }}>{p.summary}</p>
        {c && <ConnectionStatus p={p} c={c} onChange={onChange} onClose={onClose} />}
        {p.kind === "oauth" && <OAuthConnect p={p} user={user} connected={!!c} />}
        {(p.kind === "apikey" || p.kind === "login") && <KeyConnect p={p} c={c} onChange={onChange} />}
        {p.kind === "push" && <PushSetup p={p} />}
        {(p.kind === "file" || p.key === "apple_health") && <FileImport p={p} onChange={onChange} jobs={jobs} />}
        {p.note && <div className="notice" style={{ margin: 0 }}><p className="small">{p.note}</p></div>}
        {p.website && <p className="small" style={{ margin: 0 }}><a href={p.website} target="_blank" rel="noreferrer noopener">{p.website.replace(/^https?:\/\//, "")}</a></p>}
      </div>
    </Modal>
  );
}

function Steps({ items }) {
  return <ol className="steps">{items.map((s) => <li key={s}>{s}</li>)}</ol>;
}

function OAuthConnect({ p, user, connected }) {
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    try {
      const { url } = await api.post(`/connections/${p.key}/authorize`);
      window.location.href = url;
    } catch (e) {
      toast(e.message, "error");
      setBusy(false);
    }
  }
  if (!p.app_ready) {
    return (
      <div className="notice">
        <div>
          <p><strong>{p.name} ist auf diesem Server noch nicht eingerichtet.</strong></p>
          <p className="small">Für die Anmeldung braucht BodyBase eine eigene Entwickler-App bei {p.name}. Das macht der Administrator einmalig.</p>
          {user.is_admin && <p className="small"><Link className="link" to={`/admin?tab=providers&p=${p.key}`}>Jetzt in der Administration einrichten</Link></p>}
        </div>
      </div>
    );
  }
  return (
    <div>
      <Steps items={p.setup} />
      <div className="actions">
        <button className="btn primary" onClick={go} disabled={busy}>{connected ? "Neu verbinden" : `Mit ${p.name} verbinden`}</button>
      </div>
    </div>
  );
}

function KeyConnect({ p, c, onChange }) {
  const [values, setValues] = useState(() => {
    const v = {};
    p.fields.forEach((f) => { v[f.key] = f.secret ? "" : (c?.config?.[f.key === "mapping" ? "mapping_text" : f.key] ?? f.default ?? ""); });
    return v;
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.post(`/connections/${p.key}/connect`, { values });
      toast(`${p.name} verbunden. Der erste Abgleich läuft.`);
      onChange();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  const mfa = p.key === "garmin";
  return (
    <form className="stack" onSubmit={submit}>
      <Steps items={p.setup} />
      <div className="form-grid">
        {p.fields.map((f) => {
          if (mfa && f.key === "mfa_code" && !/Code/.test(error)) return null;
          const common = { value: values[f.key] ?? "", onChange: (e) => setValues({ ...values, [f.key]: e.target.value }),
            required: f.required && !(f.secret && c), placeholder: f.secret && c ? "unverändert" : f.placeholder || "" };
          return (
            <label key={f.key} className={f.type === "textarea" || f.type === "url" ? "span-all" : ""}>{f.label}
              {f.type === "textarea" ? <textarea {...common} rows={4} /> :
                <input {...common} type={f.type === "password" ? "password" : f.type === "url" ? "url" : "text"} autoComplete="off" />}
              {f.help && <span className="hint">{f.help}</span>}
            </label>
          );
        })}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="actions"><button className="btn primary" disabled={busy}>{busy ? "Prüfe …" : c ? "Speichern und prüfen" : "Verbinden"}</button></div>
    </form>
  );
}

function PushSetup({ p }) {
  const [{ data }, setData] = useAsync(() => api.get("/me/ingest"), []);
  if (!data) return null;
  async function rotate() {
    if (!(await confirmDialog("Der alte Schlüssel funktioniert danach nicht mehr. Du musst ihn in Apps und Skripten ersetzen.", { title: "Neuen Schlüssel erzeugen?", confirmLabel: "Neu erzeugen" }))) return;
    setData(await api.post("/me/ingest/rotate"));
    toast("Neuer Schlüssel erzeugt");
  }
  const hae = p.key === "apple_health";
  const url = hae ? data.urls.health_auto_export : data.urls.json;
  const example = `curl -X POST ${data.urls.json} \\
  -H "Authorization: Bearer ${data.token}" \\
  -H "Content-Type: application/json" \\
  -d '{"source": "${p.key === "health_connect" ? "health_connect" : "api"}", "samples": [
        {"metric": "weight", "value": 79.4, "time": "2026-10-29T07:30:00+01:00"},
        {"metric": "steps", "value": 9120, "date": "2026-10-29"}]}'`;
  return (
    <div className="stack">
      <Steps items={p.setup} />
      <label>Adresse<CopyField value={url} /></label>
      <label>Schlüssel {hae && <span className="hint">(in Health Auto Export als Header „Authorization“ mit „Bearer “ davor)</span>}
        <CopyField value={data.token} />
      </label>
      {!hae && <div><div className="field-label small muted">Beispiel</div><pre className="code">{example}</pre>
        <p className="hint">Messgrößen: weight, body_fat, resting_hr, hrv, steps, sleep_duration, glucose … (Liste unter Trends). Außerdem „activities“ und „sleep“.</p></div>}
      <div><button className="link small" onClick={rotate}>Neuen Schlüssel erzeugen</button></div>
    </div>
  );
}

function FileImport({ p, onChange, jobs }) {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(null);
  const [result, setResult] = useState(null);
  const input = useRef(null);
  const apple = p.key === "apple_health";
  const accept = apple ? ".zip,.xml" : p.key === "csv" ? ".csv,.txt" : ".fit,.gpx,.tcx,.gz,.csv";

  async function handle(files) {
    if (!files?.length) return;
    setBusy(true);
    setResult(null);
    try {
      const list = [...files];
      if (apple || list[0].name.toLowerCase().endsWith(".zip")) {
        setProgress(0);
        await uploadRaw("/imports/apple-health", list[0], setProgress);
        toast("Hochgeladen. Der Import läuft im Hintergrund.");
        onChange();
      } else if (list.every((f) => /\.(csv|txt)$/i.test(f.name))) {
        const form = new FormData();
        form.append("file", list[0]);
        const r = await api.upload("/imports/csv", form);
        setResult(`${fmtNum(r.counts.samples)} Werte aus den Spalten ${Object.values(r.columns).join(", ")} übernommen.`);
        onChange();
      } else {
        const form = new FormData();
        list.forEach((f) => form.append("files", f));
        const r = await api.upload("/imports/files", form);
        const ok = r.results.filter((x) => x.ok).length;
        const bad = r.results.filter((x) => !x.ok);
        setResult(`${ok} von ${r.results.length} Dateien übernommen.${bad.length ? ` Nicht lesbar: ${bad.map((b) => `${b.file} (${b.error})`).join("; ")}` : ""}`);
        onChange();
      }
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }
  const last = apple ? jobs?.find((j) => j.kind === "apple_health") : null;
  return (
    <div className="stack">
      {!apple && <Steps items={p.setup} />}
      {apple && <div className="field-label"><strong>Einmaliger Import</strong> <span className="muted small">export.zip aus der Health-App</span></div>}
      <label className={`dropzone${over ? " over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); handle(e.dataTransfer.files); }}>
        <input ref={input} type="file" multiple={!apple} accept={accept} onChange={(e) => handle(e.target.files)} disabled={busy} />
        <span>{busy ? "Lade hoch …" : apple ? "export.zip hierher ziehen oder klicken" : "Dateien hierher ziehen oder klicken"}</span>
      </label>
      {progress != null && <div className="progress"><span style={{ width: `${Math.round(progress * 100)}%` }} /></div>}
      {result && <p className="ok small" role="status">{result}</p>}
      {last && (
        <p className="small muted">Letzter Import: {last.filename} · {last.status === "done" ? `fertig, ${fmtNum(last.counts?.records)} Einträge gelesen`
          : last.status === "failed" ? `fehlgeschlagen: ${last.message}` : `läuft (${Math.round((last.progress || 0) * 100)} %)`}</p>
      )}
    </div>
  );
}

function ConnectionStatus({ p, c, onChange, onClose }) {
  const [{ data: runs }] = useAsync(() => (p.kind === "oauth" || p.kind === "apikey" || p.kind === "login" ? api.get(`/connections/${c.id}/runs`) : Promise.resolve([])), [c.id, c.last_sync_at]);
  const pollable = p.kind !== "push" && p.kind !== "file";
  async function syncNow(full) {
    try {
      await api.post(`/connections/${c.id}/sync${full ? "?full=true" : ""}`);
      toast(full ? "Alle Daten werden neu geholt." : "Abgleich gestartet.");
      onChange();
    } catch (e) { toast(e.message, "error"); }
  }
  async function toggle(enabled) {
    await api.put(`/connections/${c.id}`, { enabled });
    onChange();
  }
  const [asking, setAsking] = useState(false);
  async function disconnect(withData) {
    await api.del(`/connections/${c.id}?delete_data=${withData}`);
    toast(withData ? `${p.name} getrennt, Daten gelöscht` : `${p.name} getrennt`);
    onChange();
    onClose();
  }
  return (
    <div className="panel" style={{ marginBottom: 0, background: "var(--ink-2)" }}>
      <dl className="kv">
        {c.account && <><dt>Konto</dt><dd>{c.account}</dd></>}
        <dt>Status</dt><dd>{statusOf(p)?.text}</dd>
        {pollable && <><dt>Letzter Abgleich</dt><dd>{fmtAgo(c.last_sync_at)}{c.next_sync_at && c.enabled ? ` · nächster ${fmtAgo(c.next_sync_at).replace("vor", "in")}` : ""}</dd></>}
        {!pollable && c.last_sync_at && <><dt>Letzte Daten</dt><dd>{fmtAgo(c.last_sync_at)}</dd></>}
        <dt>Gespeichert</dt><dd>{fmtNum(c.data.samples)} Werte · {fmtNum(c.data.activities)} Aktivitäten · {fmtNum(c.data.sleep)} Nächte</dd>
      </dl>
      {c.last_error && <p className="error small" style={{ marginTop: "0.6rem" }}>{c.last_error}</p>}
      <div className="actions">
        {pollable && <button className="btn small" onClick={() => syncNow(false)} disabled={c.syncing || c.status === "auth"}>Jetzt abgleichen</button>}
        {pollable && <button className="btn small" onClick={() => syncNow(true)} disabled={c.syncing || c.status === "auth"}>Alles neu holen</button>}
        {pollable && <Switch checked={c.enabled} onChange={toggle}>Automatisch</Switch>}
        <button className="link danger small" style={{ marginLeft: "auto" }} onClick={() => setAsking(true)}>Trennen</button>
      </div>
      {asking && (
        <div className="notice bad" style={{ marginTop: "0.8rem", marginBottom: 0 }}>
          <div style={{ flex: 1 }}>
            <p><strong>{p.name} trennen?</strong> Die bisherigen Daten kannst du behalten oder mitlöschen.</p>
            <div className="actions" style={{ marginTop: "0.5rem" }}>
              <button className="btn small" onClick={() => setAsking(false)}>Abbrechen</button>
              <button className="btn small" onClick={() => disconnect(false)}>Trennen, Daten behalten</button>
              <button className="btn small danger" onClick={() => disconnect(true)}>Trennen und Daten löschen</button>
            </div>
          </div>
        </div>
      )}
      {runs?.length > 0 && (
        <details style={{ marginTop: "0.8rem" }}>
          <summary className="small muted" style={{ cursor: "pointer" }}>Protokoll</summary>
          <ul className="list small" style={{ marginTop: "0.4rem" }}>
            {runs.map((r) => (
              <li key={r.started_at} style={{ padding: "0.35rem 0", display: "flex", gap: "0.8rem", flexWrap: "wrap" }}>
                <span className={r.ok ? "ok" : r.ok === false ? "error" : "muted"}>{r.ok ? "✓" : r.ok === false ? "✗" : "…"}</span>
                <span className="muted">{fmtAgo(r.started_at)}</span>
                {r.counts && <span>{fmtNum(r.counts.samples)} Werte, {fmtNum(r.counts.activities)} Aktivitäten, {fmtNum(r.counts.sleep)} Nächte</span>}
                {r.message && <span className="muted">{r.message}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
