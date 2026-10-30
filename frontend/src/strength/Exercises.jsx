import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { LineChart } from "../components/charts.jsx";
import { confirmDialog, Loading, toast } from "../components/feedback.jsx";
import { EmptyState, Kpi, Segmented, useAsync } from "../components/ui.jsx";
import { fmtDate, fmtNum } from "../fmt.js";
import BodyMap from "../components/BodyMap.jsx";
import { ExerciseForm } from "./ExercisePicker.jsx";
import { GROUP_COLORS, fmtClock, fmtKg, fmtVolume, loadExercises, setText, useExercises } from "./shared.js";

const GROUPS = ["Brust", "Rücken", "Schultern", "Arme", "Beine", "Rumpf", "Ganzkörper", "Ausdauer", "Sonstiges"];

export function ExerciseLibrary() {
  const ex = useExercises();
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("");
  const [onlyUsed, setOnlyUsed] = useState(false);
  const [unassigned, setUnassigned] = useState(false);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();
  const list = useMemo(() => {
    if (!ex) return [];
    const needle = q.trim().toLowerCase();
    return ex.items.filter((e) => !e.archived && (!group || e.group === group) && (!onlyUsed || e.count) && (!unassigned || e.primary === "other")
      && (!needle || e.name.toLowerCase().includes(needle) || e.aliases.some((a) => a.toLowerCase().includes(needle))));
  }, [ex, q, group, onlyUsed, unassigned]);
  if (!ex) return <Loading rows={3} />;
  return (
    <div className="cat-activity">
      <div className="page-head">
        <div>
          <p style={{ margin: 0 }}><Link className="link quiet small" to="/strength">Kraft</Link></p>
          <h1>Übungen</h1>
          <p>{ex.items.filter((e) => !e.custom).length} eingebaute und {ex.items.filter((e) => e.custom && !e.archived).length} eigene Übungen.</p>
        </div>
        <div className="actions"><button className="btn primary" onClick={() => setCreating(true)}>Eigene Übung</button></div>
      </div>
      <div className="filters" style={{ marginBottom: "1rem" }}>
        <input type="search" placeholder="Suchen …" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="check"><input type="checkbox" checked={onlyUsed} onChange={(e) => setOnlyUsed(e.target.checked)} />Nur benutzte</label>
        <label className="check"><input type="checkbox" checked={unassigned} onChange={(e) => setUnassigned(e.target.checked)} />Ohne Muskelzuordnung ({ex.items.filter((e) => !e.archived && e.primary === "other").length})</label>
      </div>
      <div className="chips" style={{ marginBottom: "1rem" }}>
        <button type="button" className={`chip${!group ? " on" : ""}`} onClick={() => setGroup("")}>Alle</button>
        {GROUPS.map((g) => <button type="button" key={g} className={`chip${group === g ? " on" : ""}`} style={{ "--c": GROUP_COLORS[g] }} onClick={() => setGroup(group === g ? "" : g)}><i />{g}</button>)}
      </div>
      <div className="ex-grid">
        {list.map((e) => (
          <Link key={e.id} to={`/strength/exercise/${e.id}`} className="ex-row" style={{ "--c": GROUP_COLORS[e.group] }}>
            <span className="ex-dot" aria-hidden="true">{e.name.slice(0, 1)}</span>
            <span className="ex-row-main">
              <strong>{e.name}</strong>
              <span className="tiny muted">{ex.meta.muscles[e.primary]} · {ex.meta.equipment[e.equipment]}{e.custom ? " · eigene" : ""}</span>
            </span>
            <span className="tiny muted">{e.count ? `${e.count}× · ${fmtDate(e.last)}` : ""}</span>
          </Link>
        ))}
      </div>
      {!list.length && <p className="muted">Keine Übung gefunden.</p>}
      {creating && <ExerciseForm initial={{ name: q }} onClose={() => setCreating(false)} onSaved={(e) => { setCreating(false); navigate(`/strength/exercise/${e.id}`); }} />}
    </div>
  );
}

