import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { fmtMetric, fmtNum } from "../fmt.js";
import { Sparkline } from "./charts.jsx";
import { toast } from "./feedback.jsx";

export function BrandMark({ className = "" }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <g fill="none" strokeWidth="6" strokeLinecap="round">
        <circle cx="32" cy="32" r="26" stroke="var(--line)" />
        <circle cx="32" cy="32" r="16" stroke="var(--line)" />
        <path d="M32 6 A26 26 0 1 1 9.5 45" stroke="var(--c-activity)" />
        <path d="M32 16 A16 16 0 1 1 18.1 40" stroke="var(--c-heart)" />
      </g>
      <circle cx="32" cy="32" r="5.5" fill="var(--c-sleep)" />
    </svg>
  );
}

const LIGHT_LOGOS = new Set(["#e8e8e8", "#e9eef1", "#f2d15b"]);

export function ProviderLogo({ provider, size }) {
  if (!provider) return null;
  return (
    <span className={`logo${size === "lg" ? " lg" : ""}${LIGHT_LOGOS.has(provider.color) ? " light" : ""}`} style={{ "--logo": provider.color }} aria-hidden="true">
      {provider.initials}
    </span>
  );
}

/** Pfeil mit Bewertung: grün, wenn die Änderung in die gute Richtung geht. */
export function Delta({ value, better, format = (v) => fmtNum(v, 1), suffix = "" }) {
  if (value == null || Number.isNaN(value)) return null;
  const tiny = Math.abs(value) < 1e-9;
  const good = better === "up" ? value > 0 : better === "down" ? value < 0 : null;
  const cls = tiny || good === null ? "flat" : good ? "good" : "bad";
  return <span className={`delta ${cls}`}>{tiny ? "±0" : `${value > 0 ? "▲" : "▼"} ${format(Math.abs(value))}`}{suffix}</span>;
}

/** Kachel mit jüngstem Wert, Vergleich zum Schnitt und Verlauf. */
export function MetricCard({ item, to }) {
  const m = item.metric;
  const last = item.last;
  const diff = last && item.avg != null ? last.value - item.avg : null;
  const body = (
    <>
      <div className="mc-label"><span>{m.label}</span>{last && <span className="tiny">{relDay(last.day)}</span>}</div>
      <div className="mc-value">{last ? valueParts(m, last.value) : "–"}</div>
      <Sparkline data={item.spark} />
      <div className="mc-foot">
        {diff != null ? <><Delta value={diff} better={m.better} format={(v) => fmtNum(v, Math.max(m.decimals, Math.abs(v) < 10 ? 1 : 0))} /><span>ggü. Ø</span></> : <span>Noch keine Werte</span>}
      </div>
    </>
  );
  const cls = `metric-card cat-${m.category}${last ? "" : " is-empty"}`;
  return to ? <Link className={cls} to={to}>{body}</Link> : <div className={cls}>{body}</div>;
}

function valueParts(m, v) {
  if (m.unit === "min" && m.category === "sleep") {
    const t = Math.round(v);
    return <>{Math.floor(t / 60)}<small>h</small> {String(t % 60).padStart(2, "0")}<small>min</small></>;
  }
  return <>{fmtNum(v, m.decimals)}{m.unit && <small>{m.unit}</small>}</>;
}

export function relDay(iso) {
  const d = new Date(`${iso}T12:00:00`);
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  const diff = Math.round((today - d) / 86400000);
  if (diff === 0) return "heute";
  if (diff === 1) return "gestern";
  if (diff < 7) return `vor ${diff} Tagen`;
  return d.toLocaleDateString("de-DE", { day: "numeric", month: "short" });
}

export function Kpi({ label, value, unit, sub }) {
  return (
    <div className="kpi">
      <div className="kpi-value">{value}{unit && <small>{unit}</small>}</div>
      <div className="kpi-label">{label}</div>
      {sub && <div className="tiny muted">{sub}</div>}
    </div>
  );
}

