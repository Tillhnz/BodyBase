import { useEffect, useState } from "react";
import BodyMap from "../components/BodyMap.jsx";
import Coach from "../components/Coach.jsx";
import HabitsToday from "../habits/HabitsToday.jsx";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import ScoreCards from "../components/Scores.jsx";
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
        <div className="grid-2 home-habits" style={{ marginTop: "1.25rem" }}>
          <HabitsToday onChanged={() => setTick((n) => n + 1)} />
          <Coach refreshKey={tick} compact />
        </div>
      </>
    );
  }

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

      <ScoreCards scores={data.scores} sleep={data.sleep} goals={data.goals} />

      <div className="grid-2 home-habits">
        <HabitsToday onChanged={() => setTick((n) => n + 1)} />
        <Coach refreshKey={tick} compact />
      </div>

      <div className="section-title"><h2>Werte</h2><Link className="link small" to="/health">Alle Messgrößen</Link></div>
      <div className="metric-grid">
        {(summary || []).map((item) => <MetricCard key={item.key} item={item} to={`/metric/${item.key}`} />)}
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
const LOAD_COLORS = {
  strength: "var(--c-activity)", ride: "var(--c-recovery)", run: "var(--c-heart)", climb: "var(--c-sleep)", habits: "var(--c-nutrition)",
  swim: "var(--c-body)", hike: "var(--c-recovery)", walk: "var(--mute)", row: "var(--c-body)", ski: "var(--c-body)",
  yoga: "var(--c-sleep)", team: "var(--c-metabolic)", cardio: "var(--c-metabolic)",
};

/** Welche Körperregionen im Zeitraum beansprucht wurden; filterbar nach Aktivitätsart. */
function BodyLoadPanel({ refreshKey }) {
  const [days, setDays] = useState(() => { try { return Number(localStorage.getItem("bodybase-load-days")) || 30; } catch { return 30; } });
  const [data, setData] = useState(null);
  const [only, setOnly] = useState([]); // leer = alle Arten
  useEffect(() => {
    try { localStorage.setItem("bodybase-load-days", String(days)); } catch { /* privat */ }
    api.get(`/strength/body-load?days=${days}`).then(setData).catch(() => setData(null));
  }, [days, refreshKey]);
  const cats = data?.categories || [];
  const active = only.filter((k) => cats.some((c) => c.key === k));
  const labels = Object.fromEntries(cats.map((c) => [c.key, c.label]));
  const values = {};
  const detail = {};
  for (const m of data?.muscles || []) {
    const parts = Object.entries(m.by || {}).filter(([k]) => !active.length || active.includes(k));
    const v = parts.reduce((a, [, x]) => a + x, 0);
    if (v > 0) {
      values[m.muscle] = Math.round(v * 10) / 10;
      detail[m.muscle] = parts.sort((a, b) => b[1] - a[1]).map(([k, x]) => `${labels[k] || k} ${fmtNum(x, x < 10 && x % 1 ? 1 : 0)}`).join(" · ");
    }
  }
  const toggle = (k) => setOnly((cur) => (cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]));
  const color = active.length === 1 ? LOAD_COLORS[active[0]] || "var(--c-activity)" : "var(--c-activity)";
  return (
    <section className="panel cat-activity">
      <div className="panel-head">
        <h2>Beanspruchte Körperregionen</h2>
        <Segmented value={days} onChange={setDays} options={LOAD_RANGES} label="Zeitraum" />
      </div>
      {!data ? <p className="muted small">Lade …</p> : !cats.length ? (
        <p className="muted">Im Zeitraum gibt es kein Training. Krafttraining, Radfahren, Laufen, Klettern und andere Sportarten erscheinen hier als Körperkarte.</p>
      ) : (
        <>
          <div className="chips load-filter" role="group" aria-label="Nach Aktivität filtern">
            <button type="button" className={`chip${!active.length ? " on" : ""}`} onClick={() => setOnly([])}>Alle</button>
            {cats.map((c) => (
              <button type="button" key={c.key} className={`chip${active.includes(c.key) ? " on" : ""}`} style={{ "--c": LOAD_COLORS[c.key] || "var(--iris)" }}
                onClick={() => toggle(c.key)} title={c.detail} aria-pressed={active.includes(c.key)}>
                <i />{c.label}<span className="chip-sub">{c.detail}</span>
              </button>
            ))}
          </div>
          <BodyMap values={values} unit="Punkte" detail={detail} color={color} />
          <p className="hint">Tippe eine oder mehrere Aktivitäten an, um nur deren Belastung zu sehen. Ein Punkt entspricht etwa einem Arbeitssatz; Ausdauer zählt je 10 Minuten anteilig für die beteiligten Muskeln, Gewohnheiten mit 12 Wiederholungen je Satz.</p>
        </>
      )}
    </section>
  );
}
