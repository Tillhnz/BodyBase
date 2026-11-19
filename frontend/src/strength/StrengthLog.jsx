import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { confirmDialog, Loading, toast } from "../components/feedback.jsx";
import { EmptyState, Modal } from "../components/ui.jsx";
import { connectHr, disconnectHr, hrState, hrSupported, hrUnsupportedReason, reconnectKnownHr, subscribeHr, ZONES, zoneOf } from "../hr.js";
import BodyMap, { MUSCLE_LABELS } from "../components/BodyMap.jsx";
import BlockEditor from "./BlockEditor.jsx";
import {
  draftStats, fmtClock, fmtRest, fmtVolume, fromDraftBlock, loadExercises, newWorkout, parseClock, parseNum, readLocalActive, restAlarm,
  useExercises, writeLocalActive,
} from "./shared.js";

function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(t); }, [ms]);
  return now;
}

/** Bildschirm bleibt an, solange das Training läuft (wo der Browser es erlaubt). */
function useWakeLock(active) {
  useEffect(() => {
    if (!active || !navigator.wakeLock) return undefined;
    let lock = null;
    const req = () => navigator.wakeLock.request("screen").then((l) => { lock = l; }).catch(() => {});
    req();
    const onVis = () => { if (document.visibilityState === "visible") req(); };
    document.addEventListener("visibilitychange", onVis);
    return () => { document.removeEventListener("visibilitychange", onVis); lock?.release?.().catch(() => {}); };
  }, [active]);
}

