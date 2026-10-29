import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { fmtDay, fmtDayShort, fmtNum, parseDay } from "../fmt.js";

/* Eigene SVG-Diagramme ohne Bibliothek: Linie mit Fläche, Balken, Sparkline, Ringe, Kalender, Belastung, Strecke.
   Farben kommen aus der CSS-Variable --c (Kategorie) des umgebenden Elements. */

export function useWidth(initial = 640) {
  const ref = useRef(null);
  const [width, setWidth] = useState(initial);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    setWidth(el.clientWidth || initial);
    if (!("ResizeObserver" in window)) return undefined;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0].contentRect.width);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [initial]);
  return [ref, width];
}

function niceTicks(min, max, count = 4) {
  if (min === max) {
    const pad = Math.abs(min) * 0.05 || 1;
    min -= pad;
    max += pad;
  }
  const span = max - min;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || step0;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return { lo, hi, ticks, step };
}

const dayMs = 86400000;
const toT = (iso) => parseDay(iso).getTime();

function rolling(points, window = 7) {
  return points.map((p, i) => {
    const t = toT(p.day);
    const near = points.filter((q, j) => j <= i && t - toT(q.day) < window * dayMs);
    return { day: p.day, value: near.reduce((s, q) => s + q.value, 0) / near.length };
  });
}

function dateTicks(t0, t1, width) {
  const days = (t1 - t0) / dayMs;
  const maxTicks = Math.max(2, Math.floor(width / 90));
  const out = [];
  if (days > 400) {
    const d = new Date(t0); d.setDate(1); d.setMonth(Math.floor(d.getMonth() / 3) * 3 + 3);
    while (d.getTime() <= t1) { out.push(d.getTime()); d.setMonth(d.getMonth() + 3); }
  } else if (days > 70) {
    const d = new Date(t0); d.setDate(1); d.setMonth(d.getMonth() + 1);
    while (d.getTime() <= t1) { out.push(d.getTime()); d.setMonth(d.getMonth() + 1); }
  } else {
    const step = Math.max(1, Math.ceil(days / maxTicks));
    for (let t = t0; t <= t1; t += step * dayMs) out.push(t);
  }
  const keep = Math.ceil(out.length / maxTicks);
  return out.filter((_, i) => i % keep === 0);
}

const monthFmt = new Intl.DateTimeFormat("de-DE", { month: "short" });
const monthYearFmt = new Intl.DateTimeFormat("de-DE", { month: "short", year: "2-digit" });

