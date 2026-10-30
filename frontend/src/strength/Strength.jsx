import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { Calendar, useWidth } from "../components/charts.jsx";
import { confirmDialog, Loading, toast } from "../components/feedback.jsx";
import { Delta, EmptyState, Kpi, Segmented, useAsync } from "../components/ui.jsx";
import { fmtDate, fmtDayShort, fmtNum, todayIso } from "../fmt.js";
import {
  GROUP_COLORS, fmtClock, fmtVolume, loadExercises, readLocalActive, routineToBlocks, startWorkout, useExercises,
} from "./shared.js";

const RANGES = [{ value: 30, label: "30 Tage" }, { value: 90, label: "90 Tage" }, { value: 365, label: "1 Jahr" }, { value: 0, label: "Alles" }];
const WEEK_METRICS = [
  { value: "workouts", label: "Trainings", fmt: (v) => fmtNum(v) },
  { value: "volume", label: "Volumen", fmt: (v) => fmtVolume(v) },
  { value: "duration_s", label: "Dauer", fmt: (v) => `${fmtNum(v / 3600, 1)} h` },
  { value: "sets", label: "Sätze", fmt: (v) => fmtNum(v) },
  { value: "reps", label: "Wdh.", fmt: (v) => fmtNum(v) },
];

export default function Strength() {
  const navigate = useNavigate();
  const [days, setDays] = useState(30);
  const [{ data: sum }, setSum] = useAsync(() => api.get(`/strength/summary?days=${days}`), [days]);
  const [{ data: routines }, setRoutines] = useAsync(() => api.get("/strength/routines"), []);
  const [active, setActive] = useState(() => readLocalActive());
  useEffect(() => { api.get("/strength/active").then((r) => r.data && setActive(r.data)).catch(() => {}); }, []);

  async function startRoutine(r) {
    const ok = await startWorkout(navigate, { name: r.name, routine: r, blocks: routineToBlocks(r) });
    if (!ok) toast("Es läuft schon ein Training. Beende es zuerst.", "error");
  }

  async function reload() {
    setSum(await api.get(`/strength/summary?days=${days}`));
    setRoutines(await api.get("/strength/routines"));
  }

  return (
    <div className="cat-activity strength">
      <div className="page-head">
        <div>
          <h1>Kraft</h1>
          <p>Trainings eintragen, Routinen planen und Fortschritte sehen. Wie Hevy, nur auf deinem Server.</p>
        </div>
        <div className="actions">
          <ImportButton onDone={reload} />
          <Link className="btn" to="/strength/exercises">Übungen</Link>
          {active?.exercises
            ? <Link className="btn primary" to="/strength/log">Training fortsetzen</Link>
            : <button className="btn primary" onClick={() => startWorkout(navigate, {})}>Leeres Training starten</button>}
        </div>
      </div>

      {active?.exercises && (
        <Link to="/strength/log" className="active-banner">
          <span className="pill ok"><span className="live" />läuft</span>
          <strong>{active.name}</strong>
          <span className="muted">seit {fmtClock((Date.now() - new Date(active.start).getTime()) / 1000)} · {active.exercises.length} Übungen</span>
          <span className="link">Weiter →</span>
        </Link>
      )}

      <section className="panel">
        <div className="panel-head">
          <h2>Routinen</h2>
          <Link className="btn small" to="/strength/routine/new">Neue Routine</Link>
        </div>
        {!routines ? <Loading rows={1} /> : routines.length ? (
          <div className="routine-grid">
            {routines.map((r) => (
              <div key={r.id} className="routine-card">
                <div className="routine-top">
                  <Link to={`/strength/routine/${r.id}`} className="link"><strong>{r.name}</strong></Link>
                  {r.folder && <span className="pill">{r.folder}</span>}
                </div>
                <p className="small muted routine-ex">{r.exercises.map((e) => `${e.sets.length}× ${e.name}`).join(" · ") || "Noch keine Übungen"}</p>
                <div className="routine-foot">
                  <span className="tiny muted">{r.last_done ? `zuletzt ${fmtDate(r.last_done)}` : "noch nie gemacht"}</span>
                  <button className="btn small primary" disabled={!r.exercises.length} onClick={() => startRoutine(r)}>Starten</button>
                </div>
              </div>
            ))}
          </div>
        ) : <p className="muted">Lege Routinen an (z. B. Push, Pull, Beine), um Trainings mit einem Tipp zu starten. Fertige Trainings kannst du auch als Routine speichern.</p>}
      </section>

      <div className="panel-head" style={{ marginTop: "0.5rem" }}>
        <h2>Auswertung</h2>
        <Segmented value={days} onChange={setDays} options={RANGES} label="Zeitraum" />
      </div>
      {!sum ? <Loading rows={2} /> : sum.all_time.workouts === 0 ? (
        <EmptyState title="Noch keine Trainings" text="Starte dein erstes Training oder übernimm deine bisherigen Daten aus Hevy oder Strong (CSV-Export) über „Importieren“." />
      ) : <Stats sum={sum} days={days} />}

      <History onChanged={reload} />
    </div>
  );
}