export default function StrengthLog() {
  const navigate = useNavigate();
  const ex = useExercises();
  const [w, setW] = useState(undefined); // undefined = lädt, null = keins
  const [previous, setPrevious] = useState({});
  const [finishing, setFinishing] = useState(false);
  const saveTimer = useRef(null);
  const now = useNow();
  useWakeLock(!!w);

  // Laden: Browser-Kopie oder Server, die neuere gewinnt
  useEffect(() => {
    const local = readLocalActive();
    api.get("/strength/active").then((r) => {
      const server = r.data;
      const pick = !local ? server : !server ? local : (server.saved_at || 0) > (local.saved_at || 0) ? server : local;
      setW(pick || null);
      if (pick) writeLocalActive(pick);
    }).catch(() => setW(local || null));
  }, []);

  const wRef = useRef(w);
  wRef.current = w;
  function change(next) {
    const value = typeof next === "function" ? next(wRef.current) : next;
    wRef.current = value;
    const stamped = { ...value, saved_at: Date.now() };
    setW(stamped);
    writeLocalActive(stamped);
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => api.put("/strength/active", stamped).catch(() => {}), 1200);
  }
  useEffect(() => () => clearTimeout(saveTimer.current), []);

  // Live-Puls per Bluetooth: Werte sammeln (höchstens alle 2 s) und alle 15 s ins Training übernehmen
  const hr = useHr();
  const hrBuf = useRef({ t: [], v: [], last: 0 });
  useEffect(() => {
    const cur = wRef.current;
    if (!cur || hr.status !== "connected" || !hr.bpm || hr.at - hrBuf.current.last < 2000) return;
    hrBuf.current.last = hr.at;
    hrBuf.current.t.push(Math.round((hr.at - new Date(cur.start).getTime()) / 1000));
    hrBuf.current.v.push(hr.bpm);
  }, [hr.at]); // eslint-disable-line react-hooks/exhaustive-deps
  function flushHr(cur) {
    const b = hrBuf.current;
    if (!b.t.length) return cur;
    const prev = cur.hr || { start: cur.start, t: [], v: [], marks: [], source: "bluetooth" };
    const next = { ...prev, t: [...prev.t, ...b.t], v: [...prev.v, ...b.v], device: hrState().device || prev.device };
    hrBuf.current = { t: [], v: [], last: b.last };
    return { ...cur, hr: next };
  }
  useEffect(() => {
    const id = setInterval(() => { if (hrBuf.current.t.length && wRef.current) change((cur) => flushHr(cur)); }, 15000);
    return () => clearInterval(id);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (w?.hr) reconnectKnownHr(); }, [!!w]); // eslint-disable-line react-hooks/exhaustive-deps

  // Werte vom letzten Mal
  const ids = useMemo(() => [...new Set((w?.exercises || []).map((b) => b.exercise_id))].sort().join(","), [w]);
  useEffect(() => {
    if (!ids) return;
    api.post("/strength/previous", { ids: ids.split(",").map(Number), before: w?.start }).then((prev) => {
      setPrevious(prev);
      // Werte vom letzten Mal in die noch offenen Sätze übernehmen (einmal je Übung, eigene Eingaben bleiben danach unberührt)
      change((cur) => {
        if (!cur?.exercises?.some((b) => !b.prefilled)) return cur;
        const fetched = new Set(ids.split(","));
        return {
          ...cur,
          exercises: cur.exercises.map((b) => {
            if (b.prefilled || !fetched.has(String(b.exercise_id))) return b;
            const p = prev[String(b.exercise_id)] || [];
            return {
              ...b, prefilled: true,
              sets: b.sets.map((st, i) => {
                const q = p[i];
                if (st.done || !q) return st;
                return {
                  ...st,
                  kg: q.kg != null ? String(q.kg).replace(".", ",") : st.kg,
                  reps: q.reps != null ? String(q.reps) : st.reps,
                  duration_s: q.duration_s != null ? q.duration_s : st.duration_s,
                  distance_m: q.distance_m != null ? String(q.distance_m / 1000).replace(".", ",") : st.distance_m,
                };
              }),
            };
          }),
        };
      });
    }).catch(() => {});
  }, [ids]); // eslint-disable-line react-hooks/exhaustive-deps

  // Pausentimer
  const rest = w?.rest;
  const remaining = rest ? Math.ceil((rest.end - now) / 1000) : null;
  const alarmed = useRef(null);
  useEffect(() => {
    if (rest && remaining <= 0 && alarmed.current !== rest.end) {
      alarmed.current = rest.end;
      restAlarm();
      change((cur) => ({ ...cur, rest: null }));
    }
  }, [remaining]); // eslint-disable-line react-hooks/exhaustive-deps

  if (w === undefined || !ex) return <Loading rows={3} />;
  if (w === null) {
    return (
      <EmptyState title="Kein laufendes Training" text="Starte ein leeres Training oder eine deiner Routinen.">
        <button className="btn primary" onClick={() => change(newWorkout())}>Leeres Training starten</button>
        <Link className="btn" to="/strength">Zu den Routinen</Link>
      </EmptyState>
    );
  }

  const stats = draftStats(w.exercises, ex.byId);
  const elapsed = (now - new Date(w.start).getTime()) / 1000;

  function onSetDone(block) {
    const s = block.rest_s || 0;
    const name = ex.byId.get(block.exercise_id)?.name || "Satz";
    change((cur) => {
      let next = s > 0 ? { ...cur, rest: { end: Date.now() + s * 1000, total: s } } : cur;
      if (hrState().status === "connected" || next.hr) { // Satzende im Pulsverlauf markieren
        next = flushHr(next);
        const base = next.hr || { start: next.start, t: [], v: [], marks: [], source: "bluetooth" };
        const at = Math.round((Date.now() - new Date(next.start).getTime()) / 1000);
        next = { ...next, hr: { ...base, marks: [...(base.marks || []), [at, name]] } };
      }
      return next;
    });
  }
  const shiftRest = (d) => change((cur) => (cur.rest ? { ...cur, rest: { ...cur.rest, end: cur.rest.end + d * 1000, total: Math.max(1, cur.rest.total + d) } } : cur));

  async function discard() {
    if (!(await confirmDialog("Das Training wird verworfen. Eingetragene Sätze gehen verloren.", { confirmLabel: "Verwerfen" }))) return;
    writeLocalActive(null);
    clearTimeout(saveTimer.current);
    await api.del("/strength/active").catch(() => {});
    navigate("/strength");
  }

  return (
    <div className="strength-log">
      <div className="log-head">
        <div className="log-title">
          <input className="log-name" value={w.name} onChange={(e) => change({ ...w, name: e.target.value })} aria-label="Name des Trainings" />
          <div className="log-stats">
            <span><small>Dauer</small>{fmtClock(elapsed)}</span>
            <span><small>Volumen</small>{fmtVolume(stats.volume)}</span>
            <span><small>Sätze</small>{stats.sets}</span>
            <HrBadge hr={hr} />
          </div>
        </div>
        <div className="actions" style={{ margin: 0 }}>
          <button className="btn danger" onClick={discard}>Verwerfen</button>
          <button className="btn primary" onClick={() => { change((cur) => flushHr(cur)); setFinishing(true); }}>Beenden</button>
        </div>
      </div>

      <LiveMuscles blocks={w.exercises} byId={ex.byId} />
      {!w.exercises.length && <p className="muted" style={{ textAlign: "center", margin: "2rem 0 1rem" }}>Füge deine erste Übung hinzu.</p>}
      <BlockEditor blocks={w.exercises} onChange={(blocks) => change((cur) => ({ ...cur, exercises: blocks }))} mode="log"
        byId={ex.byId} meta={ex.meta} previous={previous} onSetDone={onSetDone} />

      {rest && remaining > 0 && (
        <div className="rest-bar" role="timer" aria-live="off">
          <div className="rest-fill" style={{ width: `${Math.max(0, Math.min(100, (remaining / rest.total) * 100))}%` }} />
          <button type="button" className="btn small" onClick={() => shiftRest(-15)}>−15</button>
          <div className="rest-time"><small>Pause</small>{fmtClock(remaining)}</div>
          <button type="button" className="btn small" onClick={() => shiftRest(15)}>+15</button>
          <button type="button" className="btn small primary" onClick={() => change((cur) => ({ ...cur, rest: null }))}>Weiter</button>
        </div>
      )}

      {finishing && <FinishDialog w={w} stats={stats} elapsed={elapsed} byId={ex.byId} onClose={() => setFinishing(false)}
        onSaved={(saved) => {
          writeLocalActive(null);
          clearTimeout(saveTimer.current);
          loadExercises(true);
          navigate(`/strength/workout/${saved.id}?neu=1`);
        }} />}
    </div>
  );
}