/** Verlauf einer Messgröße. smooth: Rohwerte als Punkte, 7-Tage-Mittel als Linie (z. B. Gewicht). */
export function LineChart({ data, height = 240, goal, format = (v) => fmtNum(v), smooth = false, compare, zero = false, label }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const pad = { l: 44, r: 14, t: 14, b: 26 };
  const pts = (data || []).filter((p) => p.value != null);
  const geo = useMemo(() => {
    if (!pts.length) return null;
    const t0 = toT(pts[0].day);
    const t1 = Math.max(toT(pts[pts.length - 1].day), t0 + dayMs);
    let vals = pts.map((p) => p.value);
    if (compare?.length) vals = vals.concat(compare.map((p) => p.value));
    if (goal != null) vals.push(goal);
    let min = Math.min(...vals), max = Math.max(...vals);
    if (zero) min = Math.min(0, min);
    const { lo, hi, ticks } = niceTicks(min, max, height > 180 ? 4 : 3);
    const w = Math.max(10, width - pad.l - pad.r), h = height - pad.t - pad.b;
    const x = (iso) => pad.l + ((toT(iso) - t0) / (t1 - t0)) * w;
    const y = (v) => pad.t + h - ((v - lo) / (hi - lo || 1)) * h;
    return { t0, t1, lo, hi, ticks, x, y, w, h };
  }, [data, compare, goal, width, height, zero]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!geo) return <div ref={ref} className="muted small" style={{ height, display: "grid", placeItems: "center" }}>Keine Werte im Zeitraum</div>;
  const { x, y, ticks } = geo;
  const line = smooth && pts.length > 7 ? rolling(pts) : pts;
  const path = line.map((p, i) => `${i ? "L" : "M"}${x(p.day).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
  const base = y(Math.max(geo.lo, Math.min(geo.hi, zero ? 0 : geo.lo)));
  const area = `${path}L${x(line[line.length - 1].day).toFixed(1)},${base}L${x(line[0].day).toFixed(1)},${base}Z`;
  const cmpPath = compare?.length ? compare.map((p, i) => `${i ? "L" : "M"}${x(p.day).toFixed(1)},${y(p.value).toFixed(1)}`).join("") : null;
  const last = pts[pts.length - 1];
  const showDots = smooth || pts.length <= 45;

  function onMove(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * width;
    let best = null, dist = Infinity;
    for (const p of pts) {
      const d = Math.abs(x(p.day) - px);
      if (d < dist) { dist = d; best = p; }
    }
    setHover(best);
  }
  const avgAt = hover && smooth ? line.find((p) => p.day === hover.day) : null;
  return (
    <div className="chart-wrap" ref={ref}>
      <svg className="chart" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label || "Verlauf"}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)} onTouchStart={(e) => onMove(e.touches[0] ? { ...e, clientX: e.touches[0].clientX, currentTarget: e.currentTarget } : e)}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="chart-grid" x1={44} x2={width - 14} y1={y(t)} y2={y(t)} />
            <text className="chart-axis" x={38} y={y(t) + 4} textAnchor="end">{format(t)}</text>
          </g>
        ))}
        {dateTicks(geo.t0, geo.t1, width).map((t) => {
          const d = new Date(t);
          const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
          const days = (geo.t1 - geo.t0) / dayMs;
          return <text key={t} className="chart-axis" x={x(iso)} y={height - 6} textAnchor="middle">
            {days > 400 ? monthYearFmt.format(d) : days > 70 ? monthFmt.format(d) : fmtDayShort(iso)}</text>;
        })}
        {goal != null && (
          <g>
            <line className="chart-goal" x1={44} x2={width - 14} y1={y(goal)} y2={y(goal)} />
            <text className="chart-goal-label" x={width - 16} y={y(goal) - 5} textAnchor="end">Ziel {format(goal)}</text>
          </g>
        )}
        <path className="chart-area" d={area} />
        {cmpPath && <path className="chart-line alt thin" d={cmpPath} />}
        {smooth && pts.length > 7 && pts.map((p) => <circle key={p.day} cx={x(p.day)} cy={y(p.value)} r={2} fill="var(--c, var(--iris))" opacity="0.45" />)}
        <path className="chart-line draw" pathLength="1" d={path} />
        {!smooth && showDots && pts.length <= 45 && pts.map((p) => <circle key={p.day} className="chart-dot" cx={x(p.day)} cy={y(p.value)} r={2.6} />)}
        <circle className="chart-dot" cx={x(last.day)} cy={y(last.value)} r={4.5} />
        {hover && (
          <g>
            <line className="chart-hover" x1={x(hover.day)} x2={x(hover.day)} y1={14} y2={height - 26} />
            <circle className="chart-dot" cx={x(hover.day)} cy={y(hover.value)} r={5} />
          </g>
        )}
      </svg>
      {hover && (
        <div className="chart-tip" style={{ left: Math.min(width - 70, Math.max(70, x(hover.day))), top: y(hover.value) }}>
          <strong>{format(hover.value)}</strong> <span className="muted">{fmtDay(hover.day)}</span>
          {avgAt && <div className="muted tiny">7-Tage-Mittel {format(avgAt.value)}</div>}
          {hover.source && <div className="muted tiny">{hover.sourceName || hover.source}</div>}
        </div>
      )}
    </div>
  );
}

/** Tagesbalken (Schritte, Minuten …). */
export function BarChart({ data, height = 200, goal, format = (v) => fmtNum(v), label }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const pts = data || [];
  if (!pts.length) return <div ref={ref} className="muted small" style={{ height, display: "grid", placeItems: "center" }}>Keine Werte im Zeitraum</div>;
  const pad = { l: 44, r: 10, t: 12, b: 24 };
  const max = Math.max(...pts.map((p) => p.value || 0), goal || 0);
  const { hi, ticks } = niceTicks(0, max || 1, 3);
  const w = Math.max(10, width - pad.l - pad.r), h = height - pad.t - pad.b;
  const t0 = toT(pts[0].day), t1 = toT(pts[pts.length - 1].day);
  const n = Math.round((t1 - t0) / dayMs) + 1;
  const bw = Math.max(1.5, (w / n) * 0.72);
  const x = (iso) => pad.l + ((toT(iso) - t0) / dayMs + 0.5) * (w / n);
  const y = (v) => pad.t + h - (v / hi) * h;
  return (
    <div className="chart-wrap" ref={ref}>
      <svg className="chart" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label || "Tageswerte"}
        onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="chart-grid" x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} />
            <text className="chart-axis" x={pad.l - 6} y={y(t) + 4} textAnchor="end">{format(t)}</text>
          </g>
        ))}
        {pts.map((p, i) => {
          const v = p.value || 0;
          return (
            <g key={p.day} onMouseEnter={() => setHover(p)}>
              <rect x={x(p.day) - (w / n) / 2} y={pad.t} width={w / n} height={h} fill="transparent" />
              <rect className={`chart-bar${goal && v < goal ? " dim" : ""}`} x={x(p.day) - bw / 2} y={y(v)} width={bw} height={Math.max(0, pad.t + h - y(v))} rx={Math.min(4, bw / 2)}
                style={{ transformOrigin: `0 ${pad.t + h}px`, animation: `grow-y .6s cubic-bezier(.2,.8,.2,1) ${Math.min(i * 8, 400)}ms backwards` }} />
            </g>
          );
        })}
        {goal ? <line className="chart-goal" x1={pad.l} x2={width - pad.r} y1={y(goal)} y2={y(goal)} /> : null}
        {dateTicks(t0, Math.max(t1, t0 + dayMs), width).map((t) => {
          const d = new Date(t);
          const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
          return <text key={t} className="chart-axis" x={x(iso)} y={height - 6} textAnchor="middle">{n > 70 ? monthFmt.format(d) : fmtDayShort(iso)}</text>;
        })}
      </svg>
      {hover && (
        <div className="chart-tip" style={{ left: Math.min(width - 70, Math.max(70, x(hover.day))), top: y(hover.value || 0) }}>
          <strong>{format(hover.value)}</strong> <span className="muted">{fmtDay(hover.day)}</span>
        </div>
      )}
    </div>
  );
}

/** Kleiner Verlauf ohne Achsen. */
export function Sparkline({ data, height = 42 }) {
  const pts = (data || []).filter((p) => p.value != null);
  if (pts.length < 2) return <svg className="spark" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true" />;
  const vals = pts.map((p) => p.value);
  const min = Math.min(...vals), max = Math.max(...vals);
  const t0 = toT(pts[0].day), t1 = toT(pts[pts.length - 1].day) || t0 + 1;
  const x = (iso) => ((toT(iso) - t0) / (t1 - t0 || 1)) * 100;
  const y = (v) => 36 - ((v - min) / (max - min || 1)) * 32;
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(p.day).toFixed(2)},${y(p.value).toFixed(2)}`).join("");
  return (
    <svg className="spark" viewBox="0 0 100 40" preserveAspectRatio="none" style={{ height }} aria-hidden="true">
      <path d={`${d}L100,40L0,40Z`} className="chart-area" />
      <path d={d} className="chart-line" style={{ vectorEffect: "non-scaling-stroke" }} />
    </svg>
  );
}

