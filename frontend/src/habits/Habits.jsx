import { useEffect, useState } from "react";
import { api } from "../api.js";
import { confirmDialog, Loading, toast } from "../components/feedback.jsx";
import { EmptyState, Modal } from "../components/ui.jsx";
import { fmtDay, fmtNum, todayIso, weekdayShort } from "../fmt.js";
import ExercisePicker from "../strength/ExercisePicker.jsx";
import { useExercises } from "../strength/shared.js";
import { HabitRow } from "./HabitsToday.jsx";

const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const COLORS = ["var(--c-recovery)", "var(--c-activity)", "var(--c-heart)", "var(--c-body)", "var(--c-sleep)", "var(--c-nutrition)"];

export default function Habits() {
  const [items, setItems] = useState(null);
  const [edit, setEdit] = useState(null);
  const [showArchived, setShowArchived] = useState(false);
  async function load() { setItems(await api.get(`/habits${showArchived ? "?archived=true" : ""}`)); }
  useEffect(() => { load().catch(() => setItems([])); }, [showArchived]); // eslint-disable-line react-hooks/exhaustive-deps
  const update = (h) => setItems((cur) => cur.map((x) => (x.id === h.id ? h : x)));

  return (
    <div className="cat-recovery">
      <div className="page-head">
        <div>
          <h1>Gewohnheiten</h1>
          <p>Kleine Dinge jeden Tag: Liegestütze, Dehnen, Wasser. Mit Zielen, die jede Woche ein Stück wachsen. Übungen zählen auch für die Körperkarte.</p>
        </div>
        <div className="actions">
          <label className="check"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />Archivierte zeigen</label>
          <button className="btn primary" onClick={() => setEdit({})}>Neue Gewohnheit</button>
        </div>
      </div>
      {!items ? <Loading rows={2} /> : !items.length ? (
        <EmptyState title="Noch keine Gewohnheit" text="Lege zum Beispiel „Liegestütze“ an: Start mit 20 am Tag, jede Woche 5 mehr.">
          <button className="btn primary" onClick={() => setEdit({ name: "Liegestütze", target: 20, increment: 5, unit: "Wdh." })}>Liegestütze anlegen</button>
        </EmptyState>
      ) : items.map((h) => <HabitCard key={h.id} h={h} onChange={update} onEdit={() => setEdit(h)} />)}
      {edit && <HabitForm initial={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} />}
    </div>
  );
}

function HabitCard({ h, onChange, onEdit }) {
  const [day, setDay] = useState(null);
  const recent = h.recent;
  const max = Math.max(1, ...recent.map((x) => Math.max(x.value || 0, x.target || 0)));
  return (
    <section className="panel habit-card" style={{ "--c": h.color || "var(--c-recovery)" }}>
      <HabitRow h={h} onChange={onChange} />
      <div className="habit-stats">
        <span><b>{h.streak}</b><small>Tage in Folge</small></span>
        <span><b>{h.best_streak}</b><small>beste Serie</small></span>
        {h.rate_28 != null && <span><b>{Math.round(h.rate_28 * 100)} %</b><small>geschafft (28 Tage)</small></span>}
        {h.kind === "count" && <span><b>{fmtNum(h.week_total)}</b><small>{h.unit || ""} diese Woche</small></span>}
        {h.exercise && <span><b className="small">{h.exercise}</b><small>zählt für die Körperkarte</small></span>}
      </div>
      <div className="habit-days" role="list" aria-label="Letzte 28 Tage">
        {recent.map((x) => (
          <button key={x.day} type="button" role="listitem" className={`habit-day${x.done ? " done" : x.value ? " part" : ""}${x.due ? "" : " off"}${x.day === todayIso() ? " today" : ""}`}
            title={`${fmtDay(x.day)}: ${x.value ? fmtNum(x.value) : "–"}${x.target && h.kind === "count" ? ` / ${fmtNum(x.target)}` : ""}`} onClick={() => setDay(x)}>
            {h.kind === "count" && <i style={{ height: `${Math.min(100, ((x.value || 0) / max) * 100)}%` }} />}
            {h.kind === "count" && x.target ? <em style={{ bottom: `${(x.target / max) * 100}%` }} /> : null}
            <span>{weekdayShort(x.day).slice(0, 2)}</span>
          </button>
        ))}
      </div>
      <div className="actions" style={{ marginTop: "0.6rem" }}>
        <button className="btn small" onClick={onEdit}>Bearbeiten</button>
      </div>
      {day && <DayDialog h={h} day={day} onClose={() => setDay(null)} onSaved={(next) => { onChange(next); setDay(null); }} />}
    </section>
  );
}

function DayDialog({ h, day, onClose, onSaved }) {
  const [value, setValue] = useState(day.value ?? (h.kind === "check" ? 1 : day.target ?? ""));
  async function save(v) {
    try { onSaved(await api.post(`/habits/${h.id}/log`, { day: day.day, value: v })); } catch (e) { toast(e.message, "error"); }
  }
  return (
    <Modal title={`${h.name} · ${fmtDay(day.day)}`} onClose={onClose}>
      {h.kind === "check" ? (
        <div className="actions">
          <button className="btn primary" onClick={() => save(1)}>Erledigt</button>
          <button className="btn" onClick={() => save(0)}>Nicht erledigt</button>
        </div>
      ) : (
        <form className="stack" onSubmit={(e) => { e.preventDefault(); save(Number(String(value).replace(",", ".")) || 0); }}>
          <label>Geschafft ({h.unit || "Anzahl"}){day.target ? <span className="hint">Ziel an diesem Tag: {fmtNum(day.target)}</span> : null}
            <input inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} autoFocus /></label>
          <div className="actions"><button className="btn primary">Speichern</button><button type="button" className="btn" onClick={onClose}>Abbrechen</button></div>
        </form>
      )}
    </Modal>
  );
}

