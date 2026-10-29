import { useEffect, useState } from "react";
import { api } from "./api.js";

// Metriken, Kategorien und Sportarten vom Server; einmal laden und teilen.
let cache = null;
let pending = null;
const listeners = new Set();

export function loadMeta() {
  if (cache) return Promise.resolve(cache);
  if (!pending) {
    pending = api.get("/meta").then((m) => {
      m.byKey = Object.fromEntries(m.metrics.map((x) => [x.key, x]));
      cache = m;
      listeners.forEach((fn) => fn(m));
      return m;
    }).finally(() => { pending = null; });
  }
  return pending;
}

export function resetMeta() { cache = null; }

export function useMeta() {
  const [meta, setMeta] = useState(cache);
  useEffect(() => {
    if (!cache) loadMeta().then(setMeta).catch(() => {});
    listeners.add(setMeta);
    return () => listeners.delete(setMeta);
  }, []);
  return meta;
}

export const CATEGORY_ORDER = ["body", "heart", "recovery", "activity", "sleep", "nutrition", "metabolic"];