/** Der Tageskern: konzentrische Ringe, je Ring Anteil am Ziel (über 100 % läuft eine zweite Runde blasser weiter). */
export function KernRings({ rings, children, size = 240 }) {
  const [shown, setShown] = useState(false);
  useEffect(() => { const id = requestAnimationFrame(() => setShown(true)); return () => cancelAnimationFrame(id); }, []);
  const c = size / 2;
  const stroke = size * 0.075;
  const gap = stroke * 0.42;
  return (
    <div className="kern-rings">
      <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label={rings.map((r) => `${r.label}: ${Math.round((r.progress || 0) * 100)} %`).join(", ")}>
        {rings.map((r, i) => {
          const rad = c - stroke / 2 - i * (stroke + gap);
          const circ = 2 * Math.PI * rad;
          const p = Math.max(0, r.progress || 0);
          const first = Math.min(1, p);
          const over = Math.min(1, Math.max(0, p - 1));
          return (
            <g key={r.key} transform={`rotate(-90 ${c} ${c})`}>
              <circle className="ring-track" cx={c} cy={c} r={rad} strokeWidth={stroke} />
              <circle className="ring-fill" cx={c} cy={c} r={rad} strokeWidth={stroke} stroke={r.color}
                strokeDasharray={circ} strokeDashoffset={shown ? circ * (1 - first) : circ} style={{ transitionDelay: `${i * 140}ms` }} />
              {over > 0 && <circle className="ring-over" cx={c} cy={c} r={rad} strokeWidth={stroke * 0.45} stroke="var(--chalk)"
                strokeDasharray={circ} strokeDashoffset={shown ? circ * (1 - over) : circ} />}
            </g>
          );
        })}
      </svg>
      <div className="kern-center">{children}</div>
    </div>
  );
}