function useHr() {
  const [s, setS] = useState(hrState());
  useEffect(() => subscribeHr(setS), []);
  return s;
}

/** Puls im Kopf des Trainings: verbinden, aktueller Wert in Zonenfarbe, Neuverbinden nach Abbruch. */
function HrBadge({ hr }) {
  const [busy, setBusy] = useState(false);
  async function connect() {
    if (!hrSupported()) { toast(hrUnsupportedReason(), "error"); return; }
    setBusy(true);
    try { await connectHr(); } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  if (hr.status === "connected" && hr.bpm) {
    const z = zoneOf(hr.bpm, 190);
    return (
      <button type="button" className="hr-badge live" style={{ "--c": z >= 0 ? ZONES[z].color : "var(--c-heart)" }}
        onClick={async () => { if (await confirmDialog(`Pulsmesser „${hr.device}“ trennen?`, { confirmLabel: "Trennen" })) disconnectHr(); }}
        title={hr.device}>
        <small>Puls</small><span><i className="hr-heart" />{hr.bpm}</span>
      </button>
    );
  }
  const label = hr.status === "connecting" || busy ? "verbinde …" : hr.status === "reconnecting" ? "verbinde neu …" : hr.status === "lost" ? "getrennt" : "verbinden";
  return (
    <button type="button" className="hr-badge" onClick={connect} disabled={busy || hr.status === "connecting"}
      title="WHOOP: in der WHOOP-App „Heart Rate Broadcast“ einschalten. Oder Brustgurt / Uhr im Sendemodus.">
      <small>Puls</small><span>❤ {label}</span>
    </button>
  );
}

function FinishDialog({ w, stats, elapsed, byId, onClose, onSaved }) {
  const [name, setName] = useState(w.name || "Training");
  const [notes, setNotes] = useState(w.notes || "");
  const [busy, setBusy] = useState(false);
  const undone = w.exercises.reduce((n, b) => n + b.sets.filter((s) => !s.done && (parseNum(s.kg) != null || parseNum(s.reps) != null || parseClock(s.duration_s))).length, 0);
  const [keepUndone, setKeepUndone] = useState(false);
  const [duration, setDuration] = useState(Math.round(elapsed / 60));
  const [routine, setRoutine] = useState(null);
  const [routineAction, setRoutineAction] = useState(w.routine_id ? "update" : "none");
  const [routineName, setRoutineName] = useState(w.name || "Neue Routine");
  useEffect(() => {
    if (w.routine_id) api.get(`/strength/routines/${w.routine_id}`).then(setRoutine).catch(() => setRoutine(null));
  }, [w.routine_id]);
  const doneBlocks = w.exercises.filter((b) => b.sets.some((st) => st.done));
  const inRoutine = new Set((routine?.exercises || []).map((e) => e.exercise_id));
  const added = routine ? doneBlocks.filter((b) => !inRoutine.has(b.exercise_id)) : [];
  const askRoutine = (w.routine_id && routine && added.length > 0) || (!w.routine_id && doneBlocks.length > 0);
  const nameOf = (id) => byId?.get(id)?.name || "Übung";

  async function applyRoutine() {
    if (!askRoutine || routineAction === "none") return;
    const block = (b) => {
      const out = fromDraftBlock(b);
      const done = out.sets.filter((st, i) => b.sets[i].done);
      return { ...out, sets: done.length ? done : out.sets };
    };
    if (routineAction === "update" && routine) {
      // bisherige Übungen der Routine behalten (mit ihren Sätzen), neue in der Reihenfolge des Trainings einfügen
      const keep = new Map((routine.exercises || []).map((e) => [e.exercise_id, e]));
      const order = [];
      for (const b of w.exercises) {
        if (keep.has(b.exercise_id)) { order.push(keep.get(b.exercise_id)); keep.delete(b.exercise_id); }
        else if (b.sets.some((st) => st.done)) order.push(block(b));
      }
      order.push(...keep.values()); // im Training ausgelassene Übungen bleiben in der Routine
      await api.put(`/strength/routines/${routine.id}`, { name: routine.name, folder: routine.folder || "", notes: routine.notes || "", exercises: order });
      toast(`Routine „${routine.name}“ aktualisiert`);
    } else if (routineAction === "new") {
      await api.post("/strength/routines", { name: routineName.trim() || "Neue Routine", folder: routine?.folder || "", notes: "", exercises: doneBlocks.map(block) });
      toast(`Neue Routine „${routineName.trim() || "Neue Routine"}“ gespeichert`);
    }
  }

  async function save() {
    setBusy(true);
    try {
      const start = new Date(w.start);
      const body = {
        name, notes, start: w.start, routine_id: w.routine_id, hr: w.hr || null,
        end: new Date(start.getTime() + Math.max(1, duration) * 60000).toISOString(),
        exercises: w.exercises.map((b) => {
          const out = fromDraftBlock(b);
          out.sets = out.sets.filter((s, i) => b.sets[i].done || (keepUndone && (s.kg != null || s.reps != null || s.duration_s)));
          return out;
        }).filter((b) => b.sets.length),
      };
      if (!body.exercises.length) {
        toast("Hake mindestens einen Satz ab.", "error");
        setBusy(false);
        return;
      }
      const saved = await api.post("/strength/workouts", body);
      toast("Training gespeichert");
      try { await applyRoutine(); } catch (err) { toast(`Routine nicht gespeichert: ${err.message}`, "error"); }
      onSaved(saved);
    } catch (err) {
      toast(err.message, "error");
      setBusy(false);
    }
  }

  return (
    <Modal title="Training beenden" onClose={onClose}>
      <div className="stack">
        <div className="log-stats big">
          <span><small>Volumen</small>{fmtVolume(stats.volume)}</span>
          <span><small>Sätze</small>{stats.sets}</span>
          <span><small>Wdh.</small>{stats.reps}</span>
        </div>
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} maxLength={160} /></label>
        <label>Dauer (Minuten)<input inputMode="numeric" value={duration} onChange={(e) => setDuration(Number(e.target.value.replace(/\D/g, "")) || 0)} /></label>
        <label>Notiz<textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Wie lief es?" /></label>
        {undone > 0 && (
          <label className="check"><input type="checkbox" checked={keepUndone} onChange={(e) => setKeepUndone(e.target.checked)} />
            {undone} ausgefüllte, aber nicht abgehakte Sätze trotzdem speichern</label>
        )}
        {askRoutine && (
          <fieldset className="routine-choice">
            <legend>{routine ? `Neue Übungen: ${added.map((b) => nameOf(b.exercise_id)).join(", ")}` : "Als Routine merken?"}</legend>
            {routine && (
              <label className="check"><input type="radio" name="ra" checked={routineAction === "update"} onChange={() => setRoutineAction("update")} />
                In „{routine.name}“ übernehmen</label>
            )}
            <label className="check"><input type="radio" name="ra" checked={routineAction === "new"} onChange={() => setRoutineAction("new")} />
              Als neue Routine speichern</label>
            {routineAction === "new" && <input value={routineName} onChange={(e) => setRoutineName(e.target.value)} maxLength={160} aria-label="Name der neuen Routine" />}
            <label className="check"><input type="radio" name="ra" checked={routineAction === "none"} onChange={() => setRoutineAction("none")} />
              {routine ? "Nur dieses Mal" : "Nein"}</label>
          </fieldset>
        )}
        {w.rest ? <p className="hint">Laufende Pause ({fmtRest(w.rest.total)}) wird beendet.</p> : null}
        <div className="actions">
          <button className="btn primary" onClick={save} disabled={busy}>{busy ? "Speichere …" : "Speichern"}</button>
          <button className="btn" onClick={onClose}>Weiter trainieren</button>
        </div>
      </div>
    </Modal>
  );
}


