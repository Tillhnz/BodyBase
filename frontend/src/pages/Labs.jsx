import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Loading, toast } from "../components/feedback.jsx";
import { EmptyState, useAsync } from "../components/ui.jsx";
import { fmtDay, fmtNum } from "../fmt.js";

/* Blutwerte: Befund hochladen (PDF), prüfen, speichern; Einordnung, Verlauf und Verknüpfung mit den Körperdaten. */

const ST = { low: "zu niedrig", high: "zu hoch", ok: "im Normbereich", optimal: "im Zielbereich" };
const dec = (v) => (Math.abs(v) < 10 ? (Math.abs(v) < 1 ? 2 : 1) : 0);

function RangeBar({ m }) {
  const [lo, hi] = m.ref;
  const vals = [m.value, lo, hi, ...(m.opt || [])].filter((x) => x != null);
  const min = Math.min(...vals, 0) , max = Math.max(...vals) * 1.15 || 1;
  const p = (v) => `${Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100))}%`;
  return (
    <div className="lab-range" aria-hidden="true">
      <i className="ref" style={{ left: p(lo ?? min), right: `calc(100% - ${p(hi ?? max)})` }} />
      {m.opt && <i className="opt" style={{ left: p(m.opt[0] ?? min), right: `calc(100% - ${p(m.opt[1] ?? max)})` }} />}
      <b className={`dot ${m.status}`} style={{ left: p(m.value) }} />
    </div>
  );
}

function Marker({ m }) {
  const [open, setOpen] = useState(false);
  const delta = m.prev ? m.value - m.prev.value : null;
  return (
    <li className={`lab-row ${m.status}`}>
      <button type="button" className="lab-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="lab-name">{m.label}</span>
        <span className="lab-val"><b>{fmtNum(m.value, dec(m.value))}</b> <small className="muted">{m.unit}</small></span>
        <span className={`lab-st ${m.status}`}>{ST[m.status]}</span>
      </button>
      <RangeBar m={m} />
      {open && (
        <div className="lab-more small">
          <p style={{ margin: 0 }}>{m.what}</p>
          {m.note && <p className="lab-note">{m.note}</p>}
          <p className="muted tiny" style={{ margin: 0 }}>
            Normbereich {m.ref[0] != null ? fmtNum(m.ref[0], dec(m.ref[0])) : "–"} bis {m.ref[1] != null ? fmtNum(m.ref[1], dec(m.ref[1])) : "–"}
            {m.opt ? ` · Ziel ${m.opt[0] != null ? fmtNum(m.opt[0], dec(m.opt[0])) : ""}–${m.opt[1] != null ? fmtNum(m.opt[1], dec(m.opt[1])) : ""}` : ""}
            {" · "}{fmtDay(m.day)}
            {delta != null ? ` · ${delta >= 0 ? "+" : "−"}${fmtNum(Math.abs(delta), dec(delta))} seit ${fmtDay(m.prev.day)}` : ""}
          </p>
          {m.history.length > 1 && <Link className="link small" to={`/metric/${m.metric}`}>Verlauf ansehen →</Link>}
        </div>
      )}
    </li>
  );
}

