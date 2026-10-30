import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { confirmDialog, Loading, toast } from "../components/feedback.jsx";
import { EmptyState, Kpi, useAsync } from "../components/ui.jsx";
import { fmtNum } from "../fmt.js";
import BodyMap, { valuesFromBlocks } from "../components/BodyMap.jsx";
import BlockEditor from "./BlockEditor.jsx";
import {
  e1rm, fmtClock, fmtKg, fmtVolume, fromDraftBlock, loadExercises, setText, startWorkout, toDraftBlock, useExercises,
} from "./shared.js";

function toLocalInput(iso) {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function when(iso) {
  const d = new Date(iso);
  return d.toLocaleString("de-DE", { weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function WorkoutDetail() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const ex = useExercises();
  const [{ data: w, error }, setW] = useAsync(() => api.get(`/strength/workouts/${id}`), [id]);
  const [edit, setEdit] = useState(null);

  if (error) return <EmptyState title="Nicht gefunden" text={error.message}><Link className="btn" to="/strength">Zurück</Link></EmptyState>;
  if (!w || !ex) return <Loading rows={3} />;
  const fresh = params.get("neu") === "1";
  const prsBy = new Map();
  for (const p of w.prs) prsBy.set(p.exercise_id, [...(prsBy.get(p.exercise_id) || []), p]);

  async function remove() {
    if (!(await confirmDialog("Training löschen? Es verschwindet auch aus Aktivitäten und Auswertungen."))) return;
    await api.del(`/strength/workouts/${w.id}`);
    toast("Gelöscht");
    navigate("/strength");
  }
  async function asRoutine() {
    const r = await api.post(`/strength/workouts/${w.id}/routine`, { name: w.name });
    toast("Als Routine gespeichert");
    navigate(`/strength/routine/${r.id}`);
  }
  async function again() {
    const blocks = w.exercises.map((b) => toDraftBlock({ ...b, sets: b.sets.map((s) => ({ ...s })) }));
    const ok = await startWorkout(navigate, { name: w.name, routine: w.routine_id ? { id: w.routine_id } : null, blocks });
    if (!ok) toast("Es läuft schon ein Training.", "error");
  }
  function startEdit() {
    setEdit({ name: w.name, notes: w.notes || "", start: toLocalInput(w.start), duration: Math.round((w.duration_s || 0) / 60),
      blocks: w.exercises.map((b) => toDraftBlock(b, { done: true })) });
  }
  async function saveEdit() {
    try {
      const start = new Date(edit.start); // Ortszeit aus dem Eingabefeld
      const body = {
        name: edit.name, notes: edit.notes, start: start.toISOString(), routine_id: w.routine_id,
        end: edit.duration ? new Date(start.getTime() + edit.duration * 60000).toISOString() : null,
        exercises: edit.blocks.map((b) => fromDraftBlock(b)),
      };
      const saved = await api.put(`/strength/workouts/${w.id}`, body);
      setW(saved);
      setEdit(null);
      loadExercises(true);
      toast("Gespeichert");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  if (edit) {
    return (
      <div className="strength-log">
        <div className="page-head">
          <div><h1>Training bearbeiten</h1></div>
          <div className="actions"><button className="btn" onClick={() => setEdit(null)}>Abbrechen</button><button className="btn primary" onClick={saveEdit}>Speichern</button></div>
        </div>
        <section className="panel">
          <div className="form-grid">
            <label>Name<input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></label>
            <label>Beginn<input type="datetime-local" value={edit.start} onChange={(e) => setEdit({ ...edit, start: e.target.value })} /></label>
            <label>Dauer (Minuten)<input inputMode="numeric" value={edit.duration} onChange={(e) => setEdit({ ...edit, duration: Number(e.target.value.replace(/\D/g, "")) || 0 })} /></label>
            <label>Notiz<input value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} /></label>
          </div>
        </section>
        <BlockEditor blocks={edit.blocks} onChange={(blocks) => setEdit({ ...edit, blocks })} mode="edit" byId={ex.byId} meta={ex.meta} />
      </div>
    );
  }

  return (
    <div className="cat-activity">
      <div className="page-head">
        <div>
          <p style={{ margin: 0 }}><Link className="link quiet small" to="/strength">Kraft</Link></p>
          <h1>{w.name}</h1>
          <p>{when(w.start)}{w.source !== "bodybase" ? ` · aus ${w.source === "hevy" ? "Hevy" : "Strong"}` : ""}</p>
        </div>
        <div className="actions">
          <button className="btn" onClick={again}>Wiederholen</button>
          <button className="btn" onClick={asRoutine}>Als Routine speichern</button>
          <button className="btn" onClick={startEdit}>Bearbeiten</button>
          <button className="btn danger" onClick={remove}>Löschen</button>
        </div>
      </div>
      {fresh && (
        <div className="done-banner">
          <strong>Stark! Training gespeichert.</strong>
          <span>{w.prs.length ? `${w.prs.length} neue ${w.prs.length === 1 ? "Bestleistung" : "Bestleistungen"} 🏆` : "Weiter so."}</span>
        </div>
      )}
      <div className="kpis">
        <Kpi label="Dauer" value={w.duration_s ? fmtClock(w.duration_s) : "–"} />
        <Kpi label="Volumen" value={fmtVolume(w.volume_kg)} />
        <Kpi label="Sätze" value={fmtNum(w.sets)} />
        <Kpi label="Wiederholungen" value={fmtNum(w.reps)} />
        <Kpi label="Rekorde" value={fmtNum(w.prs.length)} />
      </div>
      <section className="panel">
        <div className="panel-head"><h2>Trainierte Muskeln</h2><span className="tiny muted">Arbeitssätze, Nebenmuskeln zählen halb</span></div>
        <BodyMap values={valuesFromBlocks(w.exercises)} unit="Sätze" />
      </section>
      {w.notes && <section className="panel"><p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{w.notes}</p></section>}
      <div className="grid-2">
        {w.exercises.map((b, i) => {
          let n = 0;
          const prs = prsBy.get(b.exercise_id) || [];
          return (
            <section key={i} className={`panel${b.superset != null ? " in-superset" : ""}`}>
              <div className="panel-head">
                <h3><Link className="link" to={`/strength/exercise/${b.exercise_id}`}>{b.name}</Link></h3>
                {b.superset != null && <span className="pill iris">Supersatz {b.superset + 1}</span>}
              </div>
              {b.notes && <p className="small muted" style={{ marginTop: 0 }}>{b.notes}</p>}
              {prs.length > 0 && (
                <div className="chips" style={{ marginBottom: "0.6rem" }}>
                  {prs.map((p) => <span key={p.type} className="pr-badge">🏆 {p.label}</span>)}
                </div>
              )}
              <table className="table compact">
                <thead><tr><th>Satz</th><th>Gewicht × Wdh.</th><th className="num">1RM</th></tr></thead>
                <tbody>
                  {b.sets.map((s, j) => {
                    if (s.type !== "warmup") n += 1;
                    const orm = (b.kind === "weight_reps" || b.kind === "weighted_bw") ? e1rm(s.kg, s.reps) : null;
                    return (
                      <tr key={j}>
                        <td><span className={`set-label t-${s.type}`}>{s.type === "warmup" ? "W" : s.type === "failure" ? "F" : s.type === "drop" ? "D" : n}</span></td>
                        <td>{setText(s, b.kind)}{s.rpe ? <span className="muted small"> @ RPE {fmtNum(s.rpe, s.rpe % 1 ? 1 : 0)}</span> : null}</td>
                        <td className="num muted">{orm ? `${fmtKg(Math.round(orm * 10) / 10)} kg` : ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>
          );
        })}
      </div>
    </div>
  );
}