export function Segmented({ value, onChange, options, label }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={o.value === value} className={o.value === value ? "on" : ""}
          onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export function Switch({ checked, onChange, children }) {
  return (
    <label className="switch">
      <input type="checkbox" role="switch" checked={!!checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="switch-track" aria-hidden="true"><span className="switch-knob" /></span>
      <span>{children}</span>
    </label>
  );
}

export function EmptyState({ title, text, children }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {text && <p className="muted">{text}</p>}
      {children && <div className="actions">{children}</div>}
    </div>
  );
}

const SPORT_ICONS = {
  run: "M13 4 A1.6 1.6 0 1 0 13.01 4 M8 21 L11 14 L14 16 V21 M6 11 L9 8 L13 8.5 L16 12 L19 13",
  ride: "M6 17 A3.5 3.5 0 1 0 6.01 17 M18 17 A3.5 3.5 0 1 0 18.01 17 M6 17 L10 9 H15 L18 17 M10 9 L12.5 17 H6 M9 6 H12",
  walk: "M12 4 A1.5 1.5 0 1 0 12.01 4 M9 21 L11 15 L13 17 V21 M10 9 L8 13 M10 9 L14 9.5 L15 13 M11 9 L11.5 14",
  hike: "M3 20 L9 10 L13 15 L16 11 L21 20 Z M15 5 A1.4 1.4 0 1 0 15.01 5",
  swim: "M3 17 C5 15.5 7 15.5 9 17 C11 18.5 13 18.5 15 17 C17 15.5 19 15.5 21 17 M8 13 L12 9 L15 11 M16 7 A1.5 1.5 0 1 0 16.01 7",
  strength: "M4 9 V15 M7 7 V17 M17 7 V17 M20 9 V15 M7 12 H17",
  row: "M3 18 C8 16 16 16 21 18 M5 14 L19 8 M15 6 L19 8 L17 12",
  ski: "M4 20 L20 14 M7 13 L12 8 L16 10 M15 5 A1.4 1.4 0 1 0 15.01 5 M9 16 L11 12",
  yoga: "M12 4 A1.5 1.5 0 1 0 12.01 4 M5 12 C8 10 16 10 19 12 M12 8 V14 L8 19 M12 14 L16 19",
  cardio: "M3 12 H7 L9 7 L13 17 L15 12 H21",
  team: "M12 3 A9 9 0 1 0 12.01 3 M12 3 C9 7 9 17 12 21 M3 12 H21",
  other: "M12 6 A6 6 0 1 0 12.01 6 M12 9 V12 L14 14",
};

export function SportIcon({ sport }) {
  return (
    <span className="sport-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24"><path d={SPORT_ICONS[sport] || SPORT_ICONS.other} /></svg>
    </span>
  );
}

/** Dialog mit Fokusfalle und Escape. */
export function Modal({ title, onClose, children, wide, head }) {
  const ref = useRef(null);
  const last = useRef(document.activeElement);
  useEffect(() => {
    const before = last.current;
    ref.current?.querySelector("input, select, textarea, button")?.focus();
    return () => before?.focus?.();
  }, []);
  function onKey(e) {
    if (e.key === "Escape") { e.stopPropagation(); onClose(); }
  }
  return (
    <div className="modal-back" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} ref={ref} onKeyDown={onKey}>
        {head || <h3>{title}</h3>}
        {children}
      </div>
    </div>
  );
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Kopiert");
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); toast("Kopiert"); } catch { toast("Kopieren nicht möglich", "error"); }
    ta.remove();
  }
}

export function CopyField({ value, label }) {
  return (
    <div className="copy-row">
      <code aria-label={label}>{value}</code>
      <button type="button" className="btn small" onClick={() => copyText(value)}>Kopieren</button>
    </div>
  );
}

export function useAsync(fn, deps) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    fn().then((data) => alive && setState({ loading: false, data, error: null }))
      .catch((error) => alive && setState({ loading: false, data: null, error }));
    return () => { alive = false; };
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return [state, (data) => setState((s) => ({ ...s, data: typeof data === "function" ? data(s.data) : data }))];
}

export { fmtMetric };