function Upload({ catalog, onSaved }) {
  const file = useRef(null);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [rows, setRows] = useState([]);
  const [day, setDay] = useState("");
  const [add, setAdd] = useState("");
  const [paste, setPaste] = useState("");
  const [showPaste, setShowPaste] = useState(false);
  function apply(r) {
    setRes(r);
    setDay(r.day);
    setRows(r.markers.map((m) => ({ ...m, on: true, input: String(m.value).replace(".", ",") })));
    if (r.hint) toast(r.hint, "info");
  }
  async function pick(f) {
    if (!f) return;
    setBusy(true);
    try {
      // Datei erst vollständig einlesen: Dateien aus Cloud-Ordnern (Drive, OneDrive) liefert Android sonst manchmal nicht aus
      let buf;
      try {
        buf = await f.arrayBuffer();
      } catch {
        throw new Error("Die Datei ließ sich auf dem Gerät nicht lesen. Liegt sie in Google Drive oder OneDrive? Dann bitte erst herunterladen und die heruntergeladene Datei wählen.");
      }
      const fd = new FormData();
      fd.append("file", new Blob([buf], { type: f.type || "application/pdf" }), (f.name || "befund.pdf").replace(/[^\w.-]+/g, "_"));
      let r;
      try {
        r = await api.upload("/labs/parse", fd);
      } catch (e) {
        if (e instanceof TypeError) throw new Error("Die Verbindung zum Server ist beim Hochladen abgebrochen. Ist BodyBase auf dem neuesten Stand (bodybase update)? Alternativ den Text des Befunds kopieren und unten einfügen.");
        throw e;
      }
      apply(r);
      if (r.ocr && r.markers.length) toast("Per Texterkennung gelesen – bitte die Werte besonders genau mit dem Befund vergleichen.", "info");
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); if (file.current) file.current.value = ""; }
  }
  async function parseText() {
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("text", paste);
      apply(await api.upload("/labs/parse", fd));
      setPaste("");
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  async function save() {
    const values = Object.fromEntries(rows.filter((r) => r.on && r.input !== "").map((r) => [r.key, Number(String(r.input).replace(",", "."))]).filter(([, v]) => !Number.isNaN(v)));
    if (!Object.keys(values).length) return toast("Keine Werte ausgewählt", "error");
    setBusy(true);
    try {
      const r = await api.post("/labs", { day, values });
      toast(`${r.saved} Blutwerte gespeichert`);
      setRes(null); setRows([]);
      onSaved();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  const startManual = () => { setRes({ markers: [], day_detected: false }); setDay(new Date().toISOString().slice(0, 10)); setRows([]); };
  return (
    <section className="panel lab-upload">
      <div className="panel-head"><h2>Befund hinzufügen</h2></div>
      {!res ? (
        <>
          <p className="small muted" style={{ marginTop: 0 }}>Lade den Laborbefund als PDF hoch – auch eingescannt – oder fotografiere ihn. Die Werte werden auf deinem Server ausgelesen, du prüfst sie und speicherst. Die Datei selbst wird nicht aufbewahrt.</p>
          <div className="actions">
            <input ref={file} type="file" accept="application/pdf,.pdf,image/*,.txt" hidden onChange={(e) => pick(e.target.files[0])} />
            <button className="btn primary" disabled={busy} onClick={() => file.current?.click()}>{busy ? "Lese … (Scans brauchen etwas länger)" : "PDF oder Foto hochladen"}</button>
            <button className="btn" onClick={() => setShowPaste(!showPaste)}>Text einfügen</button>
            <button className="btn" onClick={startManual}>Von Hand eintragen</button>
          </div>
          {showPaste && (
            <div className="lab-paste">
              <textarea rows={6} value={paste} placeholder="Befund in der PDF markieren, kopieren und hier einfügen …" onChange={(e) => setPaste(e.target.value)} />
              <button className="btn primary small" disabled={busy || paste.trim().length < 10} onClick={parseText}>Werte erkennen</button>
            </div>
          )}
        </>
      ) : (
        <>
          <label className="small">Datum der Blutabnahme {res.day_detected ? "(aus dem Befund)" : ""}
            <input type="date" value={day} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setDay(e.target.value)} /></label>
          {rows.length > 0 && <p className="tiny muted" style={{ margin: "0.6rem 0 0.3rem" }}>{rows.length} Werte erkannt – bitte kurz mit dem Befund vergleichen. Umgerechnet in die angezeigte Einheit.</p>}
          <ul className="lab-review">
            {rows.map((r, i) => (
              <li key={r.key}>
                <label className="check"><input type="checkbox" checked={r.on} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, on: e.target.checked } : x)))} />{r.label}</label>
                <input inputMode="decimal" value={r.input} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, input: e.target.value } : x)))} />
                <span className="tiny muted">{r.unit}{r.raw_unit && r.raw_unit.toLowerCase() !== r.unit.toLowerCase() ? ` (Befund: ${r.raw_value} ${r.raw_unit})` : ""}</span>
              </li>
            ))}
          </ul>
          <div className="actions" style={{ marginTop: "0.5rem" }}>
            <select value={add} onChange={(e) => setAdd(e.target.value)} aria-label="Wert hinzufügen">
              <option value="">Wert hinzufügen …</option>
              {catalog.filter((c) => !rows.some((r) => r.key === c.key)).map((c) => <option key={c.key} value={c.key}>{c.label} ({c.unit})</option>)}
            </select>
            <button type="button" className="btn small" disabled={!add} onClick={() => { const c = catalog.find((x) => x.key === add); setRows([...rows, { ...c, on: true, input: "" }]); setAdd(""); }}>Hinzufügen</button>
          </div>
          <div className="actions" style={{ marginTop: "0.8rem" }}>
            <button className="btn" onClick={() => { setRes(null); setRows([]); }}>Abbrechen</button>
            <button className="btn primary" disabled={busy || !day} onClick={save}>Speichern</button>
          </div>
        </>
      )}
    </section>
  );
}

