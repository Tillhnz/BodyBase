import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { fmtDuration, fmtNum, fmtTime } from "../fmt.js";
import { toast } from "./feedback.jsx";
import HrChart from "./HrChart.jsx";

const ZONE_COLORS = ["var(--mute)", "var(--c-body)", "var(--c-recovery)", "var(--c-nutrition)", "var(--c-activity)", "var(--c-heart)"];
const ZONE_LABELS = ["Zone 0", "Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5"];

function HrZones({ zones }) {
  const total = zones.reduce((a, b) => a + b, 0);
  if (!total) return null;
  return (
    <div className="hr-zones">
      <div className="hr-zone-bar">
        {zones.map((z, i) => z > 0 && <i key={i} style={{ width: `${(z / total) * 100}%`, background: ZONE_COLORS[i] }} title={`${ZONE_LABELS[i]}: ${fmtDuration(z)}`} />)}
      </div>
      <div className="hr-zone-legend">
        {zones.map((z, i) => z > 0 && <span key={i}><b style={{ background: ZONE_COLORS[i] }} />{ZONE_LABELS[i]} {fmtDuration(z)}</span>)}
      </div>
    </div>
  );
}

/**
 * Daten aus anderen Quellen zu einer Einheit: Puls, Kalorien, Belastung, Herzfrequenzzonen.
 * Verknüpfungen lassen sich lösen, Vorschläge (zeitgleiche Einheiten) mit einem Klick verknüpfen.
 */
export default function Linked({ activityId, initial, title = "Verknüpfte Daten", onChange }) {
  const [d, setD] = useState(initial || null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (initial) { setD(initial); return; }
    if (activityId) api.get(`/activities/${activityId}/linked`).then(setD).catch(() => {});
  }, [activityId, initial]);
  if (!d) return null;

  async function act(path, body) {
    setBusy(true);
    try {
      const next = await api.post(path, body);
      setD(next);
      onChange?.(next);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }
  const others = d.sources.filter((s) => !s.primary);
  const from = (k) => (d.filled_from?.[k] ? <span className="tiny muted">von {d.filled_from[k]}</span> : null);
  const hasData = d.avg_hr || d.calories || d.load || d.hr_zones || d.hr;

  return (
    <section className="panel linked">
      <div className="panel-head">
        <h2>{title}</h2>
        <span className="tiny muted">{d.sources.length > 1 ? `${d.sources.length} Quellen zusammengeführt` : "nur diese Quelle"}</span>
      </div>
      {hasData ? (
        <div className="linked-kpis">
          {d.avg_hr ? <div><b>{fmtNum(d.avg_hr)}</b><small>Ø Puls bpm</small>{from("avg_hr")}</div> : null}
          {d.max_hr ? <div><b>{fmtNum(d.max_hr)}</b><small>max. Puls</small>{from("max_hr")}</div> : null}
          {d.calories ? <div><b>{fmtNum(d.calories)}</b><small>kcal</small>{from("calories")}</div> : null}
          {d.load ? <div><b>{fmtNum(d.load, d.load < 25 ? 1 : 0)}</b><small>Belastung / Strain</small>{from("load")}</div> : null}
        </div>
      ) : <p className="muted small">Noch keine Puls- oder Kaloriendaten. Trägst du dabei eine Uhr oder WHOOP, verknüpft BodyBase die Einheit automatisch, sobald sie dort ankommt.</p>}
      {d.hr && <HrChart series={d.hr} />}
      {d.hr_zones && <><div className="tiny muted" style={{ marginTop: "0.6rem" }}>Zonen laut {d.filled_from?.hr_zones || "Quelle"}</div><HrZones zones={d.hr_zones} /></>}

      {others.length > 0 && (
        <div className="linked-list">
          {d.sources.map((s) => (
            <div key={s.id} className="version-row">
              <span><strong>{s.source_name}</strong>{s.primary && <span className="pill iris" style={{ marginLeft: "0.5rem" }}>zählt</span>}
                {s.manual && <span className="pill" style={{ marginLeft: "0.4rem" }}>von Hand</span>}</span>
              <span className="muted small">{fmtTime(s.start)} · {fmtDuration(s.duration_s)}{s.avg_hr ? ` · ${fmtNum(s.avg_hr)} bpm` : ""}{s.load ? ` · Strain ${fmtNum(s.load, 1)}` : ""}</span>
              <span className="row-actions">
                <Link className="link quiet small" to={`/activities/${s.id}`}>Ansehen</Link>
                <button className="link quiet small" disabled={busy} onClick={() => act(`/activities/${s.id}/unlink`)}>Lösen</button>
              </span>
            </div>
          ))}
        </div>
      )}

      {d.candidates?.length > 0 && (
        <details className="linked-cands" open={!others.length && d.candidates.some((c) => c.overlap > 0.3)}>
          <summary className="small">Zur gleichen Zeit ({d.candidates.length}) – gehört etwas dazu?</summary>
          {d.candidates.map((c) => (
            <div key={c.id} className="version-row">
              <span><strong>{c.source_name}</strong> <span className="muted">{c.name || c.sport}</span></span>
              <span className="muted small">{fmtTime(c.start)} · {fmtDuration(c.duration_s)}{c.avg_hr ? ` · ${fmtNum(c.avg_hr)} bpm` : ""}{c.overlap ? ` · ${Math.round(c.overlap * 100)} % gleichzeitig` : ""}</span>
              <button className="btn small" disabled={busy} onClick={() => act(`/activities/${c.id}/link`, { target_id: d.activity_id })}>Verknüpfen</button>
            </div>
          ))}
        </details>
      )}
    </section>
  );
}