/** Jahreskalender: ein Kästchen pro Tag, Farbe nach Trainingsminuten. */
export function Calendar({ data, end, days = 365 }) {
  const map = new Map((data || []).map((d) => [d.day, d.minutes]));
  const last = parseDay(end);
  const start = new Date(last.getTime() - (days - 1) * dayMs);
  const offset = (start.getDay() + 6) % 7;
  const cells = [];
  for (let i = 0; i < days; i++) {
    const d = new Date(start.getTime() + i * dayMs);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const m = map.get(iso) || 0;
    const lvl = m === 0 ? 0 : m < 30 ? 1 : m < 60 ? 2 : m < 100 ? 3 : 4;
    const idx = i + offset;
    cells.push({ iso, m, lvl, col: Math.floor(idx / 7), row: idx % 7, month: d.getDate() === 1 ? d : null });
  }
  const cols = Math.max(...cells.map((c) => c.col)) + 1;
  const s = 12, g = 3;
  return (
    <div className="calendar">
      <svg viewBox={`0 0 ${cols * (s + g) + 30} ${7 * (s + g) + 18}`} role="img" aria-label="Trainingskalender">
        {["Mo", "Mi", "Fr"].map((t, i) => <text key={t} className="chart-axis" x={0} y={18 + (i * 2) * (s + g) + s - 2}>{t}</text>)}
        {cells.map((c) => (
          <g key={c.iso}>
            {c.month && <text className="chart-axis" x={26 + c.col * (s + g)} y={10}>{monthFmt.format(c.month)}</text>}
            <rect className={`cal-${c.lvl}`} x={26 + c.col * (s + g)} y={16 + c.row * (s + g)} width={s} height={s} rx={3}>
              <title>{`${fmtDay(c.iso)}: ${c.m ? `${c.m} min` : "kein Training"}`}</title>
            </rect>
          </g>
        ))}
      </svg>
    </div>
  );
}

