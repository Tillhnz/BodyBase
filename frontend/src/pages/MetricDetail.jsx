import { useEffect, useState } from "react";
import HrChart from "../components/HrChart.jsx";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";
import { BarChart, LineChart } from "../components/charts.jsx";
import EntryDialog from "../components/EntryDialog.jsx";
import { Loading, confirmDialog, toast } from "../components/feedback.jsx";
import { Delta, EmptyState, Kpi, Segmented, relDay, useAsync } from "../components/ui.jsx";
import { fmtAgo, fmtDate, fmtMetric, fmtNum } from "../fmt.js";
import { useMeta } from "../meta.js";
import { useProviders } from "./Sources.jsx";

const RANGES = [
  { value: 30, label: "30 Tage" }, { value: 90, label: "90 Tage" }, { value: 365, label: "1 Jahr" }, { value: 1825, label: "5 Jahre" },
];
const SMOOTH = new Set(["weight", "body_fat", "muscle_mass", "lean_mass", "body_water", "bmi", "resting_hr", "hrv", "vo2max"]);
const GOAL_KEYS = new Set(["steps", "sleep_duration", "active_minutes", "weight"]);

export default function MetricDetail({ user, onUser }) {
  const { key } = useParams();
  const meta = useMeta();
  const providers = useProviders();
  const [days, setDays] = useState(90);
  const [group, setGroup] = useState("day");
  const [reload, setReload] = useState(0);
  const [entry, setEntry] = useState(false);
  const [{ data, loading, error }] = useAsync(() => api.get(`/metrics/${key}?days=${days}&group=${group}`), [key, days, group, reload]);
  const [{ data: entries }, setEntries] = useAsync(() => api.get(`/entries?metric=${key}`), [key, reload]);
  if (error) return <EmptyState title="Messgröße nicht gefunden" text={error.message}><Link className="btn" to="/health">Zurück</Link></EmptyState>;
  if (!data || !meta) return <Loading rows={2} />;
  const m = data.metric;
  const st = data.stats;
  const fmt = (v) => fmtMetric(m, v, false);
  const isSum = m.agg === "sum";
  const name = (k) => providers?.find((p) => p.key === k)?.name || ({ manual: "Eigene Eingaben" }[k] ?? k);
  const series = data.series.map((p) => ({ ...p, sourceName: p.source ? name(p.source) : null }));

  async function move(src, dir) {
    const order = data.sources.map((s) => s.source).sort((a, b) => data.priority.indexOf(a) - data.priority.indexOf(b));
    const i = order.indexOf(src);
    const j = i + dir;
    if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    const priority = { ...(user.prefs?.priority || {}), [key]: order };
    try {
      const u = await api.put("/me/prefs", { priority });
      onUser(u);
      setReload((n) => n + 1);
      toast("Reihenfolge gespeichert");
    } catch (e) { toast(e.message, "error"); }
  }

  async function saveGoal(e) {
    e.preventDefault();
    const raw = new FormData(e.target).get("goal");
    const v = raw === "" ? null : Number(String(raw).replace(",", "."));
    const goalValue = key === "sleep_duration" && v != null ? Math.round(v * 60) : v;
    const goals = { ...(user.prefs?.goals || {}), [key]: goalValue };
    try {
      onUser(await api.put("/me/prefs", { goals }));
      setReload((n) => n + 1);
      toast("Ziel gespeichert");
    } catch (err) { toast(err.message, "error"); }
  }

  async function removeEntry(id) {
    if (!(await confirmDialog("Diesen eigenen Eintrag löschen?"))) return;
    await api.del(`/entries/${id}`);
    setEntries((l) => l.filter((x) => x.id !== id));
    setReload((n) => n + 1);
  }

  const ordered = [...data.sources].sort((a, b) => data.priority.indexOf(a.source) - data.priority.indexOf(b.source));
  const change = st.prev_avg != null && st.avg != null ? st.avg - st.prev_avg : null;
  return (
    <div className={`cat-${m.category}`}>
      <div className="page-head">
        <div>
          <p style={{ margin: 0 }}><Link className="link quiet small" to={`/health?c=${m.category}`}>{m.category_label}</Link></p>
          <h1>{m.label}</h1>
          {st.last != null && <p>Zuletzt {fmtMetric(m, st.last)} · {relDay(data.series[data.series.length - 1].day)}</p>}
        </div>
        <div className="actions">
          <Link className="btn" to={`/trends?a=${key}`}>Vergleichen</Link>
          <button className="btn primary" onClick={() => setEntry(true)}>Wert eintragen</button>
        </div>
      </div>

      {key === "heart_rate" && <RecentHeartRate />}

      <section className="panel">
        <div className="panel-head">
          <Segmented value={days} onChange={setDays} options={RANGES} label="Zeitraum" />
          <Segmented value={group} onChange={setGroup} label="Zusammenfassung"
            options={[{ value: "day", label: "Tage" }, { value: "week", label: "Wochen" }, { value: "month", label: "Monate" }]} />
        </div>
        {loading && <span className="sr-only">Lade …</span>}
        {isSum && group === "day" && days <= 90
          ? <BarChart data={series} goal={data.goal} format={fmt} label={m.label} />
          : <LineChart data={series} goal={data.goal} format={fmt} smooth={SMOOTH.has(key) && group === "day"} zero={isSum} label={m.label} />}
        {group !== "day" && isSum && <p className="hint">Wochen und Monate zeigen den Durchschnitt pro Tag.</p>}
      </section>

      {st.count ? (
        <div className="kpis">
          <Kpi label={`Ø ${RANGES.find((r) => r.value === days)?.label}`} value={fmt(st.avg)} unit={m.unit !== "min" ? m.unit : ""}
            sub={change != null ? <Delta value={change} better={m.better} format={(v) => fmtNum(v, Math.max(1, m.decimals))} suffix=" ggü. davor" /> : null} />
          <Kpi label="Niedrigster Wert" value={fmt(st.min)} unit={m.unit !== "min" ? m.unit : ""} />
          <Kpi label="Höchster Wert" value={fmt(st.max)} unit={m.unit !== "min" ? m.unit : ""} />
          {st.trend_per_week != null && <Kpi label="Trend pro Woche" value={`${st.trend_per_week > 0 ? "+" : ""}${fmtNum(st.trend_per_week, Math.max(1, m.decimals))}`}
            unit={m.unit !== "min" ? m.unit : "min"} />}
          <Kpi label="Tage mit Werten" value={fmtNum(st.count)} />
        </div>
      ) : <p className="muted">Im gewählten Zeitraum gibt es keine Werte.</p>}

      <div className="grid-2">
        <section className="panel">
          <div className="panel-head"><h2>Quellen</h2></div>
          {ordered.length ? (
            <>
              <p className="muted small">Liefern mehrere Quellen einen Wert für denselben Tag, gilt die obere. Die Reihenfolge kannst du ändern.</p>
              <ul className="list">
                {ordered.map((s, i) => (
                  <li key={s.source} style={{ display: "flex", alignItems: "center", gap: "0.8rem", padding: "0.55rem 0" }}>
                    <span className="pill">{i + 1}</span>
                    <div style={{ flex: 1, minWidth: 0 }}><strong>{name(s.source)}</strong>
                      <div className="tiny muted">{fmtNum(s.count)} Werte · zuletzt {fmtDate(s.last)}</div></div>
                    {ordered.length > 1 && <>
                      <button className="btn small" onClick={() => move(s.source, -1)} disabled={i === 0} aria-label="Nach oben">↑</button>
                      <button className="btn small" onClick={() => move(s.source, 1)} disabled={i === ordered.length - 1} aria-label="Nach unten">↓</button>
                    </>}
                  </li>
                ))}
              </ul>
            </>
          ) : <p className="muted">Noch keine Quelle liefert diese Messgröße. <Link className="link" to="/sources">Quellen ansehen</Link></p>}
        </section>
        <section className="panel">
          {GOAL_KEYS.has(key) && (
            <form onSubmit={saveGoal} style={{ marginBottom: "1.2rem" }}>
              <div className="panel-head"><h2>Ziel</h2></div>
              <div className="copy-row">
                <input name="goal" inputMode="decimal" key={data.goal ?? "leer"}
                  defaultValue={data.goal == null ? "" : key === "sleep_duration" ? fmtNum(data.goal / 60, 1).replace(".", ",") : String(data.goal).replace(".", ",")}
                  placeholder={key === "sleep_duration" ? "Stunden, z. B. 7,5" : m.unit} aria-label="Ziel" />
                <button className="btn">Speichern</button>
              </div>
              <p className="hint">{key === "sleep_duration" ? "In Stunden." : key === "weight" ? "Zielgewicht in kg; leer lassen für kein Ziel." : `Pro Tag${m.unit ? ` in ${m.unit}` : ""}.`}</p>
            </form>
          )}
          <div className="panel-head"><h2>Eigene Einträge</h2></div>
          {entries?.length ? (
            <ul className="list">
              {entries.slice(0, 12).map((e) => (
                <li key={e.id} style={{ display: "flex", justifyContent: "space-between", padding: "0.45rem 0", gap: "1rem" }}>
                  <span>{fmtMetric(m, e.value)}</span>
                  <span className="muted small">{fmtAgo(e.ts)}</span>
                  <button className="link danger small" onClick={() => removeEntry(e.id)}>Löschen</button>
                </li>
              ))}
            </ul>
          ) : <p className="muted small">Keine eigenen Einträge. Über „Wert eintragen“ ergänzt du Messungen ohne verbundenes Gerät.</p>}
        </section>
      </div>
      {entry && <EntryDialog metric={key} onClose={() => setEntry(false)} onSaved={() => setReload((n) => n + 1)} />}
    </div>
  );
}


/** Puls der letzten 3 Tage in voller Auflösung (ältere Werte gibt es nur als Stundenmittel). */
function RecentHeartRate() {
  const [hours, setHours] = useState(24);
  const [data, setData] = useState(null);
  useEffect(() => { api.get(`/heart-rate/recent?hours=${hours}`).then(setData).catch(() => setData(null)); }, [hours]);
  return (
    <section className="panel cat-heart">
      <div className="panel-head">
        <h2>Verlauf in voller Auflösung</h2>
        <Segmented value={hours} onChange={setHours} options={[{ value: 6, label: "6 h" }, { value: 24, label: "24 h" }, { value: 72, label: "3 Tage" }]} label="Zeitraum" />
      </div>
      {data?.t?.length ? <HrChart series={data} height={200} /> : (
        <p className="muted small">Keine Einzelwerte in diesem Zeitraum. Sie kommen von Health Connect, Health Auto Export oder eigenen Skripten.
          BodyBase behält Einzelwerte 3 Tage, danach Stundenmittel. Trainingseinheiten behalten ihren vollen Verlauf.</p>
      )}
    </section>
  );
}
