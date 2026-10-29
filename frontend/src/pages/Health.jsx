import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import EntryDialog from "../components/EntryDialog.jsx";
import { Loading } from "../components/feedback.jsx";
import { EmptyState, MetricCard, useAsync } from "../components/ui.jsx";
import { CATEGORY_ORDER, useMeta } from "../meta.js";

const INTRO = {
  body: "Gewicht und Körperzusammensetzung von Waage, Apps und eigenen Eingaben.",
  heart: "Ruhepuls, HRV, Blutdruck, Sauerstoff und Fitnesswerte.",
  recovery: "Wie gut du dich erholst: Bereitschaft, Recovery, Body Battery, Stress.",
  activity: "Alltagsbewegung: Schritte, aktive Minuten und Kalorien.",
  sleep: "Dauer, Phasen und Qualität deines Schlafs als Tageswerte.",
  nutrition: "Was du isst und trinkst, aus Ernährungs-Apps oder eigenen Eingaben.",
  metabolic: "Blutzucker aus CGM-Sensoren (Dexcom, Nightscout) oder Messgeräten.",
};

export default function Health() {
  const meta = useMeta();
  const [params, setParams] = useSearchParams();
  const cat = params.get("c") || "body";
  const [entry, setEntry] = useState(false);
  const [reload, setReload] = useState(0);
  const [{ data: overview }] = useAsync(() => api.get("/overview"), [reload]);
  const keys = meta ? meta.metrics.filter((m) => m.category === cat && overview?.metrics[m.key]).map((m) => m.key) : [];
  const [{ data: summary, loading }] = useAsync(() => (keys.length ? api.get(`/summary?keys=${keys.join(",")}&days=30`) : Promise.resolve([])),
    [keys.join(","), reload]);
  if (!meta || !overview) return <Loading rows={2} />;
  const missing = meta.metrics.filter((m) => m.category === cat && !overview.metrics[m.key]);
  const counts = Object.fromEntries(CATEGORY_ORDER.map((c) => [c, meta.metrics.filter((m) => m.category === c && overview.metrics[m.key]).length]));
  return (
    <>
      <div className="page-head">
        <div><h1>Gesundheit</h1><p>{INTRO[cat]}</p></div>
        <div className="actions">
          <Link className="btn" to="/trends">Vergleichen</Link>
          <button className="btn primary" onClick={() => setEntry(true)}>Wert eintragen</button>
        </div>
      </div>
      <div className="tabs" role="tablist">
        {CATEGORY_ORDER.map((c) => (
          <button key={c} role="tab" aria-selected={c === cat} className={`tab cat-${c}${c === cat ? " on" : ""}`} onClick={() => setParams({ c })}>
            <span className="dot" />{meta.categories[c]}{counts[c] ? <span className="muted tiny">{counts[c]}</span> : null}
          </button>
        ))}
      </div>
      {loading && !summary ? <Loading rows={1} /> : keys.length ? (
        <div className="metric-grid">
          {(summary || []).map((item) => <MetricCard key={item.key} item={item} to={`/metric/${item.key}`} />)}
        </div>
      ) : (
        <EmptyState title={`Noch keine Werte für ${meta.categories[cat]}`} text="Verbinde eine passende Quelle oder trage Werte selbst ein.">
          <Link className="btn" to="/sources">Quellen</Link>
          <button className="btn primary" onClick={() => setEntry(true)}>Wert eintragen</button>
        </EmptyState>
      )}
      {missing.length > 0 && keys.length > 0 && (
        <p className="muted small" style={{ marginTop: "1.5rem" }}>
          Ohne Daten: {missing.map((m, i) => <span key={m.key}>{i ? ", " : ""}<Link className="link quiet" to={`/metric/${m.key}`}>{m.label}</Link></span>)}
        </p>
      )}
      {entry && <EntryDialog metric={missing.concat(meta.metrics.filter((m) => m.category === cat))[0]?.key} onClose={() => setEntry(false)}
        onSaved={() => setReload((n) => n + 1)} />}
    </>
  );
}
