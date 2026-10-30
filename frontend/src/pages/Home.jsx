import { useEffect, useState } from "react";
import BodyMap from "../components/BodyMap.jsx";
import Coach from "../components/Coach.jsx";
import HabitsToday from "../habits/HabitsToday.jsx";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { KernRings, StageBar } from "../components/charts.jsx";
import { Loading, confirmDialog, toast } from "../components/feedback.jsx";
import { EmptyState, MetricCard, Segmented, SportIcon, useAsync } from "../components/ui.jsx";
import { fmtDuration, fmtKm, fmtLongDay, fmtMinutes, fmtNum, fmtTime, weekdayShort } from "../fmt.js";

function greeting() {
  const h = new Date().getHours();
  if (h < 5) return "Gute Nacht";
  if (h < 11) return "Guten Morgen";
  if (h < 18) return "Hallo";
  return "Guten Abend";
}

const READINESS_LABEL = { readiness: "Bereitschaft", recovery: "Erholung", body_battery: "Body Battery" };

function readinessText(v) {
  if (v >= 80) return "Gut erholt. Ein guter Tag für eine fordernde Einheit.";
  if (v >= 60) return "Normal erholt. Training wie geplant.";
  if (v >= 40) return "Etwas angeschlagen. Lieber locker oder kurz.";
  return "Wenig erholt. Ruhe und Schlaf bringen heute am meisten.";
}

