// Gemeinsame Helfer für das Krafttraining: Übungsliste, Formatierung, laufendes Training.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtNum } from "../fmt.js";

let exCache = null;
let metaCache = null;
const listeners = new Set();

export function loadExercises(force = false) {
  if (!exCache || force) {
    exCache = Promise.all([api.get("/strength/exercises"), metaCache || api.get("/strength/meta")])
      .then(([items, meta]) => {
        metaCache = Promise.resolve(meta);
        const byId = new Map(items.map((e) => [e.id, e]));
        return { items, byId, meta };
      })
      .catch((e) => { exCache = null; throw e; });
    exCache.then((v) => listeners.forEach((fn) => fn(v))).catch(() => {});
  }
  return exCache;
}

/** Übungen und Stammdaten; aktualisiert sich, wenn jemand loadExercises(true) aufruft. */
export function useExercises() {
  const [state, setState] = useState(null);
  useEffect(() => {
    let alive = true;
    const fn = (v) => alive && setState(v);
    listeners.add(fn);
    loadExercises().then(fn).catch(() => {});
    return () => { alive = false; listeners.delete(fn); };
  }, []);
  return state;
}

export const SET_TYPES = [
  { value: "normal", label: "Normal", short: null },
  { value: "warmup", label: "Aufwärmen", short: "W" },
  { value: "failure", label: "Bis Versagen", short: "F" },
  { value: "drop", label: "Dropsatz", short: "D" },
];

export const REST_OPTIONS = [0, 30, 45, 60, 75, 90, 120, 150, 180, 240, 300];

export function fmtRest(s) {
  if (!s) return "Aus";
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")} min`;
}

export function fmtKg(v) {
  if (v == null || v === "") return "–";
  const n = Number(v);
  return fmtNum(n, Math.abs(n % 1) > 0.001 ? (Math.abs((n * 10) % 1) > 0.001 ? 2 : 1) : 0);
}

export function fmtVolume(v) {
  if (!v) return "0 kg";
  if (v >= 10000) return `${fmtNum(v / 1000, 1)} t`;
  return `${fmtNum(v)} kg`;
}

