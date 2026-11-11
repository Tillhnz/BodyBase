import { useEffect, useState } from "react";
import { api } from "../api.js";
import { toast } from "../components/feedback.jsx";
import { useWidth } from "../components/charts.jsx";
import { fmtDay, fmtNum } from "../fmt.js";

/* Jahresübersicht einer Gewohnheit: Kalender-Raster wie bei GitHub, Monatsquoten und Nachtragen per Klick. */

const MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
const WD = ["Mo", "", "Mi", "", "Fr", "", "So"];

export default function HabitYear({ habitId, onChanged, compact = false }) {
  const [year, setYear] = useState(new Date().getFullYear());
  const [data, setData] = useState(null);
  const [edit, setEdit] = useState(null);
  const [ref, width] = useWidth(700);
  useEffect(() => { api.get(`/habits/${habitId}/history?year=${year}`).then(setData).catch((e) => toast(e.message, "error")); }, [habitId, year]);
  if (!data) return <div ref={ref} className="habit-year loading" />;
  const h = data.habit;
  const first = new Date(`${year}-01-01T12:00:00`);
  const offset = (first.getDay() + 6) % 7;
  const weeks = Math.ceil((data.days.length + offset) / 7);
  const gap = 3;
  const cell = Math.max(7, Math.min(16, Math.floor((width - 26) / weeks) - gap));
  const max = Math.max(1, ...data.days.map((d) => d.value || 0));

  async function save(day, value) {
    try {
      await api.post(`/habits/${habitId}/log`, { day, value });
      setData(await api.get(`/habits/${habitId}/history?year=${year}`));
      onChanged?.();
    } catch (e) { toast(e.message, "error"); }
  }
  function click(d) {
    if (d.future) return;
    if (h.kind === "check") save(d.day, d.value ? 0 : 1);
    else setEdit({ ...d, input: d.value ?? d.target ?? "" });
  }
  const level = (d) => {
    if (!d.value) return d.due && !d.future ? "miss" : "";
    if (h.kind === "check" || d.done) return "l4";
    const r = d.value / (d.target || max);
    return r >= 0.66 ? "l3" : r >= 0.33 ? "l2" : "l1";
  };
  const s = data.summary;
  return (
    <div className={`habit-year${compact ? " compact" : ""}`} style={{ "--c": h.color || "var(--c-recovery)" }}>
      <div className="hy-head">
        {compact && <strong>{h.name}</strong>}
        <div className="hy-years">
          <button type="button" className="btn small" disabled={!data.years.includes(year - 1)} onClick={() => setYear(year - 1)} aria-label="Jahr davor">‹</button>
          <b>{year}</b>
          <button type="button" className="btn small" disabled={year >= new Date().getFullYear()} onClick={() => setYear(year + 1)} aria-label="Jahr danach">›</button>
        </div>
        <span className="hy-sum small">
          <b>{s.done}</b> Tage geschafft{s.rate != null ? ` · ${Math.round(s.rate * 100)} %` : ""}{h.kind === "count" ? ` · ${fmtNum(s.total)} ${h.unit || ""} gesamt` : ""}
        </span>
      </div>
      <div ref={ref} className="hy-grid-wrap">
        <svg width={26 + weeks * (cell + gap)} height={16 + 7 * (cell + gap)} role="img" aria-label={`${h.name} im Jahr ${year}`}>
          {MONTHS.map((m, i) => {
            const idx = Math.round((new Date(year, i, 1) - new Date(year, 0, 1)) / 864e5);
            return <text key={m} x={26 + Math.floor((idx + offset) / 7) * (cell + gap)} y={10} className="rp-tick">{m}</text>;
          })}
          {WD.map((w, i) => w && <text key={i} x={0} y={16 + i * (cell + gap) + cell - 1} className="rp-tick">{w}</text>)}
          {data.days.map((d, i) => {
            const k = i + offset;
            return (
              <rect key={d.day} x={26 + Math.floor(k / 7) * (cell + gap)} y={16 + (k % 7) * (cell + gap)} width={cell} height={cell} rx={Math.min(4, cell / 3)}
                className={`hy-cell ${level(d)}${d.future ? " future" : ""}`} onClick={() => click(d)}>
                <title>{`${fmtDay(d.day)}: ${d.value ? fmtNum(d.value) : "–"}${d.target && h.kind === "count" ? ` / ${fmtNum(d.target)}` : ""}${d.future ? "" : " · zum Ändern klicken"}`}</title>
              </rect>
            );
          })}
        </svg>
      </div>
      {!compact && (
        <div className="hy-months">
          {data.months.map((m) => (
            <div key={m.month} title={m.rate != null ? `${m.done} von ${m.due} fälligen Tagen` : "keine fälligen Tage"}>
              <span className="hy-bar"><i style={{ height: `${(m.rate ?? 0) * 100}%` }} /></span>
              <small>{MONTHS[m.month - 1]}</small>
              <small className="muted">{m.rate != null ? `${Math.round(m.rate * 100)}%` : "–"}</small>
            </div>
          ))}
        </div>
      )}
      {!compact && <p className="tiny muted" style={{ margin: "0.3rem 0 0" }}>Tipp: Auf einen Tag klicken, um nachzutragen{h.kind === "check" ? " (Klick schaltet um)" : ""}. Mit ‹ geht es in frühere Jahre.</p>}
      {edit && (
        <div className="hy-edit">
          <form onSubmit={(e) => { e.preventDefault(); save(edit.day, Number(String(edit.input).replace(",", ".")) || 0); setEdit(null); }}>
            <label className="small">{fmtDay(edit.day)}{edit.target ? ` · Ziel ${fmtNum(edit.target)}` : ""}
              <input inputMode="decimal" value={edit.input} autoFocus onChange={(e) => setEdit({ ...edit, input: e.target.value })} /></label>
            <button className="btn primary small">Speichern</button>
            <button type="button" className="btn small" onClick={() => setEdit(null)}>Abbrechen</button>
          </form>
        </div>
      )}
    </div>
  );
}