/** Welche Muskeln im laufenden Training schon dran waren: abgehakte Arbeitssätze, Nebenmuskeln halb. */
function LiveMuscles({ blocks, byId }) {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem("bodybase-live-muscles") === "1"; } catch { return false; } });
  const values = {};
  for (const b of blocks) {
    const e = byId.get(b.exercise_id);
    if (!e) continue;
    const n = b.sets.filter((s) => s.done && s.type !== "warmup").length;
    if (!n) continue;
    if (MUSCLE_LABELS[e.primary]) values[e.primary] = (values[e.primary] || 0) + n;
    for (const m of e.secondary || []) if (MUSCLE_LABELS[m]) values[m] = (values[m] || 0) + n * 0.5;
  }
  const top = Object.entries(values).sort((a, b) => b[1] - a[1]);
  if (!top.length) return null;
  function toggle(e) {
    const v = e.currentTarget.open;
    setOpen(v);
    try { localStorage.setItem("bodybase-live-muscles", v ? "1" : "0"); } catch { /* privat */ }
  }
  return (
    <details className="panel live-muscles" open={open} onToggle={toggle}>
      <summary>
        <strong>Trainierte Muskeln</strong>
        <span className="live-chips">{top.slice(0, 5).map(([m, v]) => <span key={m} className="pill">{MUSCLE_LABELS[m]} {v % 1 ? v.toFixed(1).replace(".", ",") : v}</span>)}</span>
      </summary>
      <BodyMap values={values} unit="Sätze" size="sm" />
    </details>
  );
}