/** Fitness (42 Tage) und Ermüdung (7 Tage) als Linien, Form als Fläche. */
export function LoadChart({ data, height = 220 }) {
  const [ref, width] = useWidth();
  if (!data?.length) return <div ref={ref} />;
  const pad = { l: 40, r: 10, t: 10, b: 24 };
  const vals = data.flatMap((d) => [d.fitness, d.fatigue, d.form]);
  const { lo, hi, ticks } = niceTicks(Math.min(...vals, 0), Math.max(...vals, 1), 4);
  const w = width - pad.l - pad.r, h = height - pad.t - pad.b;
  const x = (i) => pad.l + (i / Math.max(1, data.length - 1)) * w;
  const y = (v) => pad.t + h - ((v - lo) / (hi - lo || 1)) * h;
  const line = (k) => data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d[k]).toFixed(1)}`).join("");
  const formArea = `${line("form")}L${x(data.length - 1)},${y(0)}L${x(0)},${y(0)}Z`;
  return (
    <div ref={ref}>
      <svg className="chart" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Fitness und Ermüdung">
        {ticks.map((t) => (
          <g key={t}>
            <line className="chart-grid" x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} />
            <text className="chart-axis" x={pad.l - 6} y={y(t) + 4} textAnchor="end">{fmtNum(t)}</text>
          </g>
        ))}
        <path d={formArea} fill="var(--c-recovery)" opacity="0.14" />
        <path d={line("fitness")} className="chart-line draw" pathLength="1" style={{ "--c": "var(--c-activity)" }} />
        <path d={line("fatigue")} className="chart-line thin" style={{ "--c": "var(--c-heart)", opacity: 0.85 }} />
        {data.filter((_, i) => i % 30 === 0).map((d) => {
          const i = data.indexOf(d);
          return <text key={d.day} className="chart-axis" x={x(i)} y={height - 6} textAnchor="middle">{fmtDayShort(d.day)}</text>;
        })}
      </svg>
      <div className="legend">
        <span style={{ "--c": "var(--c-activity)" }}><i />Fitness (42 Tage)</span>
        <span style={{ "--c": "var(--c-heart)" }}><i />Ermüdung (7 Tage)</span>
        <span style={{ "--c": "var(--c-recovery)" }}><i />Form</span>
      </div>
    </div>
  );
}

export function StageBar({ deep, rem, light, awake }) {
  const total = (deep || 0) + (rem || 0) + (light || 0) + (awake || 0);
  if (!total) return null;
  const pct = (v) => `${((v || 0) / total) * 100}%`;
  return (
    <div className="stagebar" role="img" aria-label="Schlafphasen">
      <span className="st-deep" style={{ width: pct(deep) }} />
      <span className="st-light" style={{ width: pct(light) }} />
      <span className="st-rem" style={{ width: pct(rem) }} />
      <span className="st-awake" style={{ width: pct(awake) }} />
    </div>
  );
}

/** Google-Polyline entschlüsseln. */
export function decodePolyline(str) {
  const out = [];
  let i = 0, lat = 0, lng = 0;
  while (str && i < str.length) {
    for (const k of [0, 1]) {
      let b, shift = 0, result = 0;
      do {
        b = str.charCodeAt(i++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20 && i < str.length + 1);
      const d = result & 1 ? ~(result >> 1) : result >> 1;
      if (k === 0) lat += d; else lng += d;
    }
    out.push([lat / 1e5, lng / 1e5]);
  }
  return out;
}

/** Streckenform ohne Kartendienst: die Linie, maßstabsgetreu (Länge nach Breitengrad gestaucht). */
export function Route({ polyline }) {
  const pts = useMemo(() => decodePolyline(polyline || ""), [polyline]);
  if (pts.length < 2) return null;
  const lat0 = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const k = Math.cos((lat0 * Math.PI) / 180);
  const xs = pts.map((p) => p[1] * k), ys = pts.map((p) => -p[0]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const span = Math.max(maxX - minX, maxY - minY) || 1;
  const W = 1000, H = Math.max(260, Math.min(700, (W * (maxY - minY)) / (maxX - minX || span)));
  const sx = (W - 40) / ((maxX - minX) || span), sy = (H - 40) / ((maxY - minY) || span);
  const s = Math.min(sx, sy);
  const ox = (W - (maxX - minX) * s) / 2, oy = (H - (maxY - minY) * s) / 2;
  const X = (i) => ox + (xs[i] - minX) * s, Y = (i) => oy + (ys[i] - minY) * s;
  const d = pts.map((_, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(i).toFixed(1)}`).join("");
  return (
    <div className="route">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Streckenverlauf">
        <path d={d} className="draw" pathLength="1" style={{ animationDuration: "1.6s" }} />
        <circle className="start" cx={X(0)} cy={Y(0)} r={9} />
        <circle className="finish" cx={X(pts.length - 1)} cy={Y(pts.length - 1)} r={9} />
      </svg>
    </div>
  );
}
