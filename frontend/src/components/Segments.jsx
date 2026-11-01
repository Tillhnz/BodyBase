import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtDate, fmtNum } from "../fmt.js";
import { Sparkline } from "./charts.jsx";
import { toast } from "./feedback.jsx";
import { Segmented } from "./ui.jsx";

const RANGES = [{ value: 30, label: "30 Tage" }, { value: 90, label: "90 Tage" }, { value: 180, label: "6 Monate" }, { value: 365, label: "1 Jahr" }];

function Change({ v, unit = "kg", invert = false }) {
  if (v == null) return <span className="muted">–</span>;
  const good = invert ? v < 0 : v > 0;
  const cls = Math.abs(v) < 0.05 ? "flat" : good ? "good" : "bad";
  return <span className={`delta ${cls}`}>{v > 0 ? "+" : ""}{fmtNum(v, 1)} {unit}</span>;
}

/** Muskel- und Fettmasse je Körpersegment (Withings Body Scan / Body Segment) im Vergleich zum Training. */
export default function Segments() {
  const [days, setDays] = useState(90);
  const [data, setData] = useState(null);
  const [mapping, setMapping] = useState(false);
  useEffect(() => { api.get(`/body-segments?days=${days}`).then(setData).catch(() => setData({ has_data: false })); }, [days]);
  if (!data?.has_data) return null;

  async function relabel(pos, part) {
    const labels = Object.fromEntries(data.segments.map((s) => [String(s.position), s.part]));
    labels[String(pos)] = part;
    try {
      await api.put("/body-segments/labels", { labels });
      setData(await api.get(`/body-segments?days=${days}`));
    } catch (e) { toast(e.message, "error"); }
  }
  async function reset() {
    await api.put("/body-segments/labels", { labels: {} });
    setData(await api.get(`/body-segments?days=${days}`));
  }

  return (
    <section className="panel cat-body segments">
      <div className="panel-head">
        <h2>Muskelverteilung</h2>
        <Segmented value={days} onChange={setDays} options={RANGES} label="Zeitraum" />
      </div>
      <p className="small muted" style={{ marginTop: 0 }}>Muskel- und Fettmasse je Körperbereich von deiner Waage, verglichen mit dem Training in diesem Zeitraum (Krafttraining, Ausdauer, Gewohnheiten).</p>
      <div className="region-grid">
        {data.regions.map((r) => (
          <div key={r.region} className="region-card">
            <div className="region-top"><strong>{r.region}</strong><span className="muted small">{fmtNum(r.muscle_kg, 1)} kg Muskeln</span></div>
            <div className="region-nums">
              <span><b><Change v={r.change_kg} /></b><small>{r.change_pct != null ? `${r.change_pct > 0 ? "+" : ""}${fmtNum(r.change_pct, 1)} %` : "Veränderung"}</small></span>
              <span><b>{fmtNum(r.load)}</b><small>Trainingspunkte</small></span>
            </div>
            <p className="small">{r.comment}</p>
          </div>
        ))}
      </div>
      <div className="table-wrap" style={{ marginTop: "1rem" }}>
        <table className="table compact">
          <thead><tr><th>Bereich</th><th className="num">Muskeln</th><th className="num">Δ</th><th>Verlauf</th><th className="num">Fett</th><th className="num">Δ</th></tr></thead>
          <tbody>{data.segments.filter((s) => s.part !== "ignore").map((s) => (
            <tr key={s.position}>
              <td>{s.label}</td>
              <td className="num">{s.muscle ? `${fmtNum(s.muscle.last, 1)} kg` : "–"}</td>
              <td className="num"><Change v={s.muscle?.change} /></td>
              <td style={{ width: 120, "--c": "var(--c-body)" }}>{s.muscle?.series?.length > 1 && <Sparkline data={s.muscle.series} height={28} />}</td>
              <td className="num">{s.fat ? `${fmtNum(s.fat.last, 1)} kg` : "–"}</td>
              <td className="num"><Change v={s.fat?.change} invert /></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <p className="hint">{data.measurements} Messungen, zuletzt {fmtDate(data.segments[0]?.muscle?.last_day || data.segments[0]?.fat?.last_day)}.
        {" "}<button className="link quiet small" onClick={() => setMapping(!mapping)}>{mapping ? "Zuordnung schließen" : "Zuordnung der Bereiche"}</button></p>
      {mapping && (
        <div className="segment-map">
          <p className="small">Withings meldet die Bereiche als Nummer (2 rechter Arm, 3 linker Arm, 10 linkes Bein, 11 rechtes Bein, 12 Rumpf). Sollte etwas nicht zur Withings-App passen, kannst du es hier ändern:</p>
          {data.segments.map((s) => (
            <label key={s.position} className="segment-row">
              <span>Code {s.position} · {s.muscle ? `${fmtNum(s.muscle.last, 2)} kg Muskeln` : s.fat ? `${fmtNum(s.fat.last, 2)} kg Fett` : ""}</span>
              <select value={s.part} onChange={(e) => relabel(s.position, e.target.value)}>
                {Object.entries(data.parts).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
          ))}
          {data.custom_labels && <button className="btn small" onClick={reset}>Automatische Zuordnung</button>}
        </div>
      )}
    </section>
  );
}
