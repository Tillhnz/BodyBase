import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { Calendar, LoadChart, decodePolyline, useWidth } from "../components/charts.jsx";
import RouteMap from "../components/RouteMap.jsx";
import { Loading, confirmDialog, toast } from "../components/feedback.jsx";
import { EmptyState, Kpi, Segmented, SportIcon, useAsync } from "../components/ui.jsx";
import { fmtDuration, fmtKm, fmtNum, fmtTime, todayIso } from "../fmt.js";
import { useMeta } from "../meta.js";

const RANGES = [{ value: 30, label: "30 Tage" }, { value: 90, label: "90 Tage" }, { value: 365, label: "1 Jahr" }, { value: 0, label: "Alles" }];
const PAGE = 40;

function speedLabel(a) {
  if (!a.distance_m || !(a.moving_s || a.duration_s)) return null;
  const s = a.moving_s || a.duration_s;
  if (a.sport === "run" || a.sport === "walk" || a.sport === "hike") {
    const pace = s / (a.distance_m / 1000);
    return { value: `${Math.floor(pace / 60)}:${String(Math.round(pace % 60)).padStart(2, "0")}`, unit: "/km", label: "Tempo" };
  }
  if (a.sport === "swim") {
    const p = s / (a.distance_m / 100);
    return { value: `${Math.floor(p / 60)}:${String(Math.round(p % 60)).padStart(2, "0")}`, unit: "/100 m", label: "Tempo" };
  }
  return { value: fmtNum((a.distance_m / 1000) / (s / 3600), 1), unit: "km/h", label: "Schnitt" };
}

function when(iso) {
  const d = new Date(iso);
  return `${d.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "short", year: d.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined })}, ${fmtTime(iso)}`;
}

export function ActivityRow({ a }) {
  const sp = speedLabel(a);
  return (
    <Link className="act-row" to={`/activities/${a.id}`}>
      <SportIcon sport={a.sport} />
      <div className="act-main">
        <strong>{a.name || a.sport_label}</strong>
        <span>{when(a.start)} · {a.source_name}{a.also_in?.length ? <span className="also" title="Auch in diesen Quellen, nur einmal gezählt">+ {a.also_in.join(", ")}</span> : null}</span>
      </div>
      <div className="act-stats">
        <div><b>{fmtDuration(a.duration_s || a.moving_s)}</b><small>Dauer</small></div>
        {a.distance_m ? <div><b>{fmtKm(a.distance_m)}</b><small>km</small></div> : a.volume_kg ? <div><b>{fmtNum(a.volume_kg / 1000, 1)}</b><small>t bewegt</small></div> : null}
        {sp && <div><b>{sp.value}</b><small>{sp.unit}</small></div>}
        {a.avg_hr ? <div><b>{fmtNum(a.avg_hr)}</b><small>Ø Puls</small></div> : null}
      </div>
    </Link>
  );
}

