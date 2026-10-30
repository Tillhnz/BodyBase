import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtDuration, fmtNum } from "../fmt.js";
import { ZONES, maxHrFor, zoneOf } from "../hr.js";
import { useWidth } from "./charts.jsx";

let mePromise = null;
function useMaxHr() {
  const [max, setMax] = useState(190);
  useEffect(() => {
    mePromise = mePromise || api.get("/me").catch(() => null);
    mePromise.then((u) => u && setMax(maxHrFor(u)));
  }, []);
  return max;
}

const SOURCE_NAMES = { bluetooth: "live per Bluetooth", apple_health: "Apple Health", health_connect: "Health Connect", api: "eigene Skripte" };

/** Pulsverlauf über die Zeit mit Zonenbändern und Markierungen (z. B. abgehakte Sätze). */
export default function HrChart({ series, height = 180 }) {
  const [ref, width] = useWidth();
  const maxHr = useMaxHr();
  const [hover, setHover] = useState(null);
  if (!series?.t?.length) return null;
  const { t, v } = series;
  const pad = { l: 36, r: 10, t: 10, b: 22 };
  const lo = Math.max(40, Math.min(...v) - 8), hi = Math.max(...v, maxHr * 0.75) + 5;
  const t0 = t[0], t1 = Math.max(t[t.length - 1], t0 + 60);
  const X = (x) => pad.l + ((x - t0) / (t1 - t0)) * (width - pad.l - pad.r);
  const Y = (y) => pad.t + (1 - (y - lo) / (hi - lo)) * (height - pad.t - pad.b);
  const d = t.map((x, i) => `${i ? "L" : "M"}${X(x).toFixed(1)},${Y(v[i]).toFixed(1)}`).join("");

  // Zeit in Zonen
  const zoneSecs = ZONES.map(() => 0);
  for (let i = 1; i < t.length; i++) {
    const dt = Math.min(60, t[i] - t[i - 1]);
    const z = zoneOf(v[i], maxHr);
    if (z >= 0) zoneSecs[z] += dt;
  }
  const zoneTotal = zoneSecs.reduce((a, b) => a + b, 0);
  const ticks = [];
  const span = (t1 - t0) / 60;
  const clock = span > 180; // lange Zeiträume: Uhrzeit statt Minuten
  const base = new Date(series.start).getTime();
  const step = clock ? (span > 2000 ? 720 : span > 700 ? 360 : 120) : span > 120 ? 30 : span > 50 ? 15 : span > 20 ? 5 : 2;
  for (let m = Math.ceil(t0 / 60 / step) * step; m * 60 <= t1; m += step) ticks.push(m);
  const tickLabel = (m) => {
    if (!clock) return `${m} min`;
    const d = new Date(base + m * 60000);
    return d.toLocaleString("de-DE", span > 1500 ? { weekday: "short", hour: "2-digit" } : { hour: "2-digit", minute: "2-digit" });
  };

  function move(e) {
    const r = e.currentTarget.getBoundingClientRect();
    const x = t0 + ((e.clientX - r.left - pad.l) / (width - pad.l - pad.r)) * (t1 - t0);
    let best = 0;
    for (let i = 0; i < t.length; i++) if (Math.abs(t[i] - x) < Math.abs(t[best] - x)) best = i;
    setHover(best);
  }

  return (
    <div className="hr-chart" ref={ref}>
      <div className="hr-head small">
        <span><b>Ø {fmtNum(series.avg ?? v.reduce((a, b) => a + b, 0) / v.length)}</b> · max {fmtNum(series.max ?? Math.max(...v))} bpm</span>
        <span className="muted">{hover != null ? `${fmtNum(v[hover])} bpm ${clock ? `um ${new Date(base + t[hover] * 1000).toLocaleString("de-DE", { weekday: "short", hour: "2-digit", minute: "2-digit" })}` : `nach ${fmtDuration(t[hover])}`}` : SOURCE_NAMES[series.source] || series.source || ""}</span>
      </div>
      <svg className="chart" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Pulsverlauf"
        onMouseMove={move} onMouseLeave={() => setHover(null)}
        onTouchMove={(e) => e.touches[0] && move({ currentTarget: e.currentTarget, clientX: e.touches[0].clientX })} onTouchEnd={() => setHover(null)}>
        {ZONES.map((z, i) => {
          const top = i === ZONES.length - 1 ? hi : ZONES[i + 1].from * maxHr;
          const bottom = Math.max(lo, z.from * maxHr);
          if (top <= lo || bottom >= hi) return null;
          return <rect key={z.name} x={pad.l} width={width - pad.l - pad.r} y={Y(Math.min(top, hi))} height={Math.max(0, Y(bottom) - Y(Math.min(top, hi)))}
            fill={z.color} opacity="0.07" />;
        })}
        {[...new Set([Math.ceil(lo / 20) * 20, Math.round((lo + hi) / 40) * 20, Math.floor(hi / 20) * 20])].filter((y) => y > lo && y < hi).map((y) => (
          <g key={y}><line className="chart-grid" x1={pad.l} x2={width - pad.r} y1={Y(y)} y2={Y(y)} /><text className="chart-axis" x={pad.l - 6} y={Y(y) + 4} textAnchor="end">{y}</text></g>
        ))}
        {ticks.map((m) => <text key={m} className="chart-axis" x={X(m * 60)} y={height - 5} textAnchor="middle">{tickLabel(m)}</text>)}
        {(series.marks || []).map(([mt, label], i) => (
          <line key={i} x1={X(mt)} x2={X(mt)} y1={height - pad.b - 6} y2={height - pad.b} className="hr-mark"><title>{label}</title></line>
        ))}
        <path d={d} fill="none" stroke="var(--c-heart)" strokeWidth="2" strokeLinejoin="round" />
        {hover != null && <circle cx={X(t[hover])} cy={Y(v[hover])} r="4" fill="var(--c-heart)" stroke="var(--panel)" strokeWidth="2" />}
      </svg>
      {zoneTotal > 0 && (
        <div className="hr-zones">
          <div className="hr-zone-bar">{zoneSecs.map((s, i) => s > 0 && <i key={i} style={{ width: `${(s / zoneTotal) * 100}%`, background: ZONES[i].color }} />)}</div>
          <div className="hr-zone-legend">{zoneSecs.map((s, i) => s > 0 && <span key={i}><b style={{ background: ZONES[i].color }} />{ZONES[i].name} {fmtDuration(s)}</span>)}
            <span className="muted">max. HF {maxHr} (Einstellungen: Geburtsjahr)</span></div>
        </div>
      )}
    </div>
  );
}
