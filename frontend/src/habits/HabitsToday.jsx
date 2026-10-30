import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { toast } from "../components/feedback.jsx";
import { fmtNum } from "../fmt.js";

export function steps(target) {
  if (!target || target <= 5) return [1];
  if (target <= 20) return [5];
  if (target <= 60) return [5, 10];
  return [10, 25];
}

/** Eine Gewohnheit mit Fortschritt und schnellen Knöpfen zum Eintragen. */
export function HabitRow({ h, onChange }) {
  const [busy, setBusy] = useState(false);
  const t = h.today;
  async function log(body) {
    setBusy(true);
    try {
      const next = await api.post(`/habits/${h.id}/log`, body);
      onChange(next);
      if (!t.done && next.today.done) toast(`${h.name} geschafft${next.streak > 1 ? ` · ${next.streak} Tage in Folge` : ""}`);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }
  const pct = h.kind === "check" ? (t.done ? 100 : 0) : Math.min(100, ((t.value || 0) / (t.target || 1)) * 100);
  return (
    <div className={`habit-row${t.done ? " done" : ""}${!t.due ? " rest" : ""}`} style={{ "--c": h.color || "var(--c-recovery)" }}>
      <div className="habit-main">
        <div className="habit-top">
          <Link to="/habits" className="habit-name">{h.name}</Link>
          {h.streak > 0 && <span className="habit-streak" title="Tage in Folge">🔥 {h.streak}</span>}
        </div>
        {h.kind === "count" ? (
          <>
            <div className="habit-bar"><i style={{ width: `${pct}%` }} /></div>
            <div className="tiny muted">{fmtNum(t.value || 0)} / {fmtNum(t.target)} {h.unit || ""}{!t.due ? " · heute frei" : ""}
              {h.increment ? ` · ab Montag ${fmtNum(h.next_week_target)}` : ""}</div>
          </>
        ) : <div className="tiny muted">{t.done ? "erledigt" : t.due ? "heute offen" : "heute frei"}</div>}
      </div>
      <div className="habit-actions">
        {h.kind === "count" ? (
          <>
            {steps(t.target).map((s) => <button key={s} className="btn small" disabled={busy} onClick={() => log({ add: s })}>+{s}</button>)}
            {!t.done && <button className="btn small primary" disabled={busy} onClick={() => log({ value: Math.max(t.target || 0, t.value || 0) })} title="Ziel erreicht">✓</button>}
            {t.value ? <button className="btn small ghost" disabled={busy} onClick={() => log({ add: -steps(t.target)[0] })} aria-label="Weniger">−</button> : null}
          </>
        ) : (
          <button className={`set-check${t.done ? " on" : ""}`} disabled={busy} onClick={() => log({ value: t.done ? 0 : 1 })} aria-pressed={t.done}>✓</button>
        )}
      </div>
    </div>
  );
}

/** Startseite: Gewohnheiten von heute. */
export default function HabitsToday({ onChanged }) {
  const [items, setItems] = useState(null);
  useEffect(() => { api.get("/habits").then(setItems).catch(() => setItems([])); }, []);
  if (!items) return null;
  const update = (h) => { setItems((cur) => cur.map((x) => (x.id === h.id ? h : x))); onChanged?.(); };
  const done = items.filter((h) => h.today.due && h.today.done).length;
  const due = items.filter((h) => h.today.due).length;
  return (
    <section className="panel habits-today">
      <div className="panel-head">
        <h2>Gewohnheiten</h2>
        <span className="small muted">{due ? `${done} von ${due} heute` : ""} <Link className="link small" to="/habits" style={{ marginLeft: "0.5rem" }}>Verwalten</Link></span>
      </div>
      {items.length ? items.map((h) => <HabitRow key={h.id} h={h} onChange={update} />) : (
        <p className="muted small">Zum Beispiel jeden Tag Liegestütze, mit einem Ziel, das jeden Montag steigt. <Link className="link" to="/habits">Gewohnheit anlegen</Link></p>
      )}
    </section>
  );
}