const CHUNK = 768 * 1024;

/** Datei komprimieren und in kleinen Stücken senden (Proxys lassen oft nur 1 MB pro Anfrage zu), dann auf das Ergebnis warten. */
async function uploadImport(file, report) {
  let data = new Uint8Array(await file.arrayBuffer());
  const zipped = data[0] === 0x50 && data[1] === 0x4b;
  if (!zipped && typeof CompressionStream !== "undefined") {
    try {
      const stream = new Blob([data]).stream().pipeThrough(new CompressionStream("gzip"));
      data = new Uint8Array(await new Response(stream).arrayBuffer());
    } catch { /* ohne Komprimierung weiter */ }
  }
  const id = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
  const total = Math.max(1, Math.ceil(data.length / CHUNK));
  let res = null;
  for (let i = 0; i < total; i++) {
    report(total > 1 ? `Lade hoch … ${Math.round((i / total) * 100)} %` : "Lade hoch …");
    let attempt = 0;
    for (;;) {
      const r = await fetch("/api/strength/import/chunk", {
        method: "POST", credentials: "same-origin", body: data.slice(i * CHUNK, (i + 1) * CHUNK),
        headers: { "X-BB-Request": "1", "Content-Type": "application/octet-stream", "X-Upload-Id": id, "X-Chunk-Index": String(i),
          "X-Chunk-Total": String(total), "X-Filename": encodeURIComponent(file.name).slice(0, 200) },
      }).catch((e) => ({ ok: false, status: 0, error: e }));
      if (r.ok) { res = await r.json(); break; }
      if (r.status === 0 && attempt++ < 2) continue; // kurzer Funkaussetzer
      let msg = r.status === 413 ? "Der Proxy vor BodyBase lehnt die Datei ab (zu groß)." : r.status ? `Fehler ${r.status}` : "Verbindung abgebrochen.";
      try { const j = await r.json(); if (typeof j.detail === "string") msg = j.detail; } catch { /* keine JSON-Antwort */ }
      throw new Error(msg);
    }
  }
  report("Lese Trainings ein …");
  for (let n = 0; n < 900; n++) {
    await new Promise((ok) => setTimeout(ok, n < 5 ? 600 : 1500));
    const st = await api.get(`/strength/import/${res.job_id}`);
    if (st.status === "done") return st.result;
    if (st.status === "failed") throw new Error(st.message || "Import fehlgeschlagen");
  }
  throw new Error("Der Import dauert ungewöhnlich lange. Schau später unter Verlauf nach.");
}

