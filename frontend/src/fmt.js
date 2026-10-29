// Zahlen, Zeiten und Einheiten im deutschen Format.

const nf = new Map();
export function fmtNum(v, digits = 0) {
  if (v == null || Number.isNaN(v)) return "–";
  const key = digits;
  if (!nf.has(key)) nf.set(key, new Intl.NumberFormat("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits }));
  return nf.get(key).format(v);
}

/** Minuten als „7:25 h“ bzw. „45 min“. */
export function fmtMinutes(min) {
  if (min == null) return "–";
  const m = Math.round(min);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")} h`;
}

export function fmtDuration(s) {
  if (s == null) return "–";
  const t = Math.round(s);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = t % 60;
  if (h) return `${h}:${String(m).padStart(2, "0")} h`;
  return `${m}:${String(sec).padStart(2, "0")} min`;
}

export function fmtKm(m, digits = 1) {
  return m == null ? "–" : fmtNum(m / 1000, digits);
}

/** Uhrzeit aus Minuten nach Mitternacht. */
export function fmtClock(minutes) {
  if (minutes == null) return "–";
  const m = Math.round(minutes) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

const dayFmt = new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "numeric", month: "short" });
const dateFmt = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "long", year: "numeric" });
const shortFmt = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "short" });
const timeFmt = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" });
const longDay = new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "numeric", month: "long" });

export const parseDay = (iso) => new Date(`${iso}T12:00:00`);
export const fmtDay = (iso) => (iso ? dayFmt.format(parseDay(iso)) : "–");
export const fmtDayShort = (iso) => (iso ? shortFmt.format(parseDay(iso)) : "–");
export const fmtDate = (iso) => (iso ? dateFmt.format(iso.length <= 10 ? parseDay(iso) : new Date(iso)) : "–");
export const fmtLongDay = (d) => longDay.format(d);
export const fmtTime = (iso) => (iso ? timeFmt.format(new Date(iso)) : "–");
export const weekdayShort = (iso) => new Intl.DateTimeFormat("de-DE", { weekday: "short" }).format(parseDay(iso)).replace(".", "");

export function fmtAgo(iso) {
  if (!iso) return "noch nie";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "gerade eben";
  if (s < 3600) return `vor ${Math.round(s / 60)} min`;
  if (s < 86400) return `vor ${Math.round(s / 3600)} h`;
  const d = Math.round(s / 86400);
  return d === 1 ? "gestern" : `vor ${d} Tagen`;
}

/** Wert einer Metrik mit ihrer Einheit und Nachkommastellen. Minuten-Metriken als Stunden. */
export function fmtMetric(metric, v, withUnit = true) {
  if (v == null) return "–";
  if (metric?.unit === "min" && metric.category === "sleep") return fmtMinutes(v);
  const s = fmtNum(v, metric?.decimals ?? 0);
  return withUnit && metric?.unit ? `${s} ${metric.unit}` : s;
}

export function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
