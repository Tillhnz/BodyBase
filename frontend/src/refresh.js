import { useEffect, useState } from "react";
import { api } from "./api.js";

/* Beim Laden der Seite (auch nach „Aktualisieren“ im Browser) alle abgefragten Quellen abgleichen.
   Seiten mit useDataVersion() laden ihre Daten neu, sobald die Abgleiche fertig sind. */

let state = { phase: "idle", running: [], errors: [] };
let version = 0;
const listeners = new Set();
let started = false;

function emit(next) {
  state = { ...state, ...next };
  listeners.forEach((fn) => fn());
}

export function startRefresh() {
  if (started) return;
  started = true;
  api.post("/sync/refresh").then(async (r) => {
    if (!r.started?.length) { emit({ phase: "idle" }); return; }
    emit({ phase: "running", running: r.started });
    const until = Date.now() + 4 * 60 * 1000;
    let lastCount = r.started.length;
    while (Date.now() < until) {
      await new Promise((res) => setTimeout(res, 2500));
      let s;
      try { s = await api.get("/sync/status"); } catch { break; }
      // jede fertige Quelle sofort zeigen, nicht erst wenn alle durch sind
      if (s.running.length < lastCount) { version += 1; lastCount = s.running.length; }
      emit({ running: s.running, errors: s.errors });
      if (!s.running.length) break;
    }
    version += 1;
    emit({ phase: "done", running: [] });
    setTimeout(() => emit({ phase: "idle" }), 3500);
  }).catch(() => emit({ phase: "idle" }));
}

export function useRefreshState() {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((n) => n + 1);
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, []);
  return state;
}

/** Zähler, der steigt, wenn neue Daten von den Quellen da sind: in die Abhängigkeiten von useAsync aufnehmen. */
export function useDataVersion() {
  useRefreshState();
  return version;
}