function ImportButton({ onDone }) {
  const ref = useRef(null);
  const [busy, setBusy] = useState(false);
  async function onFile(e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setBusy(true);
    try {
      const r = await uploadImport(f, setBusy);
      await loadExercises(true);
      toast(`${r.source === "hevy" ? "Hevy" : "Strong"}: ${r.created} neue, ${r.updated} aktualisierte Trainings${r.new_exercises ? `, ${r.new_exercises} neue Übungen` : ""}${r.skipped ? `, ${r.skipped} übersprungen` : ""}`);
      onDone?.();
    } catch (err) {
      toast(err.message === "Failed to fetch" ? "Verbindung abgebrochen. Bitte erneut versuchen." : err.message, "error");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button className="btn" onClick={() => ref.current?.click()} disabled={busy} title="CSV-Export aus Hevy (Einstellungen → Daten exportieren) oder Strong">
        {busy ? (typeof busy === "string" ? busy : "Importiere …") : "Importieren"}
      </button>
      <input ref={ref} type="file" accept=".csv,.zip,.txt,text/csv,text/comma-separated-values,text/plain,application/vnd.ms-excel,application/zip" hidden onChange={onFile} />
    </>
  );
}

function Stats({ sum, days }) {
  const [metric, setMetric] = useState("volume");
  const t = sum.totals, p = sum.previous;
  const m = WEEK_METRICS.find((x) => x.value === metric);
  const maxGroup = Math.max(1, ...sum.groups.map((g) => g.sets));
  const maxMuscle = Math.max(1, ...sum.muscles.map((x) => Math.max(x.sets, x.previous)));
  return (
    <>
      <div className="kpis">
        <Kpi label="Trainings" value={fmtNum(t.workouts)} sub={p ? <Delta value={t.workouts - p.workouts} better="up" format={(v) => fmtNum(v)} /> : null} />
        <Kpi label="Volumen" value={fmtVolume(t.volume)} sub={p ? <Delta value={t.volume - p.volume} better="up" format={(v) => fmtVolume(Math.abs(v))} /> : null} />
        <Kpi label="Sätze" value={fmtNum(t.sets)} sub={`${fmtNum(t.reps)} Wiederholungen`} />
        <Kpi label="Trainingszeit" value={fmtNum(t.duration_s / 3600, 1)} unit="h" sub={t.workouts ? `Ø ${fmtNum(t.duration_s / 60 / t.workouts)} min` : null} />
        <Kpi label="Serie" value={fmtNum(sum.streak_weeks)} unit={sum.streak_weeks === 1 ? "Woche" : "Wochen"} sub="in Folge mit Training" />
        <Kpi label="Rekorde" value={fmtNum(t.prs)} sub={days ? `in ${days} Tagen` : "insgesamt"} />
      </div>
      <div className="grid-2">
        <section className="panel">
          <div className="panel-head">
            <h2>Pro Woche</h2>
            <Segmented value={metric} onChange={setMetric} options={WEEK_METRICS} label="Größe" />
          </div>
          <WeekBars weeks={sum.weeks} metric={metric} fmt={m.fmt} />
        </section>
        <section className="panel">
          <div className="panel-head"><h2>Muskelverteilung</h2><span className="tiny muted">Arbeitssätze, Nebenmuskeln zählen halb</span></div>
          {sum.groups.length ? (
            <>
              <div className="group-bars">
                {sum.groups.map((g) => (
                  <div key={g.group} className="group-bar" style={{ "--c": GROUP_COLORS[g.group] || "var(--iris)" }}>
                    <span>{g.group}</span>
                    <div className="track"><div className="fill" style={{ width: `${(g.sets / maxGroup) * 100}%` }} /></div>
                    <span className="num">{fmtNum(g.sets, g.sets % 1 ? 1 : 0)}</span>
                  </div>
                ))}
              </div>
              <details className="muscle-details">
                <summary className="small">Einzelne Muskeln{p ? " (Strich = Vorzeitraum)" : ""}</summary>
                <div className="group-bars small">
                  {sum.muscles.map((x) => (
                    <div key={x.muscle} className="group-bar" style={{ "--c": GROUP_COLORS[x.group] || "var(--iris)" }}>
                      <span>{x.label}</span>
                      <div className="track">
                        <div className="fill" style={{ width: `${(x.sets / maxMuscle) * 100}%` }} />
                        {p && x.previous ? <div className="ghost" style={{ left: `${(x.previous / maxMuscle) * 100}%` }} /> : null}
                      </div>
                      <span className="num">{fmtNum(x.sets, x.sets % 1 ? 1 : 0)}</span>
                    </div>
                  ))}
                </div>
              </details>
            </>
          ) : <p className="muted">Im Zeitraum kein Training.</p>}
        </section>
      </div>
      <div className="grid-2">
        <section className="panel">
          <div className="panel-head"><h2>Kalender</h2><span className="tiny muted">{fmtNum(sum.all_time.workouts)} Trainings insgesamt</span></div>
          <Calendar data={sum.days} end={todayIso()} days={182} />
        </section>
        <section className="panel">
          <div className="panel-head"><h2>Häufigste Übungen</h2></div>
          {sum.top_exercises.length ? (
            <ol className="top-list">
              {sum.top_exercises.map((x) => (
                <li key={x.exercise_id}><Link className="link" to={`/strength/exercise/${x.exercise_id}`}>{x.name}</Link><span className="muted small">{x.sets} Sätze</span></li>
              ))}
            </ol>
          ) : <p className="muted">Im Zeitraum kein Training.</p>}
        </section>
      </div>
    </>
  );
}

function WeekBars({ weeks, metric, fmt }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const h = 200, pad = { l: 8, r: 8, t: 18, b: 24 };
  const vals = weeks.map((w) => w[metric] || 0);
  const max = Math.max(1, ...vals);
  const n = weeks.length;
  const slot = (width - pad.l - pad.r) / n;
  const bw = Math.max(3, slot * 0.66);
  const y = (v) => pad.t + (h - pad.t - pad.b) * (1 - v / max);
  const every = Math.ceil(n / Math.max(2, Math.floor(width / 70)));
  return (
    <div className="chart-wrap" ref={ref}>
      <svg className="chart" width={width} height={h} viewBox={`0 0 ${width} ${h}`} role="img" aria-label="Werte pro Woche" onMouseLeave={() => setHover(null)}>
        {weeks.map((w, i) => {
          const v = w[metric] || 0;
          const x = pad.l + i * slot + (slot - bw) / 2;
          return (
            <g key={w.week} onMouseEnter={() => setHover(i)}>
              <rect x={pad.l + i * slot} y={pad.t} width={slot} height={h - pad.t - pad.b} fill="transparent" />
              <rect className={`chart-bar${hover === i ? "" : i === n - 1 ? "" : " soft"}`} x={x} y={y(v)} width={bw} height={Math.max(0, h - pad.b - y(v))} rx={Math.min(5, bw / 2)}
                style={{ transformOrigin: `0 ${h - pad.b}px`, animation: `grow-y .6s cubic-bezier(.2,.8,.2,1) ${Math.min(i * 15, 400)}ms backwards` }} />
              {i % every === 0 && <text className="chart-axis" x={x + bw / 2} y={h - 6} textAnchor="middle">{fmtDayShort(w.week)}</text>}
            </g>
          );
        })}
      </svg>
      {hover != null && (
        <div className="chart-tip" style={{ left: Math.min(width - 70, Math.max(70, pad.l + hover * slot + slot / 2)), top: y(vals[hover]) }}>
          <strong>{fmt(vals[hover])}</strong> <span className="muted">Woche ab {fmtDayShort(weeks[hover].week)}</span>
        </div>
      )}
    </div>
  );
}

function History({ onChanged }) {
  const ex = useExercises();
  const [items, setItems] = useState(null);
  const [more, setMore] = useState(true);
  async function load(before) {
    const r = await api.get(`/strength/workouts?limit=15${before ? `&before=${encodeURIComponent(before)}` : ""}`);
    setItems((cur) => (before ? [...(cur || []), ...r] : r));
    setMore(r.length === 15);
  }
  useEffect(() => { load().catch(() => setItems([])); }, []);
  async function remove(w) {
    if (!(await confirmDialog(`„${w.name}“ vom ${fmtDate(w.start)} löschen?`))) return;
    await api.del(`/strength/workouts/${w.id}`);
    setItems((cur) => cur.filter((x) => x.id !== w.id));
    onChanged?.();
  }
  if (!items) return <Loading rows={2} />;
  if (!items.length) return null;
  return (
    <section className="panel">
      <div className="panel-head"><h2>Verlauf</h2></div>
      <div className="feed">
        {items.map((w) => (
          <article key={w.id} className="feed-item">
            <div className="feed-head">
              <Link to={`/strength/workout/${w.id}`} className="link"><strong>{w.name}</strong></Link>
              <span className="muted small">{fmtDate(w.start)}{w.source !== "bodybase" ? ` · aus ${w.source === "hevy" ? "Hevy" : "Strong"}` : ""}</span>
              <button className="icon-btn" aria-label="Löschen" onClick={() => remove(w)}>×</button>
            </div>
            <div className="feed-stats">
              <span><small>Dauer</small>{w.duration_s ? fmtClock(w.duration_s) : "–"}</span>
              <span><small>Volumen</small>{fmtVolume(w.volume_kg)}</span>
              <span><small>Sätze</small>{w.sets}</span>
              {w.prs.length ? <span className="pr-badge">🏆 {w.prs.length} {w.prs.length === 1 ? "Rekord" : "Rekorde"}</span> : null}
            </div>
            <ul className="feed-ex">
              {w.exercises.slice(0, 6).map((b, i) => (
                <li key={i}><span>{b.sets} × {b.name}</span><span className="muted">{b.best}</span></li>
              ))}
              {w.exercises.length > 6 && <li className="muted">+ {w.exercises.length - 6} weitere</li>}
            </ul>
          </article>
        ))}
      </div>
      {more && <div className="actions"><button className="btn" onClick={() => load(items[items.length - 1].start)}>Ältere laden</button></div>}
      {!ex && null}
    </section>
  );
}