export function fmtClock(s) {
  if (s == null) return "–";
  const t = Math.max(0, Math.round(s));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

/** "1:30" oder "90" → Sekunden */
export function parseClock(text) {
  if (text == null || text === "") return null;
  const t = String(text).trim();
  if (/^\d+$/.test(t)) return Number(t);
  const parts = t.split(":").map((x) => Number(x));
  if (parts.some((x) => Number.isNaN(x))) return null;
  return parts.reduce((acc, x) => acc * 60 + x, 0);
}

export function parseNum(text) {
  if (text == null || text === "") return null;
  const n = Number(String(text).replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

/** Epley, wie im Backend (über 12 Wiederholungen gedeckelt). */
export function e1rm(kg, reps) {
  if (!kg || !reps || kg <= 0 || reps <= 0) return null;
  return reps === 1 ? kg : kg * (1 + Math.min(reps, 12) / 30);
}

export function setVolume(s, kind) {
  if (s.type === "warmup" || !s.kg || !s.reps) return 0;
  return kind === "weight_reps" || kind === "weighted_bw" ? Number(s.kg) * Number(s.reps) : 0;
}

/** Welche Eingabefelder eine Übungsart braucht. */
export function columnsFor(kind) {
  switch (kind) {
    case "bodyweight": return ["reps"];
    case "weighted_bw": return ["kg", "reps"];
    case "assisted_bw": return ["kg", "reps"];
    case "duration": return ["duration_s"];
    case "distance": return ["distance_m", "duration_s"];
    default: return ["kg", "reps"];
  }
}

export const COL_LABEL = { kg: "kg", reps: "Wdh.", duration_s: "Zeit", distance_m: "km" };
export function colLabel(col, kind) {
  if (col === "kg" && kind === "weighted_bw") return "+kg";
  if (col === "kg" && kind === "assisted_bw") return "−kg";
  return COL_LABEL[col];
}

export function setText(s, kind) {
  if (!s) return "";
  const cols = columnsFor(kind);
  if (cols[0] === "duration_s") return fmtClock(s.duration_s);
  if (cols[0] === "distance_m") return `${fmtNum((s.distance_m || 0) / 1000, 2)} km${s.duration_s ? ` · ${fmtClock(s.duration_s)}` : ""}`;
  if (cols.length === 1) return `${s.reps ?? "–"} Wdh.`;
  const sign = kind === "weighted_bw" ? "+" : kind === "assisted_bw" ? "−" : "";
  if (s.kg == null || s.kg === "") return `${s.reps ?? "–"} Wdh.`;
  return `${sign}${fmtKg(s.kg)} kg × ${s.reps ?? "–"}`;
}

let keySeq = 0;
export const newKey = () => `k${Date.now().toString(36)}${(keySeq++).toString(36)}`;

export function emptySet(type = "normal") {
  return { key: newKey(), type, kg: "", reps: "", duration_s: "", distance_m: "", rpe: "", done: false };
}

/** Block aus Routine/Training in den Bearbeitungszustand bringen (Zahlen als Text, eigene Schlüssel). */
export function toDraftBlock(b, { done = false } = {}) {
  return {
    key: newKey(), exercise_id: b.exercise_id, rest_s: b.rest_s ?? 90, notes: b.notes || "", superset: b.superset ?? null,
    sets: (b.sets?.length ? b.sets : [{ type: "normal" }]).map((s) => ({
      key: newKey(), type: s.type || "normal", kg: s.kg ?? "", reps: s.reps ?? "", rpe: s.rpe ?? "",
      duration_s: s.duration_s ?? "", distance_m: s.distance_m != null && s.distance_m !== "" ? s.distance_m / 1000 : "", done,
    })),
  };
}

/** Bearbeitungszustand → API (distance in km eingegeben, gespeichert in m). */
export function fromDraftBlock(b, { onlyDone = false } = {}) {
  return {
    exercise_id: b.exercise_id, rest_s: b.rest_s, notes: b.notes || null, superset: b.superset,
    sets: b.sets.filter((s) => !onlyDone || s.done).map((s) => ({
      type: s.type, kg: parseNum(s.kg), reps: parseNum(s.reps), rpe: parseNum(s.rpe),
      duration_s: typeof s.duration_s === "number" ? s.duration_s : parseClock(s.duration_s),
      distance_m: parseNum(s.distance_m) != null ? parseNum(s.distance_m) * 1000 : null,
    })),
  };
}

export function draftStats(blocks, byId) {
  let volume = 0, sets = 0, reps = 0;
  for (const b of blocks) {
    const kind = byId?.get(b.exercise_id)?.kind || "weight_reps";
    for (const s of b.sets) {
      if (!s.done || s.type === "warmup") continue;
      sets += 1;
      reps += parseNum(s.reps) || 0;
      volume += setVolume({ type: s.type, kg: parseNum(s.kg), reps: parseNum(s.reps) }, kind);
    }
  }
  return { volume, sets, reps };
}

// ---------- Laufendes Training (im Browser und auf dem Server gesichert) ----------

const LOCAL = "bodybase-active-workout";

export function readLocalActive() {
  try { const raw = localStorage.getItem(LOCAL); return raw ? JSON.parse(raw) : null; } catch { return null; }
}
export function writeLocalActive(data) {
  try { if (data) localStorage.setItem(LOCAL, JSON.stringify(data)); else localStorage.removeItem(LOCAL); } catch { /* privat */ }
}

export function newWorkout({ name = "Training", routine = null, blocks = [] } = {}) {
  return { name, routine_id: routine?.id ?? null, notes: "", start: new Date().toISOString(), exercises: blocks, rest: null, saved_at: Date.now() };
}

export async function startWorkout(navigate, opts) {
  const existing = readLocalActive() || (await api.get("/strength/active").catch(() => ({}))).data;
  if (existing && existing.exercises?.length) {
    navigate("/strength/log");
    return false;
  }
  const w = newWorkout(opts);
  writeLocalActive(w);
  api.put("/strength/active", w).catch(() => {});
  navigate("/strength/log");
  return true;
}

export function routineToBlocks(r) {
  return (r.exercises || []).map((ex) => toDraftBlock(ex));
}

/** Kurzer Ton und Vibration am Ende der Pause. */
export function restAlarm() {
  try { navigator.vibrate?.([200, 100, 200]); } catch { /* egal */ }
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    [0, 0.25].forEach((t) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 880;
      g.gain.setValueAtTime(0.0001, ctx.currentTime + t);
      g.gain.exponentialRampToValueAtTime(0.3, ctx.currentTime + t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + t + 0.2);
      o.connect(g).connect(ctx.destination);
      o.start(ctx.currentTime + t);
      o.stop(ctx.currentTime + t + 0.22);
    });
    setTimeout(() => ctx.close(), 800);
  } catch { /* kein Ton möglich */ }
}

export const GROUP_COLORS = {
  Brust: "var(--c-heart)", Rücken: "var(--c-body)", Schultern: "var(--c-activity)", Arme: "var(--c-sleep)",
  Beine: "var(--c-recovery)", Rumpf: "var(--c-nutrition)", Ausdauer: "var(--c-metabolic)", Ganzkörper: "var(--iris)", Sonstiges: "var(--mute)",
};