export default function Activities() {
  const meta = useMeta();
  const [days, setDays] = useState(90);
  const [sport, setSport] = useState("");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [totals, setTotals] = useState(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [{ data: stats }] = useAsync(() => api.get(`/activities/stats?days=${days || 3650}`), [days]);

  useEffect(() => {
    const id = setTimeout(() => setQuery(q), 300);
    return () => clearTimeout(id);
  }, [q]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const p = new URLSearchParams({ limit: PAGE, offset });
    if (days) p.set("days", days);
    if (sport) p.set("sport", sport);
    if (query) p.set("q", query);
    api.get(`/activities?${p}`).then((r) => {
      if (!alive) return;
      setItems((old) => (offset ? [...old, ...r.items] : r.items));
      setTotal(r.total);
      setTotals(r.totals);
      setLoading(false);
    }).catch((e) => { toast(e.message, "error"); setLoading(false); });
    return () => { alive = false; };
  }, [days, sport, query, offset]);

  useEffect(() => { setOffset(0); }, [days, sport, query]);

  const maxMin = Math.max(1, ...(stats?.sports || []).map((s) => s.minutes));
  return (
    <div className="cat-activity">
      <div className="page-head">
        <div><h1>Aktivitäten</h1><p>Alle Einheiten aus allen Quellen. Dieselbe Einheit aus mehreren Quellen erscheint nur einmal.</p></div>
        <Segmented value={days} onChange={setDays} options={RANGES} label="Zeitraum" />
      </div>
      {totals && (
        <div className="kpis">
          <Kpi label="Einheiten" value={fmtNum(totals.count)} />
          <Kpi label="Trainingszeit" value={fmtNum(totals.duration_s / 3600, 0)} unit="h" />
          <Kpi label="Strecke" value={fmtNum(totals.distance_m / 1000, 0)} unit="km" />
          <Kpi label="Höhenmeter" value={fmtNum(totals.elevation_m, 0)} unit="m" />
          <Kpi label="Kalorien" value={fmtNum(totals.calories, 0)} unit="kcal" />
        </div>
      )}
      {stats && stats.calendar.length > 0 && (
        <>
          <section className="panel">
            <div className="panel-head"><h2>Trainingskalender</h2><span className="muted small">Minuten pro Tag</span></div>
            <Calendar data={stats.calendar} end={todayIso()} days={Math.min(371, days || 371)} />
          </section>
          <div className="grid-2">
            <section className="panel">
              <div className="panel-head"><h2>Sportarten</h2></div>
              <ul className="hbars">
                {stats.sports.map((s, i) => (
                  <li key={s.sport}>
                    <span className="hbar-label">{s.label}</span>
                    <span className="hbar-track"><span className="hbar-fill" style={{ width: `${(s.minutes / maxMin) * 100}%`, animationDelay: `${i * 60}ms` }} /></span>
                    <span className="hbar-val">{fmtDuration(s.minutes * 60)}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="panel">
              <div className="panel-head"><h2>Fitness und Ermüdung</h2></div>
              <LoadChart data={stats.load} />
            </section>
          </div>
        </>
      )}
      <div className="section-title"><h2>Einheiten</h2><span className="muted small">{fmtNum(total)} insgesamt</span></div>
      <div className="filters">
        <input type="search" placeholder="Suchen …" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Aktivitäten durchsuchen" />
        <div className="chips">
          <button className={`chip${!sport ? " on" : ""}`} onClick={() => setSport("")}>Alle</button>
          {(stats?.sports || []).map((s) => (
            <button key={s.sport} className={`chip${sport === s.sport ? " on" : ""}`} onClick={() => setSport(s.sport)}>{meta?.sports[s.sport] || s.label}</button>
          ))}
        </div>
      </div>
      {loading && !items.length ? <Loading rows={2} /> : items.length ? (
        <section className="panel">
          <ul className="list">{items.map((a) => <li key={a.id}><ActivityRow a={a} /></li>)}</ul>
          {items.length < total && (
            <div className="actions" style={{ justifyContent: "center" }}>
              <button className="btn" onClick={() => setOffset(items.length)} disabled={loading}>Weitere laden</button>
            </div>
          )}
        </section>
      ) : (
        <EmptyState title="Keine Aktivitäten" text="Im gewählten Zeitraum gibt es keine Einheiten. Verbinde Garmin, Strava, Polar & Co. oder importiere FIT-Dateien.">
          <Link className="btn primary" to="/sources">Quellen</Link>
        </EmptyState>
      )}
    </div>
  );
}

function Profile({ x, y, label, unit, colorVar, digits = 0, hover, onHover }) {
  const [ref, width] = useWidth();
  const pts = x.map((d, i) => [d, y[i], i]).filter((p) => p[1] != null);
  if (pts.length < 2) return null;
  const h = 120;
  const xmax = x[x.length - 1] || 1;
  const ys = pts.map((p) => p[1]);
  const lo = Math.min(...ys), hi = Math.max(...ys);
  const X = (v) => 40 + (v / xmax) * (width - 50);
  const Y = (v) => 8 + (h - 30) * (1 - (v - lo) / (hi - lo || 1));
  const d = pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
  function move(e) {
    if (!onHover) return;
    const r = e.currentTarget.getBoundingClientRect();
    const km = ((e.clientX - r.left - 40) / (width - 50)) * xmax;
    let best = pts[0];
    for (const p of pts) if (Math.abs(p[0] - km) < Math.abs(best[0] - km)) best = p;
    onHover(best[2]);
  }
  const cur = hover != null ? pts.find((p) => p[2] === hover) : null;
  return (
    <div ref={ref} style={{ "--c": colorVar }}>
      <div className="small muted" style={{ display: "flex", justifyContent: "space-between" }}>
        <span>{label}{cur ? <strong style={{ color: "var(--chalk)", marginLeft: "0.5rem" }}>{fmtNum(cur[1], digits)} {unit} · {fmtNum(cur[0], 1)} km</strong> : null}</span>
        <span>{fmtNum(lo, digits)}–{fmtNum(hi, digits)} {unit}</span>
      </div>
      <svg className="chart" width={width} height={h} viewBox={`0 0 ${width} ${h}`} aria-label={label} role="img"
        onMouseMove={move} onMouseLeave={() => onHover && onHover(null)} onTouchEnd={() => onHover && onHover(null)}
        onTouchMove={(e) => e.touches[0] && move({ currentTarget: e.currentTarget, clientX: e.touches[0].clientX })}>
        <path className="chart-area" d={`${d}L${X(pts[pts.length - 1][0])},${h - 22}L${X(pts[0][0])},${h - 22}Z`} />
        <path className="chart-line" d={d} />
        {cur && <line className="chart-cursor" x1={X(cur[0])} x2={X(cur[0])} y1={4} y2={h - 22} />}
        {cur && <circle cx={X(cur[0])} cy={Y(cur[1])} r={4} fill="var(--c)" stroke="var(--ink)" strokeWidth={2} />}
        <text className="chart-axis" x={40} y={h - 6}>0 km</text>
        <text className="chart-axis" x={width - 10} y={h - 6} textAnchor="end">{fmtNum(xmax, 1)} km</text>
      </svg>
    </div>
  );
}

export function ActivityDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [{ data: a, error }] = useAsync(() => api.get(`/activities/${id}`), [id]);
  const [hover, setHover] = useState(null);
  const ll = useMemo(() => (a?.details?.profile?.ll ? decodePolyline(a.details.profile.ll) : null), [a]);
  if (error) return <EmptyState title="Nicht gefunden" text={error.message}><Link className="btn" to="/activities">Zurück</Link></EmptyState>;
  if (!a) return <Loading rows={2} />;
  const sp = speedLabel(a);
  const prof = a.details?.profile;
  async function remove() {
    if (!(await confirmDialog("Die Einheit wird aus BodyBase gelöscht. Beim nächsten Abgleich kann sie von der Quelle erneut kommen."))) return;
    await api.del(`/activities/${a.id}`);
    toast("Gelöscht");
    navigate("/activities");
  }
  const exercises = a.details?.exercises;
  return (
    <div className="cat-activity">
      <div className="page-head">
        <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
          <SportIcon sport={a.sport} />
          <div>
            <p style={{ margin: 0 }}><Link className="link quiet small" to="/activities">Aktivitäten</Link></p>
            <h1>{a.name || a.sport_label}</h1>
            <p style={{ margin: 0 }}>{when(a.start)} · {a.sport_label}{a.sport_raw && a.sport_raw !== a.name ? ` (${a.sport_raw})` : ""}</p>
          </div>
        </div>
        <div className="actions">
          {a.details?.workout_id ? <Link className="btn primary" to={`/strength/workout/${a.details.workout_id}`}>Im Krafttraining öffnen</Link> : null}
          <button className="btn danger" onClick={remove}>Löschen</button>
        </div>
      </div>
      <div className="kpis">
        <Kpi label="Dauer" value={fmtDuration(a.duration_s || a.moving_s)} sub={a.moving_s && a.duration_s && a.moving_s < a.duration_s - 60 ? `in Bewegung ${fmtDuration(a.moving_s)}` : null} />
        {a.distance_m ? <Kpi label="Strecke" value={fmtKm(a.distance_m, 2)} unit="km" /> : null}
        {sp && <Kpi label={sp.label} value={sp.value} unit={sp.unit} />}
        {a.elevation_m ? <Kpi label="Höhenmeter" value={fmtNum(a.elevation_m)} unit="m" /> : null}
        {a.avg_hr ? <Kpi label="Puls" value={fmtNum(a.avg_hr)} unit="bpm" sub={a.max_hr ? `max. ${fmtNum(a.max_hr)}` : null} /> : null}
        {a.avg_power ? <Kpi label="Leistung" value={fmtNum(a.avg_power)} unit="W" /> : null}
        {a.calories ? <Kpi label="Kalorien" value={fmtNum(a.calories)} unit="kcal" /> : null}
        {a.load ? <Kpi label="Belastung" value={fmtNum(a.load, a.load < 25 ? 1 : 0)} /> : null}
        {a.volume_kg ? <Kpi label="Bewegtes Gewicht" value={fmtNum(a.volume_kg)} unit="kg" /> : null}
      </div>
      {a.polyline ? (
        <section className="panel map-panel">
          <RouteMap polyline={a.polyline} hover={hover != null && ll ? ll[hover] : null} />
        </section>
      ) : null}
      <div className="grid-2">
        {prof && (prof.e || prof.h || prof.s) ? (
          <section className="panel stack">
            <div className="panel-head" style={{ marginBottom: 0 }}><h2>Verlauf</h2></div>
            {prof.e && <Profile x={prof.d} y={prof.e} label="Höhe" unit="m" colorVar="var(--c-body)" hover={hover} onHover={setHover} />}
            {prof.h && <Profile x={prof.d} y={prof.h} label="Puls" unit="bpm" colorVar="var(--c-heart)" hover={hover} onHover={setHover} />}
            {prof.s && <Profile x={prof.d} y={prof.s} label="Tempo" unit="km/h" colorVar="var(--c-activity)" digits={1} hover={hover} onHover={setHover} />}
            {prof.p && <Profile x={prof.d} y={prof.p} label="Leistung" unit="W" colorVar="var(--c-metabolic)" hover={hover} onHover={setHover} />}
          </section>
        ) : null}
        {exercises?.length ? (
          <section className="panel">
            <div className="panel-head"><h2>Übungen</h2></div>
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Übung</th><th className="num">Sätze</th><th>Wiederholungen × kg</th></tr></thead>
              <tbody>{exercises.map((ex, i) => (
                <tr key={i}><td>{ex.name}</td><td className="num">{ex.sets.filter((s) => s.type !== "warmup").length}</td>
                  <td className="small">{ex.sets.filter((s) => s.type !== "warmup").map((s) => `${fmtNum(s.reps)}×${fmtNum(s.kg, s.kg % 1 ? 1 : 0)}`).join(" · ")}</td></tr>
              ))}</tbody>
            </table></div>
          </section>
        ) : null}
        <section className="panel">
          <div className="panel-head"><h2>Quellen dieser Einheit</h2></div>
          <div className="versions">
            {a.versions.map((v) => (
              <div key={v.id} className="version-row">
                <span><strong>{v.source_name}</strong>{v.primary && <span className="pill iris" style={{ marginLeft: "0.5rem" }}>zählt</span>}</span>
                <span className="muted">{v.distance_m ? `${fmtKm(v.distance_m, 2)} km · ` : ""}{fmtDuration(v.duration_s)}{v.avg_hr ? ` · ${fmtNum(v.avg_hr)} bpm` : ""}</span>
              </div>
            ))}
          </div>
          {a.versions.length > 1 && <p className="hint" style={{ marginTop: "0.6rem" }}>Welche Quelle zählt, legst du unter Einstellungen → Datenquellen fest.</p>}
        </section>
      </div>
    </div>
  );
}