export default function Labs() {
  const [reload, setReload] = useState(0);
  const [{ data, error }] = useAsync(() => api.get("/labs"), [reload]);
  if (error) return <EmptyState title="Blutwerte nicht verfügbar" text={error.message} />;
  if (!data) return <Loading rows={2} />;
  const groups = data.groups.filter((g) => data.markers.some((m) => m.group === g));
  const counts = { low: 0, high: 0 };
  data.markers.forEach((m) => { if (m.status in counts) counts[m.status] += 1; });
  async function del(d) {
    if (!window.confirm(`Befund vom ${fmtDay(d)} löschen?`)) return;
    try { await api.del(`/labs/${d}`); setReload(reload + 1); } catch (e) { toast(e.message, "error"); }
  }
  return (
    <div className="labs">
      {!data.markers.length && <EmptyState title="Noch keine Blutwerte" text="Lade deinen letzten Laborbefund hoch. BodyBase ordnet die Werte ein, verknüpft sie mit Training, Schlaf und Körperwerten und gibt Empfehlungen." />}
      {data.markers.length > 0 && (
        <div className="grid-2">
          <section className="panel lab-summary">
            <span className="rp-k">Letzter Befund {fmtDay(data.reports[0])}</span>
            <strong className="lab-big">{data.markers.length} Werte</strong>
            <span className="small">{counts.low + counts.high ? <><b className="bad-text">{counts.low + counts.high} außerhalb</b> des Normbereichs</> : "alle im Normbereich"}</span>
          </section>
          <section className="panel lab-summary">
            <span className="rp-k">Blut-Alter (PhenoAge)</span>
            {data.phenoage ? (
              <>
                <strong className="lab-big">{fmtNum(data.phenoage.value, 1)} <small className="muted">Jahre</small></strong>
                <span className="small">{data.phenoage.value < data.phenoage.age ? `${fmtNum(data.phenoage.age - data.phenoage.value, 1)} Jahre jünger` : `${fmtNum(data.phenoage.value - data.phenoage.age, 1)} Jahre älter`} als dein Alter · fließt ins <Link className="link" to="/analysis?ansicht=bioalter">Bio-Alter</Link> ein</span>
              </>
            ) : <span className="small muted">Braucht noch: {data.phenoage_missing.join(", ")}. Beim nächsten Blutbild danach fragen (übliche Routinewerte).</span>}
          </section>
        </div>
      )}
      {data.links.length > 0 && (
        <section className="panel">
          <div className="panel-head"><h2>Was das für dich bedeutet</h2><span className="tiny muted">verknüpft mit Training, Schlaf und Körperwerten</span></div>
          <ul className="coach-list">
            {data.links.map((x, i) => (
              <li key={i} className={`coach-item ${x.type}`}>
                <span className="coach-icon" aria-hidden="true">{{ warn: "!", tip: "→", good: "✓" }[x.type]}</span>
                <div><strong>{x.title}</strong><p>{x.text}</p>{x.advice && <p className="coach-advice"><b>Empfehlung:</b> {x.advice}</p>}</div>
              </li>
            ))}
          </ul>
          <p className="tiny muted" style={{ margin: "0.6rem 0 0" }}>Einordnung nach üblichen Laborbereichen und Studienlage – ersetzt keine ärztliche Beurteilung. Maßgeblich ist der Referenzbereich deines Labors.</p>
        </section>
      )}
      {groups.map((g) => (
        <section key={g} className="panel">
          <div className="panel-head"><h2>{g}</h2></div>
          <ul className="lab-list">{data.markers.filter((m) => m.group === g).map((m) => <Marker key={m.key} m={m} />)}</ul>
        </section>
      ))}
      <Upload catalog={data.catalog} onSaved={() => setReload(reload + 1)} />
      {data.reports.length > 0 && (
        <section className="panel">
          <div className="panel-head"><h2>Befunde</h2></div>
          <ul className="list">{data.reports.map((d) => <li key={d} className="row-between"><span>{fmtDay(d)}</span><button className="btn small" onClick={() => del(d)}>Löschen</button></li>)}</ul>
        </section>
      )}
    </div>
  );
}
