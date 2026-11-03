import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { MonthReport, WeekReport } from "./Report.jsx";
import { api } from "../api.js";
import { useWidth } from "../components/charts.jsx";
import { Loading } from "../components/feedback.jsx";
import { EmptyState, Segmented, useAsync } from "../components/ui.jsx";
import { fmtDate, fmtDayShort, fmtMetric, fmtNum } from "../fmt.js";
import { useDataVersion } from "../refresh.js";

const RANGES = [{ value: 30, label: "30 T" }, { value: 90, label: "90 T" }, { value: 180, label: "6 M" }, { value: 365, label: "1 J" }];
const SECTIONS = [["bild", "Gesamtbild"], ["ebenen", "Ebenen"], ["zusammenhang", "Zusammenhänge"], ["wenn", "Wenn–dann"],
  ["muster", "Wochentage"], ["training", "Training"], ["kennzahlen", "Kennzahlen"], ["quellen", "Quellen"]];
const CAT = { recovery: "var(--c-recovery)", sleep: "var(--c-sleep)", heart: "var(--c-heart)", activity: "var(--c-activity)",
  body: "var(--c-body)", nutrition: "var(--c-nutrition)", metabolic: "var(--c-metabolic)" };
const LAYER_COLORS = ["var(--c-recovery)", "var(--c-sleep)", "var(--c-heart)", "var(--iris)", "var(--c-body)", "var(--c-nutrition)", "var(--c-metabolic)", "var(--warn)"];
const DEFAULT_LAYERS = ["bb_readiness", "bb_sleep", "hrv", "resting_hr"];
const STATUS = { gut: ["gut", "good"], okay: ["okay", "iris"], achtung: ["Achtung", "warn"], unklar: ["wenig Daten", ""] };
const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

const metricOf = (s) => ({ unit: s.unit, decimals: s.decimals, category: s.category });

export default function Analysis() {
  const [params, setParams] = useSearchParams();
  const view = params.get("ansicht") || "woche";
  const tabs = (
    <Segmented value={view} onChange={(v) => setParams({ ansicht: v }, { replace: true })} label="Ansicht"
      options={[{ value: "woche", label: "Woche" }, { value: "monat", label: "Monat" }, { value: "statistik", label: "Statistik" }]} />
  );
  if (view === "statistik") return <Statistics tabs={tabs} />;
  return (
    <>
      <div className="page-head">
        <div><h1>Gesundheitsbild</h1><p>Leistungsbericht aus allen Quellen</p></div>
        <div className="actions">{tabs}</div>
      </div>
      {view === "monat" ? <MonthReport /> : <WeekReport />}
    </>
  );
}

function Statistics({ tabs }) {
  const [days, setDays] = useState(() => { try { return Number(localStorage.getItem("bodybase-analysis-days")) || 90; } catch { return 90; } });
  const v = useDataVersion();
  const [{ data, loading, error }] = useAsync(() => api.get(`/analysis?days=${days}`), [days, v]);
  const pick = (d) => { setDays(d); try { localStorage.setItem("bodybase-analysis-days", String(d)); } catch { /* privat */ } };

  const head = (
    <div className="page-head">
      <div>
        <h1>Gesundheitsbild</h1>
        <p>{data ? `${fmtDate(data.start)} bis ${fmtDate(data.end)} · ${data.coverage.metrics} Messgrößen aus ${data.coverage.sources.length} Quellen, ${data.coverage.activities} Trainings, ${data.coverage.nights} Nächte` : "Alle Quellen zusammen ausgewertet"}</p>
      </div>
      <div className="actions">{tabs}<Segmented value={days} onChange={pick} options={RANGES} label="Zeitraum" /></div>
    </div>
  );
  if (error) return <>{head}<EmptyState title="Analyse nicht verfügbar" text={error.message} /></>;
  if (!data) return <>{head}<Loading rows={4} /></>;
  if (!data.stats.length) return <>{head}<EmptyState title="Noch zu wenig Daten" text="Verbinde Quellen oder warte ein paar Tage. Für Zusammenhänge braucht es mindestens zwei Wochen Messwerte." /></>;

  return (
    <div className={`analysis${loading ? " is-loading" : ""}`}>
      {head}
      <nav className="chips analysis-nav" aria-label="Abschnitte">
        {SECTIONS.map(([id, label]) => <a key={id} className="chip" href={`#${id}`}>{label}</a>)}
      </nav>
      <Overview data={data} />
      <Layers data={data} />
      <Correlations corr={data.correlations} stats={data.stats} />
      <Comparisons items={data.comparisons} />
      <Patterns patterns={data.patterns} stats={data.stats} />
      <Training tr={data.training} />
      <StatsTable stats={data.stats} days={data.days} />
      <Sources items={data.sources} />
      <p className="hint" style={{ marginTop: "1rem" }}>
        So wird gerechnet: Zusammenhänge sind Rangkorrelationen (Spearman) über Tage, bereinigt um langfristige Trends (±14 Tage) und um das
        Wochentagsmuster, damit nicht der Kalender oder ein gemeinsamer Verlauf Zusammenhänge vortäuscht. „Belastbar“ heißt: auch nach der Korrektur
        für viele gleichzeitige Tests (Benjamini-Hochberg, q &lt; 0,1) noch auffällig. Ein Zusammenhang zeigt, was gemeinsam auftritt, nicht was was
        verursacht. Keine medizinische Beratung.
      </p>
    </div>
  );
}

