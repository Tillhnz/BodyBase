import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { confirmDialog, Loading, toast } from "../components/feedback.jsx";
import { EmptyState, Modal } from "../components/ui.jsx";
import { connectHr, disconnectHr, hrState, hrSupported, hrUnsupportedReason, reconnectKnownHr, subscribeHr, ZONES, zoneOf } from "../hr.js";
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
