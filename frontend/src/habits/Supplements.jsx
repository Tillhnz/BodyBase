import { useEffect, useState } from "react";
import { api } from "../api.js";
import { confirmDialog, Loading, toast } from "../components/feedback.jsx";
import { EmptyState, Modal } from "../components/ui.jsx";
import { fmtDay, fmtNum, todayIso } from "../fmt.js";
import HabitYear from "./HabitYear.jsx";

/* Supplements: Tracker (als Gewohnheit), Empfehlung für heute (Vitamin D nach UV-Index am Ort) und Wirkung. */

const LEVEL = { take: ["nehmen", "good"], optional: ["optional", "warn"], pause: ["pausieren", "mute"] };
const TIMES = [["morning", "morgens"], ["noon", "mittags"], ["evening", "abends"], ["any", "jederzeit"]];

function Weather({ data, onLocate, onSave, onReset, busy, device }) {
  const loc = data.location;
  const w = data.weather;
  return (
    <section className="panel supp-weather">
      <div>
        <span className="rp-k">Ort für die Empfehlung</span>
        <strong>{loc ? loc.name : "unbekannt"}</strong>
        <span className="tiny muted">{loc ? `${loc.lat.toFixed(2)}, ${loc.lon.toFixed(2)}${loc.source === "activities" ? " · aus deinen Strecken" : loc.source === "device" ? " · Handy-Standort" : " · gespeichert"}` : "Bitte Standort verwenden"}</span>
      </div>
      {w ? (
        <div className="supp-wx">
          <span><b>{fmtNum(w.uv_max, 1)}</b><small>UV-Index max.</small></span>
          <span><b>{fmtNum(w.sun_h, 1)} h</b><small>Sonne</small></span>
          <span><b>{w.uv_window ? `${w.uv_window[0]}–${w.uv_window[1]}` : "–"}</b><small>UV ab 3</small></span>
          <span><b>{fmtNum(w.temp_max)} °C</b><small>max.</small></span>
        </div>
      ) : <span className="small muted">{loc ? "Wetter gerade nicht abrufbar." : ""}</span>}
      <div className="actions">
        <button className="btn small" disabled={busy} onClick={onLocate}>📍 Aktuellen Standort</button>
        {device && <button className="btn small" onClick={onSave}>Als festen Ort merken</button>}
        {loc?.source === "set" && <button className="btn small" onClick={onReset}>Ort zurücksetzen</button>}
      </div>
    </section>
  );
}

function SuppCard({ it, onToggle, onEdit, onReload }) {
  const [open, setOpen] = useState(false);
  const [year, setYear] = useState(false);
  const [lvl, cls] = LEVEL[it.advice.level] || LEVEL.take;
  return (
    <section className={`panel supp-card${it.taken ? " taken" : ""}`}>
      <div className="supp-head">
        <button type="button" className={`supp-check${it.taken ? " on" : ""}`} onClick={onToggle} aria-label={it.taken ? "Einnahme zurücknehmen" : "Als genommen abhaken"}>✓</button>
        <div className="supp-name">
          <strong>{it.label}</strong>
          <span className="small muted">{fmtNum(it.dose, it.dose % 1 ? 1 : 0)} {it.unit} · {TIMES.find((t) => t[0] === it.time)?.[1]}{it.streak ? ` · 🔥 ${it.streak}` : ""}</span>
        </div>
        <span className={`supp-level ${cls}`}>{it.taken ? "genommen" : lvl}</span>
      </div>
      <div className={`supp-advice ${cls}`}><b>{it.advice.title}.</b> {it.advice.text}</div>
      <div className="actions" style={{ marginTop: "0.5rem" }}>
        <button className="btn small" onClick={() => setOpen(!open)}>{open ? "Weniger" : "Einnahme & Hinweise"}</button>
        <button className="btn small" onClick={() => setYear(!year)}>{year ? "Verlauf schließen" : "Verlauf & nachtragen"}</button>
        <button className="btn small" onClick={onEdit}>Bearbeiten</button>
      </div>
      {open && (
        <div className="supp-more small">
          <p><b>Wofür:</b> {it.why}</p>
          <p><b>Wie und wann:</b> {it.how}</p>
          <p><b>Besser nicht:</b> {it.avoid}</p>
        </div>
      )}
      {year && <HabitYear habitId={it.habit_id} onChanged={onReload} />}
    </section>
  );
}