export default function Home({ user }) {
  const [tick, setTick] = useState(0);
  const navigate = useNavigate();
  const [{ data, loading, error }] = useAsync(() => api.get("/dashboard"), []);
  const keys = (user.prefs?.home?.length ? user.prefs.home : null)?.join(",") || "";
  const [{ data: summary }] = useAsync(() => api.get(`/summary?keys=${keys}`), [keys]);
  const [busy, setBusy] = useState(false);

  if (loading && !data) return <Loading rows={3} />;
  if (error) return <EmptyState title="Übersicht nicht verfügbar" text={error.message} />;

  async function loadDemo() {
    setBusy(true);
    try {
      await api.post("/me/demo");
      toast("Beispieldaten geladen");
      window.location.reload();
    } catch (e) {
      toast(e.message, "error");
      setBusy(false);
    }
  }
  async function removeDemo() {
    if (!(await confirmDialog("Alle Beispieldaten werden gelöscht. Deine eigenen Daten bleiben.", { title: "Beispieldaten entfernen?", confirmLabel: "Entfernen" }))) return;
    await api.del("/me/demo");
    toast("Beispieldaten entfernt");
    window.location.reload();
  }

  const name = user.name ? `, ${user.name}` : "";
  const head = (
    <div className="page-head">
      <div>
        <h1>{greeting()}{name}</h1>
        <p>{fmtLongDay(new Date())}</p>
      </div>
      <div className="actions"><Link className="btn" to="/sources">Quellen</Link></div>
    </div>
  );

  if (!data.has_data) {
    return (
      <>
        {head}
        <EmptyState title="Noch keine Daten" text="Verbinde deine Uhr, Waage, deinen Ring oder deine Apps. BodyBase holt die Daten selbstständig und führt sie hier zusammen.">
          <button className="btn primary" onClick={() => navigate("/sources")}>Erste Quelle verbinden</button>
          <button className="btn" onClick={loadDemo} disabled={busy}>Mit Beispieldaten ausprobieren</button>
        </EmptyState>
      </>
    );
  }

  const [steps, active, sleep] = data.rings;
  const progress = (r) => (r.value != null && r.goal ? r.value / r.goal : 0);
  const rd = data.readiness;
  const week = data.week;
  const maxMin = Math.max(30, ...week.days.map((d) => d.minutes));
  const todayIso = data.today;
  return (
    <>
      {head}
      {data.demo && (
        <div className="notice info">
          <div><p><strong>Du siehst Beispieldaten.</strong> So sieht BodyBase mit ein paar Monaten Daten aus mehreren Quellen aus.</p></div>
          <button className="btn small" onClick={removeDemo} style={{ marginLeft: "auto" }}>Entfernen</button>
        </div>
      )}
      {data.connections.problems.map((p) => (
        <div key={p.provider} className="notice bad">
          <div><p><strong>{p.name}:</strong> {p.status === "auth" ? "Der Zugang ist abgelaufen." : "Der letzte Abgleich ist fehlgeschlagen."}</p>
            {p.error && <p className="small muted">{p.error}</p>}</div>
          <Link className="btn small" to={`/sources?provider=${p.provider}`} style={{ marginLeft: "auto" }}>Ansehen</Link>
        </div>
      ))}

      <div className="home-hero">
        <section className="kern" aria-label="Heute">
          <KernRings rings={[
            { key: "steps", label: "Schritte", progress: progress(steps), color: "var(--c-activity)" },
            { key: "active", label: "Aktive Minuten", progress: progress(active), color: "var(--c-heart)" },
            { key: "sleep", label: "Schlaf", progress: progress(sleep), color: "var(--c-sleep)" },
          ]}>
            <div>
              <strong>{steps.value != null && steps.goal ? `${Math.round(progress(steps) * 100)}%` : "–"}</strong>
              <span>des Schrittziels</span>
            </div>
          </KernRings>
          <ul className="kern-legend">
            <li className="cat-activity"><i /><div><div className="lbl">Schritte heute</div>
              <div className="val">{fmtNum(steps.value)}<small>von {fmtNum(steps.goal)}</small></div></div></li>
            <li className="cat-heart"><i /><div><div className="lbl">Aktive Minuten</div>
              <div className="val">{fmtNum(active.value)}<small>von {fmtNum(active.goal)}</small></div></div></li>
            <li className="cat-sleep"><i /><div><div className="lbl">Schlaf letzte Nacht</div>
              <div className="val">{fmtMinutes(sleep.value)}<small>von {fmtMinutes(sleep.goal)}</small></div></div></li>
          </ul>
        </section>

        <div className="stack">
          <section className="panel readiness" style={{ marginBottom: 0 }}>
            <div className="panel-head">
              <h2>{rd ? READINESS_LABEL[rd.key] || "Bereitschaft" : "Bereitschaft"}</h2>
              {rd && <span className="pill">{rd.estimated ? `geschätzt aus ${rd.basis.join(" und ")}` : `laut ${providerName(rd.source)}`}</span>}
            </div>
            {rd ? (
              <>
                <div className="readiness-top">
                  <div className="readiness-num">{fmtNum(rd.value)}</div>
                  <p className="muted" style={{ margin: 0 }}>{readinessText(rd.value)}</p>
                </div>
                <div className="readiness-bar" aria-hidden="true"><i style={{ left: `${Math.max(0, Math.min(100, rd.value))}%` }} /></div>
              </>
            ) : <p className="muted">Sobald HRV und Ruhepuls von ein paar Tagen vorliegen, schätzt BodyBase hier deine Erholung.</p>}
          </section>
          <section className="panel" style={{ marginBottom: 0 }}>
            <div className="panel-head"><h2>Letzte Nacht</h2><Link className="link small" to="/sleep">Schlaf</Link></div>
            {data.sleep ? (
              <>
                <p style={{ marginBottom: "0.6rem" }}>
                  <strong style={{ fontFamily: "var(--font-display)", fontSize: "1.9rem" }}>{fmtMinutes(data.sleep.asleep_min)}</strong>
                  <span className="muted small"> · {fmtTime(data.sleep.start)} bis {fmtTime(data.sleep.end)}</span>
                  {data.sleep.score != null && <span className="pill" style={{ marginLeft: "0.6rem" }}>Wert {fmtNum(data.sleep.score)}</span>}
                </p>
                <StageBar deep={data.sleep.deep_min} rem={data.sleep.rem_min} light={data.sleep.light_min} awake={data.sleep.awake_min} />
                <div className="stage-legend">
                  {data.sleep.deep_min != null && <span><i className="st-deep" />Tief {fmtMinutes(data.sleep.deep_min)}</span>}
                  {data.sleep.rem_min != null && <span><i className="st-rem" />REM {fmtMinutes(data.sleep.rem_min)}</span>}
                  {data.sleep.light_min != null && <span><i className="st-light" />Leicht {fmtMinutes(data.sleep.light_min)}</span>}
                </div>
              </>
            ) : <p className="muted">Keine Schlafdaten der letzten Nacht.</p>}
          </section>
        </div>
      </div>

      <div className="section-title"><h2>Werte</h2><Link className="link small" to="/health">Alle Messgrößen</Link></div>
      <div className="metric-grid">
        {(summary || []).map((item) => <MetricCard key={item.key} item={item} to={`/metric/${item.key}`} />)}
      </div>

      <div className="grid-2">
        <HabitsToday onChanged={() => setTick((n) => n + 1)} />
        <Coach refreshKey={tick} compact />
      </div>

      <BodyLoadPanel refreshKey={tick} />

      <div className="grid-2">
        <section className="panel cat-activity">
          <div className="panel-head"><h2>Diese Woche</h2><Link className="link small" to="/activities">Aktivitäten</Link></div>
          <div className="week-facts">
            <span><strong>{fmtMinutes(week.totals.minutes)}</strong>Training</span>
            <span><strong>{week.totals.count}</strong>Einheiten</span>
            <span><strong>{fmtNum(week.totals.distance_km, 1)}</strong>km</span>
            {week.prev.minutes > 0 && <span>Vorwoche {fmtMinutes(week.prev.minutes)}</span>}
          </div>
          <div className="week-bars">
            {week.days.map((d, i) => (
              <div key={d.day} className={`week-day${d.day === todayIso ? " today" : ""}`} title={`${d.count} Einheiten`}>
                <span className="week-min">{d.minutes ? d.minutes : ""}</span>
                <div className="week-track">
                  {d.minutes > 0 && <div className="week-fill" style={{ height: `${(d.minutes / maxMin) * 100}%`, "--i": i }} />}
                </div>
                <span className="week-label">{weekdayShort(d.day)}</span>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-head"><h2>Zuletzt</h2></div>
          {data.recent.length ? (
            <ul className="list">
              {data.recent.slice(0, 5).map((a) => (
                <li key={a.id}>
                  <Link className="act-row" to={`/activities/${a.id}`}>
                    <SportIcon sport={a.sport} />
                    <div className="act-main"><strong>{a.name || a.sport_label}</strong>
                      <span>{relWhen(a.start)} · {a.source_name}</span></div>
                    <div className="act-stats">
                      <div><b>{fmtDuration(a.duration_s || a.moving_s)}</b><small>Dauer</small></div>
                      {a.distance_m ? <div><b>{fmtKm(a.distance_m)}</b><small>km</small></div> : null}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          ) : <p className="muted">Noch keine Aktivitäten.</p>}
        </section>
      </div>
    </>
  );
}

const PROVIDER_NAMES = { bodybase: "BodyBase", oura: "Oura", whoop: "WHOOP", garmin: "Garmin", polar: "Polar", intervals: "intervals.icu",
  fitbit: "Fitbit", apple_health: "Apple Health", manual: "Eingabe" };
const providerName = (key) => PROVIDER_NAMES[key] || key;

function relWhen(iso) {
  const d = new Date(iso);
  const today = new Date();
  const days = Math.round((new Date(today.toDateString()) - new Date(d.toDateString())) / 86400000);
  const t = fmtTime(iso);
  if (days === 0) return `Heute, ${t}`;
  if (days === 1) return `Gestern, ${t}`;
  return `${d.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "short" })}, ${t}`;
}


const LOAD_RANGES = [{ value: 7, label: "7 Tage" }, { value: 30, label: "30 Tage" }, { value: 90, label: "90 Tage" }, { value: 365, label: "1 Jahr" }];

/** Welche Körperregionen im Zeitraum beansprucht wurden: Krafttraining plus Rad, Laufen, Klettern & Co. */
function BodyLoadPanel({ refreshKey }) {
  const [days, setDays] = useState(() => { try { return Number(localStorage.getItem("bodybase-load-days")) || 30; } catch { return 30; } });
  const [data, setData] = useState(null);
  useEffect(() => {
    try { localStorage.setItem("bodybase-load-days", String(days)); } catch { /* privat */ }
    api.get(`/strength/body-load?days=${days}`).then(setData).catch(() => setData(null));
  }, [days, refreshKey]);
  const values = {};
  const detail = {};
  for (const m of data?.muscles || []) {
    if (m.value > 0) {
      values[m.muscle] = m.value;
      detail[m.muscle] = [m.strength ? `Kraft ${fmtNum(m.strength, m.strength % 1 ? 1 : 0)}` : null,
        m.sports ? `Ausdauer & Sport ${fmtNum(m.sports, m.sports % 1 ? 1 : 0)}` : null,
        m.habits ? `Gewohnheiten ${fmtNum(m.habits, m.habits % 1 ? 1 : 0)}` : null].filter(Boolean).join(" · ");
    }
  }
  const empty = data && !data.strength.sets && !data.sources.length && !data.habits?.length;
  return (
    <section className="panel cat-activity">
      <div className="panel-head">
        <h2>Beanspruchte Körperregionen</h2>
        <Segmented value={days} onChange={setDays} options={LOAD_RANGES} label="Zeitraum" />
      </div>
      {!data ? <p className="muted small">Lade …</p> : empty ? (
        <p className="muted">Im Zeitraum gibt es kein Training. Krafttraining, Radfahren, Laufen, Klettern und andere Sportarten erscheinen hier als Körperkarte.</p>
      ) : (
        <>
          <BodyMap values={values} unit="Punkte" detail={detail} />
          <div className="load-sources">
            {data.strength.sets > 0 && <span className="pill"><b>Kraft</b> {data.strength.workouts} Trainings · {data.strength.sets} Sätze</span>}
            {data.sources.map((s) => <span key={s.sport} className="pill"><b>{s.label}</b> {fmtMinutes(s.minutes)}</span>)}
            {(data.habits || []).map((h) => <span key={h.habit} className="pill"><b>{h.habit}</b> {fmtNum(h.total)} {h.unit || ""}</span>)}
          </div>
          <p className="hint">Ein Punkt entspricht etwa einem Arbeitssatz. Ausdauer zählt je 10 Minuten anteilig für die beteiligten Muskeln, beim Radfahren also vor allem Oberschenkel, Gesäß und Waden, beim Klettern Unterarme, Rücken und Bizeps.</p>
        </>
      )}
    </section>
  );
}
