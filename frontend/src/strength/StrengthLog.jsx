import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { confirmDialog, Loading, toast } from "../components/feedback.jsx";
import { EmptyState, Modal } from "../components/ui.jsx";
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

  function change(next) {
    const value = typeof next === "function" ? next(w) : next;
    const stamped = { ...value, saved_at: Date.now() };
    setW(stamped);
    writeLocalActive(stamped);
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => api.put("/strength/active", stamped).catch(() => {}), 1200);
  }
  useEffect(() => () => clearTimeout(saveTimer.current), []);

  // Werte vom letzten Mal
  const ids = useMemo(() => [...new Set((w?.exercises || []).map((b) => b.exercise_id))].sort().join(","), [w]);
  useEffect(() => {
    if (!ids) return;
    api.post("/strength/previous", { ids: ids.split(",").map(Number), before: w?.start }).then(setPrevious).catch(() => {});
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
    if (s > 0) change((cur) => ({ ...cur, rest: { end: Date.now() + s * 1000, total: s } }));
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
          </div>
        </div>
        <div className="actions" style={{ margin: 0 }}>
          <button className="btn danger" onClick={discard}>Verwerfen</button>
          <button className="btn primary" onClick={() => setFinishing(true)}>Beenden</button>
        </div>
      </div>

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

      {finishing && <FinishDialog w={w} stats={stats} elapsed={elapsed} onClose={() => setFinishing(false)}
        onSaved={(saved) => {
          writeLocalActive(null);
          clearTimeout(saveTimer.current);
          loadExercises(true);
          navigate(`/strength/workout/${saved.id}?neu=1`);
        }} />}
    </div>
  );
}

function FinishDialog({ w, stats, elapsed, onClose, onSaved }) {
  const [name, setName] = useState(w.name || "Training");
  const [notes, setNotes] = useState(w.notes || "");
  const [busy, setBusy] = useState(false);
  const undone = w.exercises.reduce((n, b) => n + b.sets.filter((s) => !s.done && (parseNum(s.kg) != null || parseNum(s.reps) != null || parseClock(s.duration_s))).length, 0);
  const [keepUndone, setKeepUndone] = useState(false);
  const [duration, setDuration] = useState(Math.round(elapsed / 60));

  async function save() {
    setBusy(true);
    try {
      const start = new Date(w.start);
      const body = {
        name, notes, start: w.start, routine_id: w.routine_id,
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
        {w.rest ? <p className="hint">Laufende Pause ({fmtRest(w.rest.total)}) wird beendet.</p> : null}
        <div className="actions">
          <button className="btn primary" onClick={save} disabled={busy}>{busy ? "Speichere …" : "Speichern"}</button>
          <button className="btn" onClick={onClose}>Weiter trainieren</button>
        </div>
      </div>
    </Modal>
  );
}