const CHARTS = {
  weight: [
    { value: "heaviest", label: "Schwerstes Gewicht", unit: "kg" },
    { value: "e1rm", label: "1RM (geschätzt)", unit: "kg" },
    { value: "best_set_volume", label: "Bester Satz", unit: "kg" },
    { value: "volume", label: "Volumen", unit: "kg" },
    { value: "reps", label: "Wiederholungen", unit: "" },
  ],
  reps: [{ value: "reps", label: "Wiederholungen", unit: "" }],
  duration: [{ value: "duration", label: "Längste Dauer", unit: "s" }],
  distance: [{ value: "distance", label: "Weiteste Strecke", unit: "m" }],
};

function chartsFor(kind) {
  if (kind === "weight_reps" || kind === "weighted_bw") return CHARTS.weight;
  if (kind === "duration") return CHARTS.duration;
  if (kind === "distance") return CHARTS.distance;
  return CHARTS.reps;
}

export function ExerciseDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const exs = useExercises();
  const [{ data, error }, setData] = useAsync(() => api.get(`/strength/exercises/${id}`), [id]);
  const [metric, setMetric] = useState(null);
  const [editing, setEditing] = useState(false);
  if (error) return <EmptyState title="Nicht gefunden" text={error.message}><Link className="btn" to="/strength/exercises">Zurück</Link></EmptyState>;
  if (!data || !exs) return <Loading rows={3} />;
  const e = data.exercise;
  const options = chartsFor(e.kind);
  const m = options.find((o) => o.value === metric) || options[0];
  const fmtVal = (v) => (m.unit === "s" ? fmtClock(v) : m.unit === "m" ? `${fmtNum(v / 1000, 2)} km` : m.unit ? `${fmtKg(v)} kg` : fmtNum(v));
  const series = data.sessions.filter((s) => s[m.value] != null).map((s) => ({ day: s.day, value: s[m.value] }));
  const r = data.records;
  const isWeight = e.kind === "weight_reps" || e.kind === "weighted_bw";

  async function archive() {
    if (!(await confirmDialog("Übung entfernen? Wenn sie schon benutzt wurde, bleibt ihr Verlauf erhalten und sie verschwindet nur aus der Auswahl."))) return;
    await api.del(`/strength/exercises/${e.id}`);
    await loadExercises(true);
    toast("Entfernt");
    navigate("/strength/exercises");
  }

  return (
    <div className="cat-activity" style={{ "--c": GROUP_COLORS[e.group] }}>
      <div className="page-head">
        <div>
          <p style={{ margin: 0 }}><Link className="link quiet small" to="/strength/exercises">Übungen</Link></p>
          <h1>{e.name}</h1>
          <p>{exs.meta.muscles[e.primary]}{e.secondary.length ? ` · auch ${e.secondary.map((x) => exs.meta.muscles[x]).join(", ")}` : ""} · {exs.meta.equipment[e.equipment]}</p>
        </div>
        {e.custom && (
          <div className="actions">
            <button className="btn" onClick={() => setEditing(true)}>Bearbeiten</button>
            <button className="btn danger" onClick={archive}>Entfernen</button>
          </div>
        )}
      </div>
      <section className="panel ex-muscles">
        <BodyMap values={{ ...Object.fromEntries(e.secondary.map((m) => [m, 1])), [e.primary]: 2 }} unit="" list={false} size="sm" />
        <div>
          <p style={{ marginTop: 0 }}><strong>Hauptmuskel:</strong> {exs.meta.muscles[e.primary]}</p>
          <p><strong>Weitere:</strong> {e.secondary.length ? e.secondary.map((x) => exs.meta.muscles[x]).join(", ") : "keine"}</p>
          {e.primary === "other" && <p className="hint">Noch keinem Muskel zugeordnet.{e.custom ? " Unter „Bearbeiten“ festlegen, dann zählt die Übung in Körperkarte und Auswertung." : ""}</p>}
        </div>
      </section>
      {!data.sessions.length ? (
        <EmptyState title="Noch nicht trainiert" text="Sobald du die Übung in einem Training einträgst, erscheinen hier Verlauf und Rekorde." />
      ) : (
        <>
          <div className="kpis">
            {isWeight && r.heaviest && <Kpi label="Schwerstes Gewicht" value={fmtKg(r.heaviest.value)} unit="kg" sub={fmtDate(r.heaviest.day)} />}
            {isWeight && r.e1rm && <Kpi label="Bestes 1RM (geschätzt)" value={fmtKg(r.e1rm.value)} unit="kg" sub={fmtDate(r.e1rm.day)} />}
            {isWeight && r.best_set_volume && <Kpi label="Bester Satz (Volumen)" value={fmtKg(r.best_set_volume.value)} unit="kg" sub={fmtDate(r.best_set_volume.day)} />}
            {isWeight && r.volume && <Kpi label="Bestes Einheitsvolumen" value={fmtVolume(r.volume.value)} sub={fmtDate(r.volume.day)} />}
            {!isWeight && r.reps && <Kpi label="Meiste Wiederholungen (Satz)" value={fmtNum(r.reps.value)} sub={fmtDate(r.reps.day)} />}
            {r.duration && <Kpi label="Längste Dauer" value={fmtClock(r.duration.value)} sub={fmtDate(r.duration.day)} />}
            {r.distance && <Kpi label="Weiteste Strecke" value={fmtNum(r.distance.value / 1000, 2)} unit="km" sub={fmtDate(r.distance.day)} />}
            <Kpi label="Insgesamt" value={fmtNum(data.total.sessions)} unit="Einheiten" sub={`${fmtNum(data.total.sets)} Sätze · ${fmtNum(data.total.reps)} Wdh.`} />
          </div>
          <section className="panel">
            <div className="panel-head">
              <h2>Verlauf</h2>
              {options.length > 1 && <Segmented value={m.value} onChange={setMetric} options={options} label="Größe" />}
            </div>
            <LineChart data={series} format={fmtVal} label={m.label} />
          </section>
          <div className="grid-2">
            {isWeight && data.rep_records.length > 0 && (
              <section className="panel">
                <div className="panel-head"><h2>Rekorde nach Wiederholungen</h2></div>
                <table className="table compact">
                  <thead><tr><th>Wdh.</th><th>Bestes Gewicht</th><th>Datum</th></tr></thead>
                  <tbody>{data.rep_records.map((x) => (
                    <tr key={x.reps}><td>{x.reps}</td><td><strong>{fmtKg(x.kg)} kg</strong></td>
                      <td><Link className="link quiet small" to={`/strength/workout/${x.workout_id}`}>{fmtDate(x.day)}</Link></td></tr>
                  ))}</tbody>
                </table>
              </section>
            )}
            <section className="panel">
              <div className="panel-head"><h2>Einheiten</h2></div>
              <div className="feed">
                {[...data.sessions].reverse().slice(0, 30).map((s) => (
                  <div key={s.workout_id} className="feed-item">
                    <div className="feed-head">
                      <Link className="link" to={`/strength/workout/${s.workout_id}`}><strong>{s.name}</strong></Link>
                      <span className="muted small">{fmtDate(s.day)}</span>
                    </div>
                    <div className="small">{s.sets.map((x, i) => <span key={i} className={`set-chip t-${x.type}`}>{setText(x, e.kind)}</span>)}</div>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </>
      )}
      {editing && <ExerciseForm initial={e} onClose={() => setEditing(false)} onSaved={async () => { setEditing(false); setData(await api.get(`/strength/exercises/${id}`)); }} />}
    </div>
  );
}