function SuppForm({ catalog, initial, onClose, onSaved }) {
  const [key, setKey] = useState(initial?.key || "");
  const c = catalog.find((x) => x.key === key);
  const [dose, setDose] = useState(initial?.dose ?? "");
  const [unit, setUnit] = useState(initial?.unit || "");
  const [time, setTime] = useState(initial?.time || "");
  const [busy, setBusy] = useState(false);
  function pick(k) {
    setKey(k);
    const x = catalog.find((y) => y.key === k);
    if (x) { setDose(x.dose); setUnit(x.unit); setTime(x.time); }
  }
  async function save() {
    if (!c) return;
    setBusy(true);
    const body = { name: c.label, kind: "check", supplement: { key, dose: String(dose).replace(",", "."), unit, time } };
    try {
      if (initial?.habit_id) await api.put(`/habits/${initial.habit_id}`, body);
      else await api.post("/habits", body);
      onSaved();
    } catch (e) { toast(e.message, "error"); setBusy(false); }
  }
  async function archive() {
    if (!(await confirmDialog(`${c.label} nicht mehr tracken? (Der Verlauf bleibt erhalten.)`))) return;
    await api.put(`/habits/${initial.habit_id}`, { name: c.label, kind: "check", supplement: { key, dose, unit, time }, archived: true });
    onSaved();
  }
  return (
    <Modal title={initial?.habit_id ? "Supplement bearbeiten" : "Supplement hinzufügen"} onClose={onClose}>
      <div className="stack">
        <label>Supplement
          <select value={key} onChange={(e) => pick(e.target.value)} disabled={!!initial?.habit_id}>
            <option value="">Bitte wählen …</option>
            {catalog.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
          </select>
        </label>
        {c && (
          <>
            <p className="small muted" style={{ margin: 0 }}>{c.why}</p>
            <div className="grid-2" style={{ margin: 0 }}>
              <label>Dosis<input inputMode="decimal" value={dose} onChange={(e) => setDose(e.target.value)} /></label>
              <label>Einheit<input value={unit} onChange={(e) => setUnit(e.target.value)} maxLength={12} /></label>
            </div>
            <label>Zeitpunkt
              <select value={time} onChange={(e) => setTime(e.target.value)}>{TIMES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
            </label>
            <p className="tiny muted" style={{ margin: 0 }}>{c.how}</p>
          </>
        )}
        <div className="actions">
          <button className="btn primary" disabled={!c || busy} onClick={save}>Speichern</button>
          {initial?.habit_id && <button className="btn" onClick={archive}>Nicht mehr tracken</button>}
          <button className="btn" onClick={onClose}>Abbrechen</button>
        </div>
      </div>
    </Modal>
  );
}

function Effects() {
  const [eff, setEff] = useState(null);
  useEffect(() => { api.get("/supplements/effects").then(setEff).catch(() => setEff([])); }, []);
  if (!eff?.length) return null;
  return (
    <section className="panel">
      <div className="panel-head"><h2>Wirkt es?</h2><span className="tiny muted">vor dem Start gegenüber danach, und Tage mit gegenüber ohne Einnahme</span></div>
      {eff.map((e) => (
        <div key={e.habit_id} className="supp-eff">
          <h3 className="sub-h">{e.label} <small className="muted">seit {fmtDay(e.since)} · an {e.days_taken} von {e.days_since} Tagen</small></h3>
          {e.lab && (e.lab.before || e.lab.after) && (
            <p className="small" style={{ margin: "0 0 0.4rem" }}>Blutwert: {e.lab.before ? `${fmtNum(e.lab.before.value, 1)} (${fmtDay(e.lab.before.day)})` : "–"} → {e.lab.after ? `${fmtNum(e.lab.after.value, 1)} (${fmtDay(e.lab.after.day)})` : "noch keine Messung danach"}</p>
          )}
          {e.rows.length ? (
            <div className="table-wrap"><table className="table compact">
              <thead><tr><th>Messwert</th><th className="num">4 Wo. vorher</th><th className="num">seitdem</th><th className="num">mit / ohne Einnahme</th></tr></thead>
              <tbody>{e.rows.map((r) => (
                <tr key={r.key}>
                  <td>{r.label}</td>
                  <td className="num">{r.before_after?.before ?? "–"}</td>
                  <td className="num">{r.before_after ? <span className={r.before_after.clear ? (r.before_after.good ? "good-text" : r.before_after.good === false ? "bad-text" : "") : ""}>{r.before_after.after} ({r.before_after.diff})</span> : "–"}</td>
                  <td className="num">{r.on_off ? <span className={r.on_off.clear ? "strong" : ""}>{r.on_off.on} / {r.on_off.off}</span> : "–"}</td>
                </tr>
              ))}</tbody>
            </table></div>
          ) : <p className="small muted">Noch zu wenig Daten – nach zwei, drei Wochen mit Einnahme wird es aussagekräftig.</p>}
        </div>
      ))}
      <p className="tiny muted" style={{ margin: "0.5rem 0 0" }}>Farbig = deutlicher Unterschied. Andere Einflüsse (Jahreszeit, Training, Schlaf) wirken mit – eine Tendenz, kein Beweis. Unter Gesundheitsbild → Statistik tauchen Supplements außerdem als Einflussfaktor auf.</p>
    </section>
  );
}

export default function Supplements() {
  const [data, setData] = useState(null);
  const [coords, setCoords] = useState(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState(null);
  async function load(c = coords) {
    const q = c ? `?lat=${c.lat}&lon=${c.lon}` : "";
    setData(await api.get(`/supplements/today${q}`));
  }
  useEffect(() => { load().catch((e) => toast(e.message, "error")); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  function locate() {
    if (!navigator.geolocation) return toast("Standort wird von diesem Browser nicht unterstützt.", "error");
    setBusy(true);
    navigator.geolocation.getCurrentPosition((p) => {
      const c = { lat: Math.round(p.coords.latitude * 1000) / 1000, lon: Math.round(p.coords.longitude * 1000) / 1000 };
      setCoords(c);
      load(c).finally(() => setBusy(false));
    }, (e) => { setBusy(false); toast(`Standort nicht verfügbar (${e.message})`, "error"); }, { timeout: 15000, maximumAge: 600000 });
  }
  async function saveLoc() {
    const name = window.prompt("Name für diesen Ort", "Zuhause") || "eigener Ort";
    await api.put("/supplements/location", { ...coords, name });
    setCoords(null);
    load(null);
  }
  async function resetLoc() { await api.del("/supplements/location"); load(null); }
  async function toggle(it) {
    try {
      await api.post(`/habits/${it.habit_id}/log`, { day: todayIso(), value: it.taken ? 0 : 1 });
      load();
    } catch (e) { toast(e.message, "error"); }
  }
  if (!data) return <Loading rows={2} />;
  return (
    <div className="supps">
      <Weather data={data} onLocate={locate} onSave={saveLoc} onReset={resetLoc} busy={busy} device={!!coords} />
      {!data.items.length ? (
        <EmptyState title="Noch keine Supplements" text="Lege an, was du nimmst – z. B. Vitamin D. BodyBase sagt dir jeden Tag, ob und wann du es nehmen solltest, und wertet die Wirkung aus.">
          <button className="btn primary" onClick={() => setForm({ key: "vitd", dose: 1000, unit: "IE", time: "noon" })}>Vitamin D anlegen</button>
        </EmptyState>
      ) : data.items.map((it) => <SuppCard key={it.habit_id} it={it} onToggle={() => toggle(it)} onEdit={() => setForm(it)} onReload={() => load()} />)}
      <button className="btn primary" style={{ alignSelf: "flex-start" }} onClick={() => setForm({})}>+ Supplement hinzufügen</button>
      <Effects />
      {form && <SuppForm catalog={data.catalog} initial={form} onClose={() => setForm(null)} onSaved={() => { setForm(null); load(); }} />}
    </div>
  );
}