/* ---------- 1. Gesamtbild ---------- */

function Overview({ data }) {
  const s = data.summary;
  return (
    <section id="bild" className="analysis-section">
      <div className="grid-2 summary-boxes">
        <div className="panel sum-box good">
          <h3>Läuft gut</h3>
          {s.strengths.length ? <ul>{s.strengths.map((t) => <li key={t}>{t}</li>)}</ul> : <p className="muted small">Noch nichts Auffälliges.</p>}
        </div>
        <div className="panel sum-box warn">
          <h3>Im Blick behalten</h3>
          {s.attention.length ? <ul>{s.attention.map((t) => <li key={t}>{t}</li>)}</ul> : <p className="muted small">Nichts Auffälliges.</p>}
        </div>
      </div>
      {s.top_links.length > 0 && (
        <div className="panel top-links">
          <h3>Stärkste Zusammenhänge</h3>
          <ul>{s.top_links.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      )}
      <div className="domain-grid">
        {data.domains.map((d) => {
          const [label, cls] = STATUS[d.status] || STATUS.unklar;
          return (
            <div key={d.key} className="panel domain" style={{ "--c": CAT[d.cat] }}>
              <div className="domain-head">
                <Link className="score-title" to={`/metric/${d.metric}`}>{d.title}</Link>
                <span className={`pill ${cls}`}>{label}</span>
              </div>
              <div className="domain-main">
                {d.score != null && <span className="domain-score">{d.score}</span>}
                <strong>{d.headline}</strong>
              </div>
              <ul className="domain-facts">{d.facts.map((f) => <li key={f}>{f}</li>)}</ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/* ---------- 2. Ebenen-Diagramm ---------- */

function Layers({ data }) {
  const keys = Object.keys(data.layers.series);
  const labels = Object.fromEntries(data.stats.map((s) => [s.key, s]));
  const [on, setOn] = useState(() => DEFAULT_LAYERS.filter((k) => keys.includes(k)).concat(keys.filter((k) => !DEFAULT_LAYERS.includes(k))).slice(0, 4));
  const [raw, setRaw] = useState(false);
  const [hover, setHover] = useState(null);
  const [ref, width] = useWidth(800);
  const days = data.layers.days;
  const H = 240, LOAD_H = 46, PAD = 8;
  const x = (i) => PAD + (i / Math.max(1, days.length - 1)) * (width - 2 * PAD);
  // z-Werte: jede Messgröße um ihren eigenen Schnitt, in Standardabweichungen
  const lines = on.filter((k) => data.layers.series[k]).map((k, i) => {
    const s = data.layers.series[k];
    const pts = (raw ? s.daily : s.rolling).map((v) => (v == null || !s.sd ? null : (v - s.mean) / s.sd));
    return { key: k, color: LAYER_COLORS[keys.indexOf(k) % LAYER_COLORS.length], pts, s, i };
  });
  const y = (z) => H / 2 - Math.max(-2.5, Math.min(2.5, z)) * (H / 2 - 12) / 2.5;
  const path = (pts) => {
    let d = "", pen = false;
    pts.forEach((z, i) => {
      if (z == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(z).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  const maxLoad = Math.max(30, ...data.layers.load);
  function move(e) {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left - PAD) / (r.width - 2 * PAD)) * (days.length - 1));
    setHover(Math.max(0, Math.min(days.length - 1, i)));
  }
  return (
    <section id="ebenen" className="panel analysis-section">
      <div className="panel-head">
        <h2>Ebenen übereinander</h2>
        <label className="small muted inline-check"><input type="checkbox" checked={raw} onChange={(e) => setRaw(e.target.checked)} /> Tageswerte statt 7-Tage-Schnitt</label>
      </div>
      <p className="small muted" style={{ marginTop: 0 }}>Jede Linie zeigt, wie weit eine Messgröße über oder unter deinem eigenen Schnitt liegt (in Standardabweichungen). So lassen sich ganz verschiedene Größen übereinanderlegen. Unten die tägliche Auslastung.</p>
      <div className="chips layer-chips" style={{ marginBottom: "0.6rem" }}>
        {keys.map((k) => (
          <button key={k} type="button" className={`chip${on.includes(k) ? " on" : ""}`} style={{ "--c": LAYER_COLORS[keys.indexOf(k) % LAYER_COLORS.length] }}
            onClick={() => setOn(on.includes(k) ? on.filter((x) => x !== k) : [...on, k])}><i />{labels[k]?.label || k}</button>
        ))}
      </div>
      <div ref={ref} className="layer-chart" onMouseMove={move} onMouseLeave={() => setHover(null)} onTouchStart={(e) => move(e.touches[0] ? { currentTarget: e.currentTarget, clientX: e.touches[0].clientX } : e)}>
        <svg width={width} height={H + LOAD_H + 18} role="img" aria-label="Messgrößen übereinander">
          {[-2, -1, 0, 1, 2].map((z) => (
            <g key={z}>
              <line x1={PAD} x2={width - PAD} y1={y(z)} y2={y(z)} className={z === 0 ? "axis-zero" : "grid-line"} />
              <text x={PAD + 2} y={y(z) - 3} className="axis-label">{z === 0 ? "Schnitt" : `${z > 0 ? "+" : ""}${z} σ`}</text>
            </g>
          ))}
          {lines.map((l) => <path key={l.key} d={path(l.pts)} fill="none" stroke={l.color} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" opacity={hover == null ? 0.95 : 0.85} />)}
          {data.layers.load.map((v, i) => {
            const h = (v / maxLoad) * LOAD_H;
            const w = Math.max(1, (width - 2 * PAD) / days.length - 1);
            return <rect key={i} x={x(i) - w / 2} y={H + LOAD_H - h + 4} width={w} height={h} rx="1.5" className="load-bar" />;
          })}
          {days.map((d, i) => (i % Math.ceil(days.length / 6) === 0 ? <text key={d} x={x(i)} y={H + LOAD_H + 16} className="axis-label" textAnchor="middle">{fmtDayShort(d)}</text> : null))}
          {hover != null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={H + LOAD_H + 4} className="hover-line" />}
        </svg>
        {hover != null && (
          <div className="layer-tip" style={{ left: Math.min(width - 190, Math.max(0, x(hover) + 10)) }}>
            <strong>{fmtDate(days[hover])}</strong>
            {lines.map((l) => (
              <span key={l.key}><i style={{ background: l.color }} />{labels[l.key]?.label}: {fmtMetric(metricOf(labels[l.key]), l.s.daily[hover])}</span>
            ))}
            <span className="muted">Auslastung {fmtNum(data.layers.load[hover])}</span>
          </div>
        )}
      </div>
    </section>
  );
}

/* ---------- 3. Zusammenhänge ---------- */

function corrColor(r) {
  if (r == null) return "transparent";
  const a = Math.min(1, Math.abs(r)) * 85;
  return `color-mix(in srgb, ${r > 0 ? "var(--iris)" : "var(--c-heart)"} ${a}%, transparent)`;
}

function Correlations({ corr }) {
  const [lag, setLag] = useState(0);
  const [cell, setCell] = useState(null);
  if (!corr.keys.length) return null;
  const m = lag ? corr.next_day : corr.same_day;
  const short = (l) => (l.length > 14 ? `${l.slice(0, 13)}…` : l);
  return (
    <section id="zusammenhang" className="panel analysis-section">
      <div className="panel-head">
        <h2>Zusammenhänge</h2>
        <Segmented value={lag} onChange={setLag} options={[{ value: 0, label: "Selber Tag" }, { value: 1, label: "Folgetag" }]} label="Versatz" />
      </div>
      <p className="tiny muted" style={{ marginTop: 0 }}>{corr.tested} Paare geprüft, bereinigt um Trends und Wochentage.</p>
      {corr.findings.length > 0 ? (
        <ol className="findings">
          {corr.findings.map((f) => (
            <li key={`${f.a}-${f.b}-${f.lag}`}>
              <span className={`r-badge ${f.r > 0 ? "pos" : "neg"}${f.solid ? "" : " weak"}`}>r {fmtNum(f.r, 2)}</span>
              <div><p>{f.text}</p><span className="tiny muted">{f.solid ? "belastbar" : "Hinweis, könnte Zufall sein"} · {f.n} Tage · p {f.p < 0.001 ? "< 0,001" : fmtNum(f.p, 3)}</span></div>
            </li>
          ))}
        </ol>
      ) : <p className="muted small">Noch keine belastbaren Zusammenhänge. Mit mehr Tagen Daten werden sie sichtbar.</p>}
      <h3 className="sub-h">Alle Paare {lag ? "(Zeile heute → Spalte am Folgetag)" : "(am selben Tag)"}</h3>
      <div className="table-wrap">
        <table className="corr-matrix">
          <thead><tr><th />{corr.labels.map((l) => <th key={l} className="rot"><span>{short(l)}</span></th>)}</tr></thead>
          <tbody>
            {m.map((row, i) => (
              <tr key={corr.keys[i]}>
                <th>{short(corr.labels[i])}</th>
                {row.map((c, j) => (
                  <td key={j} style={{ background: corrColor(c.r) }} className={c.p != null && c.p < 0.05 ? "sig" : ""}
                    onMouseEnter={() => setCell({ i, j, ...c })} onClick={() => setCell({ i, j, ...c })}
                    title={`${corr.labels[i]} → ${corr.labels[j]}: r ${c.r ?? "–"}, ${c.n} Tage`}>
                    {c.r != null && Math.abs(c.r) >= 0.2 && !(lag === 0 && i === j) ? fmtNum(c.r * 100, 0) : ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="tiny muted">
        {cell ? `${corr.labels[cell.i]} ${lag ? "heute" : ""} und ${corr.labels[cell.j]} ${lag ? "am Folgetag" : ""}: r = ${fmtNum(cell.r, 2)}, ${cell.n} Tage${cell.p != null ? `, p ${fmtNum(cell.p, 3)}` : ""}. ` : ""}
        Zahlen sind r × 100; blau = steigen gemeinsam, rot = gegenläufig; Rahmen = signifikant (p &lt; 0,05).
      </p>
    </section>
  );
}

/* ---------- 4. Wenn–dann ---------- */

function Comparisons({ items }) {
  if (!items.length) return null;
  return (
    <section id="wenn" className="analysis-section">
      <div className="section-title"><h2>Wenn–dann</h2><span className="muted small">Gruppen von Tagen im Vergleich, nicht um Wochentage bereinigt</span></div>
      <div className="grid-2">
        {items.map((c) => (
          <div key={c.title} className="panel comp">
            <h3>{c.title}</h3>
            <div className="comp-legend"><span><i className="a" />{c.a} ({c.n_a} Tage)</span><span><i className="b" />{c.b} ({c.n_b} Tage)</span></div>
            <div className="table-wrap"><table className="table compact comp-table">
              <tbody>
                {c.rows.map((r) => {
                  const max = Math.max(Math.abs(r.a), Math.abs(r.b)) || 1;
                  return (
                    <tr key={r.key + r.when}>
                      <td><strong>{r.label}</strong><br /><span className="tiny muted">{r.when}</span></td>
                      <td className="comp-bars">
                        <span className="bar a" style={{ width: `${(Math.abs(r.a) / max) * 100}%` }}>{r.a_text}</span>
                        <span className="bar b" style={{ width: `${(Math.abs(r.b) / max) * 100}%` }}>{r.b_text}</span>
                      </td>
                      <td className="num">
                        <span className={`delta ${r.good == null ? "flat" : r.good ? "good" : "bad"}`}>{r.diff_text}</span><br />
                        <span className="tiny muted">{Math.abs(r.d) >= 0.8 ? "starker" : Math.abs(r.d) >= 0.5 ? "mittlerer" : Math.abs(r.d) >= 0.3 ? "kleiner" : "kein klarer"} Unterschied</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table></div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ---------- 5. Wochentage ---------- */

function Patterns({ patterns, stats }) {
  const by = Object.fromEntries(stats.map((s) => [s.key, s]));
  const keys = Object.keys(patterns);
  if (!keys.length) return null;
  return (
    <section id="muster" className="panel analysis-section">
      <div className="panel-head"><h2>Wochentage</h2><span className="tiny muted">grün = besser als dein Schnitt, rot = schlechter</span></div>
      <div className="table-wrap">
        <table className="heat">
          <thead><tr><th />{WEEKDAYS.map((d) => <th key={d}>{d}</th>)}</tr></thead>
          <tbody>
            {keys.map((k) => {
              const p = patterns[k];
              return (
                <tr key={k}>
                  <th>{p.label}</th>
                  {p.weekday.map((v, i) => {
                    const z = v != null && p.sd ? (v - p.mean) / p.sd : 0;
                    const sign = p.better === "down" ? -z : z;
                    const color = p.better ? (sign >= 0 ? "var(--good)" : "var(--signal)") : "var(--iris)";
                    return (
                      <td key={i} style={{ background: v == null ? "transparent" : `color-mix(in srgb, ${color} ${Math.min(80, Math.abs(z) * 70)}%, transparent)` }}
                        title={`${p.n[i]} Tage`}>
                        {v == null ? "–" : fmtMetric(metricOf(by[k]), v, false)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* ---------- 6. Training ---------- */

function Training({ tr }) {
  const zoneTotal = Object.values(tr.zones).reduce((a, b) => a + b, 0) || 1;
  const maxWho = Math.max(150, ...tr.weeks.map((w) => w.who_minutes));
  const maxHour = Math.max(1, ...tr.hours);
  return (
    <section id="training" className="analysis-section">
      <div className="section-title"><h2>Training</h2><span className="muted small">{tr.count} Einheiten · {fmtNum(tr.minutes / 60, 1)} Stunden · Puls Ruhe {tr.hr_rest} / max. {tr.hr_max}</span></div>
      <div className="grid-2">
        <div className="panel">
          <h3>Sportarten nach Trainingslast</h3>
          <div className="table-wrap"><table className="table compact">
            <thead><tr><th>Sport</th><th className="num">Einheiten</th><th className="num">Stunden</th><th>Anteil Last</th><th className="num">Ø Puls</th></tr></thead>
            <tbody>{tr.sports.map((s) => (
              <tr key={s.sport}>
                <td>{s.label}</td><td className="num">{s.count}</td><td className="num">{fmtNum(s.minutes / 60, 1)}</td>
                <td><span className="share-bar"><i style={{ width: `${s.load_share}%` }} /></span> <span className="tiny">{fmtNum(s.load_share, 0)} %</span></td>
                <td className="num">{s.avg_hr ?? "–"}</td>
              </tr>
            ))}</tbody>
          </table></div>
          <h3 className="sub-h">Intensität</h3>
          <div className="zone-bar">
            {Object.entries(tr.zones).map(([k, v]) => v > 0 && <span key={k} className={`z-${k}`} style={{ width: `${(v / zoneTotal) * 100}%` }}>{k} {fmtNum((v / zoneTotal) * 100, 0)} %</span>)}
          </div>
          <p className="tiny muted">Nach Pulsreserve: locker unter 40 %, moderat 40–60 %, intensiv ab 60 %. Ohne Puls nach Sportart geschätzt.</p>
        </div>
        <div className="panel">
          <h3>Wochen: WHO-Minuten und Krafttage</h3>
          <p className="tiny muted" style={{ marginTop: 0 }}>Empfehlung: mindestens 150 Minuten moderat (intensiv zählt doppelt) und 2 Krafttage. Erreicht in {tr.weeks_who_met} von {tr.weeks_full} Wochen.</p>
          <div className="week-cols">
            {tr.weeks.map((w) => (
              <div key={w.week} className={`week-col${w.partial ? " partial" : ""}`} title={`Woche ab ${fmtDate(w.week)}: ${w.who_minutes} WHO-Min., ${w.strength_days} Krafttage, Belastungsverhältnis ${w.acwr ?? "–"}, Monotonie ${w.monotony ?? "–"}`}>
                <div className="wc-track">
                  <span className="wc-goal" style={{ bottom: `${(150 / maxWho) * 100}%` }} />
                  <i className={w.who_minutes >= 150 ? "met" : ""} style={{ height: `${(w.who_minutes / maxWho) * 100}%` }} />
                </div>
                <span className="wc-dots">{"●".repeat(Math.min(4, w.strength_days))}</span>
                <span className="tiny muted">{fmtDayShort(w.week)}</span>
              </div>
            ))}
          </div>
          <div className="table-wrap"><table className="table compact" style={{ marginTop: "0.8rem" }}>
            <thead><tr><th>Woche</th><th className="num">Last</th><th className="num">7:28-Verhältnis</th><th className="num">Monotonie</th></tr></thead>
            <tbody>{tr.weeks.slice(-6).map((w) => (
              <tr key={w.week}>
                <td>{fmtDate(w.week)}</td><td className="num">{w.load}</td>
                <td className="num"><span className={w.acwr > 1.5 ? "delta bad" : w.acwr && w.acwr < 0.8 ? "delta flat" : ""}>{w.acwr != null ? fmtNum(w.acwr, 2) : "–"}</span></td>
                <td className="num"><span className={w.monotony > 2 ? "delta bad" : ""}>{w.monotony != null ? fmtNum(w.monotony, 1) : "–"}</span></td>
              </tr>
            ))}</tbody>
          </table></div>
          <p className="tiny muted">7:28-Verhältnis: Last der Woche gegenüber den 4 Wochen davor (0,8–1,3 gilt als ausgewogen, über 1,5 als sprunghaft). Monotonie über 2: jeden Tag ähnlich viel, wenig Erholung dazwischen.</p>
        </div>
        <div className="panel">
          <h3>Uhrzeit der Trainings</h3>
          <div className="hour-bars">
            {tr.hours.map((n, h) => <span key={h} title={`${h} Uhr: ${n}`}><i style={{ height: `${(n / maxHour) * 100}%` }} /><small>{h % 6 === 0 ? h : ""}</small></span>)}
          </div>
        </div>
        <div className="panel">
          <h3>Muskelgruppen</h3>
          {tr.muscle_groups.length ? tr.muscle_groups.map((g) => (
            <div key={g.group} className="mg-row"><span>{g.group}</span><span className="share-bar"><i style={{ width: `${g.relative}%` }} /></span><span className="tiny muted">{fmtNum(g.points)}</span></div>
          )) : <p className="muted small">Noch keine Daten.</p>}
          <p className="tiny muted">Relativ zur am meisten trainierten Gruppe, Größe der Muskelgruppen berücksichtigt. Krafttraining: {tr.strength.workouts} Einheiten, {fmtNum(tr.strength.volume_kg / 1000, 1)} t bewegt, {tr.strength.prs} Rekorde.</p>
        </div>
      </div>
    </section>
  );
}

/* ---------- 7. Kennzahlen ---------- */

const CAT_LABEL = { recovery: "Erholung", sleep: "Schlaf", heart: "Herz & Kreislauf", activity: "Bewegung", body: "Körper", nutrition: "Ernährung", metabolic: "Stoffwechsel" };

function StatsTable({ stats, days }) {
  const groups = useMemo(() => {
    const g = {};
    stats.forEach((s) => { (g[s.category] ||= []).push(s); });
    return g;
  }, [stats]);
  return (
    <section id="kennzahlen" className="panel analysis-section">
      <div className="panel-head"><h2>Alle Kennzahlen</h2><span className="tiny muted">Trend: Gerade durch alle Tageswerte, je Woche</span></div>
      <div className="table-wrap">
        <table className="table compact stats-table">
          <thead><tr><th>Messgröße</th><th className="num">Ø</th><th className="num">Median</th><th className="num">± Streuung</th><th className="num">Spanne (10–90 %)</th>
            <th className="num">Trend/Woche</th><th className="num">vs. {days} T davor</th><th className="num">Tage</th><th>Quellen</th></tr></thead>
          {Object.entries(groups).map(([cat, list]) => (
            <tbody key={cat}>
              <tr className="group-row"><th colSpan={9} style={{ color: CAT[cat] }}>{CAT_LABEL[cat] || cat}</th></tr>
              {list.map((s) => {
                const m = metricOf(s);
                const cls = s.verdict === "besser" ? "good" : s.verdict === "schlechter" ? "bad" : "flat";
                return (
                  <tr key={s.key}>
                    <td><Link className="link" to={`/metric/${s.key}`}>{s.label}</Link></td>
                    <td className="num"><strong>{fmtMetric(m, s.mean)}</strong></td>
                    <td className="num">{fmtMetric(m, s.median, false)}</td>
                    <td className="num">{s.sd != null ? fmtMetric(m, s.sd, false) : "–"}</td>
                    <td className="num">{fmtMetric(m, s.p10, false)} – {fmtMetric(m, s.p90, false)}</td>
                    <td className="num"><span className={`delta ${cls}`}>{s.slope_week != null ? `${s.slope_week > 0 ? "+" : ""}${fmtMetric({ ...m, decimals: (m.decimals || 0) + 1 }, s.slope_week, false)}` : "–"}</span></td>
                    <td className="num">{s.delta_pct != null ? `${s.delta_pct > 0 ? "+" : ""}${fmtNum(s.delta_pct, 1)} %` : "–"}</td>
                    <td className="num">{s.n}<span className="tiny muted"> ({fmtNum(s.coverage * 100, 0)} %)</span></td>
                    <td className="tiny muted">{s.sources.join(", ")}</td>
                  </tr>
                );
              })}
            </tbody>
          ))}
        </table>
      </div>
    </section>
  );
}

/* ---------- 8. Quellen ---------- */

function Sources({ items }) {
  const multi = items.filter((i) => i.sources.length > 1);
  return (
    <section id="quellen" className="panel analysis-section">
      <div className="panel-head"><h2>Quellen</h2><span className="tiny muted">Reihenfolge = Vorrang (Einstellungen → Datenquellen)</span></div>
      {multi.length > 0 && (
        <>
          <h3 className="sub-h" style={{ marginTop: 0 }}>Wo mehrere Quellen dasselbe messen</h3>
          <ul className="source-agree">
            {multi.map((i) => (
              <li key={i.key}>
                <strong>{i.label}</strong>
                <span>{i.sources.map((s) => `${s.name} ${s.days} T${s.used_days ? ` (genutzt ${s.used_days})` : ""}`).join(" · ")}</span>
                {i.agreement && <span className="small muted">{i.agreement.text}{i.agreement.r != null ? `, Übereinstimmung r ${fmtNum(i.agreement.r, 2)}` : ""}, {i.agreement.days} gemeinsame Tage</span>}
              </li>
            ))}
          </ul>
        </>
      )}
      <h3 className="sub-h">Nur eine Quelle</h3>
      <p className="small">{items.filter((i) => i.sources.length === 1).map((i) => `${i.label} (${i.sources[0].name})`).join(" · ") || "–"}</p>
    </section>
  );
}
