import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { fmtDuration, fmtKm, fmtNum, fmtTime } from "../fmt.js";
import { useDataVersion } from "../refresh.js";
import { SportIcon } from "./ui.jsx";

/* Kurzer Hinweis nach neuen Aktivitäten (ohne Gehen) und wenn sich die FTP ändert. */

function stats(a) {
  const out = [];
  if (a.duration_s) out.push([fmtDuration(a.duration_s), "Dauer"]);
  if (a.distance_m >= 100) out.push([`${fmtKm(a.distance_m)} km`, "Strecke"]);
  if (a.avg_power) out.push([`${fmtNum(a.avg_power)} W`, "Leistung"]);
  else if (a.elevation_m >= 50) out.push([`${fmtNum(a.elevation_m)} m`, "Höhe"]);
  if (a.avg_hr) out.push([`${fmtNum(a.avg_hr)}`, "Ø Puls"]);
  if (a.load != null) out.push([fmtNum(a.load), "Auslastung"]);
  return out.slice(0, 4);
}

export default function Notices() {
  const v = useDataVersion();
  const [data, setData] = useState(null);
  useEffect(() => {
    api.get("/notices").then((d) => { if (d.activities.length || d.ftp) setData(d); }).catch(() => {});
  }, [v]);
  if (!data) return null;
  const acts = data.activities.slice(0, 3);
  function close() {
    api.post("/notices/seen", { activity_id: data.max_id, ftp: data.ftp ? data.ftp.new : null }).catch(() => {});
    setData(null);
  }
  const f = data.ftp;
  return (
    <div className="notice-back" onClick={(e) => e.target === e.currentTarget && close()}>
      <div className="notice" role="dialog" aria-label="Neu seit deinem letzten Besuch">
        {f && (
          <div className="notice-ftp">
            <span className="rp-k">{f.old == null ? "Deine FTP" : f.new > f.old ? "FTP gestiegen" : "FTP gesunken"}</span>
            <strong>{f.new} W {f.old != null && <small className={f.new > f.old ? "up" : "down"}>{f.new > f.old ? "+" : "−"}{Math.abs(f.new - f.old)}</small>}</strong>
            <span className="muted small">{[f.wkg && `${fmtNum(f.wkg, 2)} W/kg`, f.vo2max && `VO₂max ≈ ${fmtNum(f.vo2max, 0)}`].filter(Boolean).join(" · ")}</span>
          </div>
        )}
        {acts.map((a) => (
          <Link key={a.id} to={`/activities/${a.id}`} className="notice-act" onClick={close}>
            <div className="notice-title"><SportIcon sport={a.sport} /><div><strong>{a.name}</strong><span className="muted small">{a.sport_label} · {fmtTime(a.start)}</span></div></div>
            <div className="notice-stats">{stats(a).map(([val, l]) => <div key={l}><b>{val}</b><small>{l}</small></div>)}</div>
          </Link>
        ))}
        {data.activities.length > 3 && <p className="muted small" style={{ margin: 0 }}>und {data.activities.length - 3} weitere</p>}
        <button type="button" className="btn primary" onClick={close}>Super</button>
      </div>
    </div>
  );
}