function HabitForm({ initial, onClose, onSaved }) {
  const ex = useExercises();
  const [v, setV] = useState({
    name: "", kind: "count", unit: "", target: "", increment: "", max_target: "", weekdays: [], exercise_id: null,
    start: todayIso(), color: COLORS[0], ...initial,
  });
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const exName = v.exercise_id && ex ? ex.byId.get(v.exercise_id)?.name : null;
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      if (initial.id) await api.put(`/habits/${initial.id}`, v); else await api.post("/habits", v);
      toast("Gespeichert");
      onSaved();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  }
  async function archive(flag) {
    await api.put(`/habits/${initial.id}`, { ...v, archived: flag });
    onSaved();
  }
  async function remove() {
    if (!(await confirmDialog(`„${initial.name}“ mit allen Einträgen löschen? Archivieren behält den Verlauf.`))) return;
    await api.del(`/habits/${initial.id}`);
    onSaved();
  }
  const toggleDay = (d) => setV({ ...v, weekdays: v.weekdays.includes(d) ? v.weekdays.filter((x) => x !== d) : [...v.weekdays, d].sort() });
  const preview = v.kind === "count" && Number(v.target) ? [0, 1, 2, 3].map((w) => {
    const t = Number(v.target) + (Number(v.increment) || 0) * w;
    return Number(v.max_target) ? Math.min(t, Number(v.max_target)) : t;
  }) : null;
  return (
    <Modal title={initial.id ? "Gewohnheit bearbeiten" : "Neue Gewohnheit"} onClose={onClose}>
      <form className="stack" onSubmit={save}>
        <label>Name<input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} placeholder="z. B. Liegestütze" required /></label>
        <div className="segmented" role="radiogroup" aria-label="Art">
          <button type="button" className={v.kind === "count" ? "on" : ""} onClick={() => setV({ ...v, kind: "count" })}>Anzahl erreichen</button>
          <button type="button" className={v.kind === "check" ? "on" : ""} onClick={() => setV({ ...v, kind: "check" })}>Abhaken</button>
        </div>
        <div>
          <div className="field-label">Übung (optional, zählt dann für die Körperkarte)</div>
          <div className="actions" style={{ marginTop: 0 }}>
            <button type="button" className="btn small" onClick={() => setPicking(true)}>{exName || "Übung wählen"}</button>
            {v.exercise_id && <button type="button" className="link quiet small" onClick={() => setV({ ...v, exercise_id: null })}>entfernen</button>}
          </div>
        </div>
        {v.kind === "count" && (
          <>
            <div className="form-grid">
              <label>Tagesziel in der ersten Woche<input inputMode="decimal" value={v.target ?? ""} onChange={(e) => setV({ ...v, target: e.target.value })} required /></label>
              <label>Einheit<input value={v.unit || ""} onChange={(e) => setV({ ...v, unit: e.target.value })} placeholder="Wdh., Minuten, Liter …" /></label>
              <label>Erhöhung jede Woche (montags)<input inputMode="decimal" value={v.increment ?? ""} onChange={(e) => setV({ ...v, increment: e.target.value })} placeholder="z. B. 5" /></label>
              <label>Höchstens<input inputMode="decimal" value={v.max_target ?? ""} onChange={(e) => setV({ ...v, max_target: e.target.value })} placeholder="ohne Grenze" /></label>
            </div>
            {preview && <p className="hint">Ziele der nächsten Wochen: {preview.map((x) => fmtNum(x, x % 1 ? 1 : 0)).join(" → ")} {v.unit || ""}</p>}
          </>
        )}
        <div>
          <div className="field-label">An welchen Tagen? (nichts gewählt = täglich)</div>
          <div className="chips">{WEEKDAYS.map((d, i) => <button type="button" key={d} className={`chip${v.weekdays.includes(i) ? " on" : ""}`} onClick={() => toggleDay(i)}>{d}</button>)}</div>
        </div>
        <div className="form-grid">
          <label>Start<input type="date" value={v.start || ""} onChange={(e) => setV({ ...v, start: e.target.value })} /></label>
          <div>
            <div className="field-label">Farbe</div>
            <div className="chips">{COLORS.map((c) => <button type="button" key={c} className={`color-dot${v.color === c ? " on" : ""}`} style={{ background: c }} onClick={() => setV({ ...v, color: c })} aria-label="Farbe" />)}</div>
          </div>
        </div>
        <div className="actions">
          <button className="btn primary" disabled={busy}>Speichern</button>
          <button type="button" className="btn" onClick={onClose}>Abbrechen</button>
          {initial.id && <button type="button" className="btn" onClick={() => archive(!initial.archived)}>{initial.archived ? "Wiederherstellen" : "Archivieren"}</button>}
          {initial.id && <button type="button" className="btn danger" onClick={remove}>Löschen</button>}
        </div>
      </form>
      {picking && <ExercisePicker multi={false} title="Übung wählen" onClose={() => setPicking(false)}
        onPick={([id]) => { const e = ex?.byId.get(id); setV({ ...v, exercise_id: id, name: v.name || e?.name || "", unit: v.unit || (e?.kind === "duration" ? "Sekunden" : "Wdh.") }); setPicking(false); }} />}
    </Modal>
  );
}
