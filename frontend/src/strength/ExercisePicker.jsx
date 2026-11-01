import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { toast } from "../components/feedback.jsx";
import { Modal } from "../components/ui.jsx";
import ExerciseThumb from "./ExerciseThumb.jsx";
import { GROUP_COLORS, loadExercises, useExercises } from "./shared.js";

const GROUPS = ["Brust", "Rücken", "Schultern", "Arme", "Beine", "Rumpf", "Ganzkörper", "Ausdauer"];

/** Auswahl einer oder mehrerer Übungen. onPick(ids) */
export default function ExercisePicker({ onClose, onPick, multi = true, title = "Übungen hinzufügen" }) {
  const ex = useExercises();
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("");
  const [equip, setEquip] = useState("");
  const [picked, setPicked] = useState([]);
  const [creating, setCreating] = useState(false);

  const list = useMemo(() => {
    if (!ex) return [];
    const needle = q.trim().toLowerCase();
    return ex.items
      .filter((e) => !e.archived)
      .filter((e) => !group || e.group === group)
      .filter((e) => !equip || e.equipment === equip)
      .filter((e) => !needle || e.name.toLowerCase().includes(needle) || e.aliases.some((a) => a.toLowerCase().includes(needle)))
      .sort((a, b) => (needle ? 0 : (b.count > 0) - (a.count > 0)) || a.name.localeCompare(b.name, "de"));
  }, [ex, q, group, equip]);
  const recent = useMemo(() => (ex && !q && !group && !equip
    ? ex.items.filter((e) => e.last && !e.archived).sort((a, b) => b.last.localeCompare(a.last)).slice(0, 6) : []), [ex, q, group, equip]);

  function toggle(id) {
    if (!multi) { onPick([id]); return; }
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  }

  if (creating) {
    return <ExerciseForm initial={{ name: q }} onClose={() => setCreating(false)} onSaved={(e) => { setCreating(false); toggle(e.id); }} />;
  }

  const row = (e) => (
    <button type="button" key={e.id} className={`ex-row${picked.includes(e.id) ? " on" : ""}`} onClick={() => toggle(e.id)}>
      <ExerciseThumb media={e.media} name={e.name} size={44} color={GROUP_COLORS[e.group]} />
      <span className="ex-row-main">
        <strong>{e.name}</strong>
        <span className="tiny muted">{ex.meta.muscles[e.primary] || e.primary} · {ex.meta.equipment[e.equipment] || e.equipment}{e.custom ? " · eigene" : ""}</span>
      </span>
      {e.count ? <span className="tiny muted">{e.count}×</span> : null}
      {multi && <span className="ex-check" aria-hidden="true">{picked.includes(e.id) ? "✓" : "+"}</span>}
    </button>
  );

  return (
    <Modal title={title} onClose={onClose} wide>
      {!ex ? <p className="muted">Lade Übungen …</p> : (
        <div className="picker">
          <input type="search" placeholder="Übung suchen …" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
          <div className="chips">
            <button type="button" className={`chip${!group ? " on" : ""}`} onClick={() => setGroup("")}>Alle</button>
            {GROUPS.map((g) => (
              <button type="button" key={g} className={`chip${group === g ? " on" : ""}`} style={{ "--c": GROUP_COLORS[g] }}
                onClick={() => setGroup(group === g ? "" : g)}><i />{g}</button>
            ))}
          </div>
          <select value={equip} onChange={(e) => setEquip(e.target.value)} aria-label="Ausrüstung">
            <option value="">Jede Ausrüstung</option>
            {Object.entries(ex.meta.equipment).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <div className="picker-list">
            {recent.length > 0 && <><div className="picker-head">Zuletzt</div>{recent.map(row)}<div className="picker-head">Alle Übungen</div></>}
            {list.map(row)}
            {!list.length && <p className="muted small">Nichts gefunden.</p>}
          </div>
          <div className="actions" style={{ justifyContent: "space-between" }}>
            <button type="button" className="btn" onClick={() => setCreating(true)}>Eigene Übung anlegen</button>
            {multi && (
              <button type="button" className="btn primary" disabled={!picked.length} onClick={() => onPick(picked)}>
                {picked.length ? `${picked.length} hinzufügen` : "Auswählen"}
              </button>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}

/** Eigene Übung anlegen oder bearbeiten. */
export function ExerciseForm({ initial = {}, onClose, onSaved }) {
  const ex = useExercises();
  const [v, setV] = useState({ name: "", equipment: "barbell", primary: "chest", secondary: [], kind: "weight_reps", ...initial });
  const [busy, setBusy] = useState(false);
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = initial.id ? await api.put(`/strength/exercises/${initial.id}`, v) : await api.post("/strength/exercises", v);
      await loadExercises(true);
      toast(initial.id ? "Gespeichert" : "Übung angelegt");
      onSaved(r);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  }
  if (!ex) return null;
  const toggleSec = (m) => setV({ ...v, secondary: v.secondary.includes(m) ? v.secondary.filter((x) => x !== m) : [...v.secondary, m] });
  return (
    <Modal title={initial.id ? "Übung bearbeiten" : "Eigene Übung"} onClose={onClose}>
      <form className="stack" onSubmit={save}>
        <label>Name<input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} required maxLength={120} /></label>
        <div className="form-grid">
          <label>Ausrüstung<select value={v.equipment} onChange={(e) => setV({ ...v, equipment: e.target.value })}>
            {Object.entries(ex.meta.equipment).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label>Art<select value={v.kind} onChange={(e) => setV({ ...v, kind: e.target.value })}>
            {Object.entries(ex.meta.kinds).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        </div>
        <label>Hauptmuskel<select value={v.primary} onChange={(e) => setV({ ...v, primary: e.target.value })}>
          {Object.entries(ex.meta.muscles).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <div>
          <div className="small" style={{ fontWeight: 500, marginBottom: "0.4rem" }}>Weitere Muskeln</div>
          <div className="chips">
            {Object.entries(ex.meta.muscles).filter(([k]) => k !== v.primary).map(([k, l]) => (
              <button type="button" key={k} className={`chip${v.secondary.includes(k) ? " on" : ""}`} onClick={() => toggleSec(k)}>{l}</button>
            ))}
          </div>
        </div>
        <MediaChooser value={v.media} name={v.name} onChange={(m) => setV({ ...v, media: m })} />
        <div className="actions">
          <button className="btn primary" disabled={busy}>{busy ? "Speichere …" : "Speichern"}</button>
          <button type="button" className="btn" onClick={onClose}>Abbrechen</button>
        </div>
      </form>
    </Modal>
  );
}


/** Bild aus der freien Übungsdatenbank wählen (Fotos von Start- und Endposition). */
function MediaChooser({ value, name, onChange }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState(name || "");
  const [items, setItems] = useState([]);
  useEffect(() => {
    if (!open) return undefined;
    const t = setTimeout(() => api.get(`/strength/media/search?q=${encodeURIComponent(q)}`).then(setItems).catch(() => setItems([])), 250);
    return () => clearTimeout(t);
  }, [q, open]);
  return (
    <div>
      <div className="field-label">Bild</div>
      <div className="actions" style={{ marginTop: 0 }}>
        <ExerciseThumb media={value} name={name} size={56} animate />
        <button type="button" className="btn small" onClick={() => setOpen(!open)}>{open ? "Schließen" : value ? "Anderes Bild" : "Bild suchen"}</button>
        {value && <button type="button" className="link quiet small" onClick={() => onChange(null)}>ohne Bild</button>}
      </div>
      {open && (
        <>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Englischer Name, z. B. lunge, curl, row" style={{ marginTop: "0.6rem" }} />
          <div className="media-pick">
            {items.map((m) => (
              <button type="button" key={m.id} className={value === m.id ? "on" : ""} onClick={() => { onChange(m.id); setOpen(false); }}>
                <ExerciseThumb media={m.id} name={m.name} size={80} />
                <span>{m.name}</span>
              </button>
            ))}
            {!items.length && <p className="muted small">Nichts gefunden.</p>}
          </div>
        </>
      )}
    </div>
  );
}
