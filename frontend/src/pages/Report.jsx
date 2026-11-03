import { useState } from "react";
import { api } from "../api.js";
import { useWidth } from "../components/charts.jsx";
import { Loading } from "../components/feedback.jsx";
import { EmptyState, useAsync } from "../components/ui.jsx";
import { fmtDate, fmtNum } from "../fmt.js";
import { useDataVersion } from "../refresh.js";

/* Wochen- und Monatsbericht im Stil der WHOOP-Leistungsbewertung. */

const SPORT_COLORS = ["#1f4e79", "#2f6f9f", "#2a9d8f", "#5fd3a6", "#8fe388", "#c3a6ff"];
const ZONE_LABEL = { erholsam: "erholsam", optimal: "optimal", ueber: "über Ziel" };

function hm(min) {
  if (min == null) return "–";
  const m = Math.round(min);
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
}
function vs(cur, base, digits = 0) {
  if (cur == null || base == null) return null;
  const d = cur - base;
  if (Math.abs(d) < 10 ** -digits / 2) return { dir: "flat", text: "gleich" };
  return { dir: d > 0 ? "up" : "down", text: `${d > 0 ? "+" : "−"}${fmtNum(Math.abs(d), digits)}` };
}
function Arrow({ cur, base }) {
  const v = vs(cur, base, 1);
  if (!v || v.dir === "flat") return null;
  return <span className={`rp-arrow ${v.dir}`} aria-hidden="true">{v.dir === "up" ? "▲" : "▼"}</span>;
}
const recColor = (v) => (v == null ? "transparent" : v >= 67 ? "var(--good)" : v >= 34 ? "var(--warn)" : "var(--signal)");

function Nav({ title, sub, prev, next, onGo, running }) {
  return (
    <div className="rp-head">
      <button type="button" className="rp-nav" onClick={() => onGo(prev)} aria-label="Zurück">‹</button>
      <div>
        <div className="rp-kicker">{title}</div>
        <div className="rp-range">{sub}{running && <span className="pill warn" style={{ marginLeft: "0.5rem" }}>läuft noch</span>}</div>
      </div>
      <button type="button" className="rp-nav" onClick={() => next && onGo(next)} disabled={!next} aria-label="Weiter">›</button>
    </div>
  );
}

/* ---------- Woche ---------- */

export function WeekReport() {
  const v = useDataVersion();
  const [start, setStart] = useState(null);
  const [{ data: r, error }] = useAsync(() => api.get(`/report/week${start ? `?start=${start}` : ""}`), [start, v]);
  if (error) return <EmptyState title="Bericht nicht verfügbar" text={error.message} />;
  if (!r) return <Loading rows={4} />;
  const d0 = new Date(`${r.start}T12:00:00`);
  const d1 = new Date(`${r.end}T12:00:00`);
  const range = `${d0.toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" })} – ${d1.toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" })}`;
  const [lHead, lBody] = r.load.text || [];
  return (
    <div className="report">
      <Nav title="Wöchentliche Leistungsbewertung" sub={range} prev={r.prev} next={r.next} onGo={setStart} running={r.running} />
      <section className="rp-hero">
        <h2>{r.headline}</h2>
        <p>{r.text}</p>
      </section>

      <div className="grid-2">
        <section className="panel rp-card">
          <h3 className="rp-title">Tagesbelastung</h3>
          <StrainScatter days={r.days} />
          <p className="tiny muted">Auslastung je Tag gegen die Bereitschaft am Morgen. Das Band zeigt die Auslastung, die zu deiner Bereitschaft passt.</p>
        </section>
        <section className="panel rp-card">
          <h3 className="rp-title">Schlafregelmäßigkeit</h3>
          <SleepScatter days={r.days} />
          <p className="tiny muted">Regelmäßigkeit der Einschlafzeit gegen den Schlafwert der Nacht. Oben rechts ist optimaler Schlaf.</p>
        </section>
      </div>

      <section className="panel rp-card">
        <h3 className="rp-title">Übersicht Belastung</h3>
        {lHead && <p className="rp-lead">{lHead}</p>}
        {lBody && <p className="muted small" style={{ marginTop: 0 }}>{lBody}</p>}
        <div className="rp-compare">
          <div><span className="rp-k">Ø Auslastung</span><strong>{fmtNum(r.load.avg)}<Arrow cur={r.load.avg} base={r.load.base} /></strong><small>3-Wochen-Schnitt {fmtNum(r.load.base)}</small></div>
          <div><span className="rp-k">Aktivitätsdauer</span><strong>{hm(r.load.minutes)}<Arrow cur={r.load.minutes} base={r.load.base_minutes} /></strong><small>{hm(r.load.base_minutes)} im Schnitt</small></div>
          <div><span className="rp-k">Aktivitäten</span><strong>{r.load.count}<Arrow cur={r.load.count} base={r.load.base_count} /></strong><small>{fmtNum(r.load.base_count, 1)} im Schnitt</small></div>
        </div>
        {r.sports.length > 0 && (
          <div className="rp-sports">
            <div className="rp-k">Ø Auslastung je Aktivität</div>
            {r.sports.map((s, i) => (
              <div key={s.sport} className="rp-sport">
                <span>{s.label} <small className="muted">{s.count}× · {hm(s.minutes)}</small></span>
                <span className="rp-bar"><i style={{ width: `${s.avg_load}%`, background: SPORT_COLORS[i % SPORT_COLORS.length] }} /></span>
                <b>{fmtNum(s.avg_load)}</b>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel rp-card">
        <h3 className="rp-title">Deine Woche Tag für Tag</h3>
        <div className="table-wrap">
          <table className="table compact rp-days">
            <thead><tr><th /><th className="num">Bereitschaft</th><th className="num">Auslastung</th><th>Ziel</th><th className="num">Schlafwert</th><th className="num">Schlaf / Bedarf</th><th className="num">HRV</th><th className="num">Ruhepuls</th><th className="num">Schritte</th></tr></thead>
            <tbody>{r.days.map((d) => (
              <tr key={d.day}>
                <th>{d.wd} <span className="tiny muted">{fmtDate(d.day).replace(/ \d{4}$/, "")}</span></th>
                <td className="num"><span className="rp-dot" style={{ background: recColor(d.readiness) }} />{d.readiness ?? "–"}</td>
                <td className="num">{d.load}</td>
                <td><span className={`rp-zone z-${d.zone || "none"}`}>{ZONE_LABEL[d.zone] || "–"}</span> <span className="tiny muted">{d.target[0]}–{d.target[1]}</span></td>
                <td className="num">{d.sleep ?? "–"}</td>
                <td className="num">{hm(d.asleep)} <span className="tiny muted">/ {hm(d.need)}</span></td>
                <td className="num">{d.hrv ?? "–"}</td>
                <td className="num">{d.rhr ?? "–"}</td>
                <td className="num">{d.steps != null ? fmtNum(d.steps) : "–"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>

      <div className="rp-vitals">
        {[["readiness", "Bereitschaft", ""], ["sleep", "Schlafwert", ""], ["hrv", "HRV", "ms"], ["rhr", "Ruhepuls", "bpm"], ["steps", "Schritte", ""]].map(([k, l, u]) => {
          const x = r.vitals[k];
          if (!x || x.week == null) return null;
          const c = vs(x.week, x.base);
          const good = k === "rhr" ? c?.dir === "down" : c?.dir === "up";
          return (
            <div key={k} className="panel rp-vital">
              <span className="rp-k">{l}</span>
              <strong>{fmtNum(x.week)} <small>{u}</small></strong>
              {c && <span className={`delta ${c.dir === "flat" ? "flat" : good ? "good" : "bad"}`}>{c.text} gegenüber 3 Wochen</span>}
            </div>
          );
        })}
        <div className="panel rp-vital">
          <span className="rp-k">Schlaf je Nacht</span>
          <strong>{hm(r.sleep_hours.asleep)}</strong>
          <span className="muted small">Bedarf {hm(r.sleep_hours.need)}</span>
        </div>
      </div>
      {(r.best || r.worst) && (
        <p className="small muted">Bester Tag: {r.best ? `${r.best.wd} (Bereitschaft ${r.best.readiness})` : "–"} · Schwierigster Tag: {r.worst ? `${r.worst.wd} (Bereitschaft ${r.worst.readiness})` : "–"}</p>
      )}
    </div>
  );
}

function band(x) {
  return x >= 70 ? [55, 85] : x >= 45 ? [35, 65] : [10, 35];
}

function Scatter({ points, xLabel, yLabel, xTicks, yTicks, optimal, optimalLabel, xColors, left = 34 }) {
  const [ref, width] = useWidth(420);
  const H = 260, L = left, B = 34, T = 14, R = 10;
  const x = (v) => L + (v / 100) * (width - L - R);
  const y = (v) => T + (1 - v / 100) * (H - T - B);
  return (
    <div ref={ref} className="rp-scatter">
      <svg width={width} height={H}>
        {[0, 20, 40, 60, 80, 100].map((g) => <line key={`x${g}`} x1={x(g)} x2={x(g)} y1={T} y2={H - B} className="rp-grid" />)}
        {[0, 20, 40, 60, 80, 100].map((g) => <line key={`y${g}`} x1={L} x2={width - R} y1={y(g)} y2={y(g)} className="rp-grid" />)}
        {optimal && <path d={optimal(x, y)} className="rp-optimal" />}
        {optimalLabel && <text x={optimalLabel[0](x)} y={optimalLabel[1](y)} className="rp-optimal-label" textAnchor="middle">{optimalLabel[2]}</text>}
        {xColors && xColors.map(([a, b, c]) => <line key={a} x1={x(a)} x2={x(b)} y1={H - B} y2={H - B} stroke={c} strokeWidth="3" />)}
        {xTicks.map(([v, l]) => <text key={v} x={x(v)} y={H - B + 16} className="rp-tick" textAnchor="middle">{l}</text>)}
        {yTicks.map(([v, l]) => <text key={v} x={L - 6} y={y(v) + 3} className="rp-tick" textAnchor="end">{l}</text>)}
        <text x={width - R} y={H - 2} className="rp-axis" textAnchor="end">{xLabel}</text>
        <text x={L} y={T - 1} className="rp-axis">{yLabel}</text>
        {points.map((p) => (
          <g key={p.label}>
            <circle cx={x(p.x)} cy={y(p.y)} r="6" className="rp-point" />
            <text x={x(p.x)} y={y(p.y) + 18} className="rp-point-label" textAnchor="middle">{p.label}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function StrainScatter({ days }) {
  const pts = days.filter((d) => d.readiness != null).map((d) => ({ x: d.readiness, y: d.load, label: d.wd }));
  const optimal = (x, y) => {
    const top = [], bot = [];
    for (let v = 0; v <= 100; v += 1) { const [lo, hi] = band(v); top.push(`${x(v)},${y(hi)}`); bot.unshift(`${x(v)},${y(lo)}`); }
    return `M${top.join("L")}L${bot.join("L")}Z`;
  };
  return <Scatter points={pts} xLabel="Bereitschaft" yLabel="Auslastung" optimal={optimal}
    optimalLabel={[(x) => x(57), (y) => y(52), "OPTIMAL"]}
    xTicks={[[0, "0"], [34, "34"], [67, "67"], [100, "100"]]} yTicks={[[0, "0"], [25, "25"], [50, "50"], [75, "75"], [100, "100"]]}
    xColors={[[0, 34, "var(--signal)"], [34, 67, "var(--warn)"], [67, 100, "var(--good)"]]} />;
}

function SleepScatter({ days }) {
  const pts = days.filter((d) => d.sleep != null).map((d) => ({ x: d.sleep, y: d.consistency ?? 50, label: d.wd }));
  const optimal = (x, y) => `M${x(80)},${y(100)}L${x(100)},${y(100)}L${x(100)},${y(70)}L${x(80)},${y(70)}Z`;
  return <Scatter points={pts} xLabel="Schlafwert" yLabel="Regelmäßigkeit" optimal={optimal}
    optimalLabel={[(x) => x(90), (y) => y(84), "OPTIMAL"]}
    xTicks={[[10, "10"], [30, "30"], [50, "50"], [70, "70"], [85, "85"], [100, "100"]]}
    yTicks={[[25, "ungenügend"], [60, "ausreichend"], [95, "maximal"]]} left={78} />;
}

/* ---------- Monat ---------- */

export function MonthReport() {
  const v = useDataVersion();
  const [month, setMonth] = useState(null);
  const [{ data: r, error }] = useAsync(() => api.get(`/report/month${month ? `?month=${month}` : ""}`), [month, v]);
  if (error) return <EmptyState title="Bericht nicht verfügbar" text={error.message} />;
  if (!r) return <Loading rows={4} />;
  const keys = r.training.sports.map((s) => s.key);
  const color = (k) => (k === "_rest" ? "#9aa6b8" : SPORT_COLORS[keys.indexOf(k) % SPORT_COLORS.length]);
  const ex = r.extra;
  return (
    <div className="report">
      <Nav title="Monatliche Leistungsanalyse" sub={r.title} prev={r.prev} next={r.next} onGo={setMonth} running={r.running} />

      {(ex.bullets.length > 0 || ex.compare.length > 0) && (
        <section className="panel rp-card">
          <h3 className="rp-title">Auf einen Blick</h3>
          {ex.bullets.length > 0 && <ul className="rp-bullets">{ex.bullets.map((b) => <li key={b.text} className={b.good ? "good" : "bad"}>{b.text}</li>)}</ul>}
          <div className="rp-mini-grid">
            {ex.compare.map((c) => (
              <div key={c.key}>
                <span className="rp-k">{c.label}</span>
                <strong>{c.unit === "min" ? hm(c.cur) : fmtNum(c.cur)} <small>{c.unit !== "min" ? c.unit : ""}</small></strong>
                <small className="muted">{r.prev_title}: {c.unit === "min" ? hm(c.prev) : fmtNum(c.prev)}{c.change != null ? ` (${c.change > 0 ? "+" : ""}${c.change} %)` : ""}</small>
              </div>
            ))}
          </div>
          <div className="rp-zonebar">
            <span className="rec-g" style={{ flex: ex.recovery_colors.green || 0.001 }}>{ex.recovery_colors.green} grün</span>
            <span className="rec-y" style={{ flex: ex.recovery_colors.yellow || 0.001 }}>{ex.recovery_colors.yellow} gelb</span>
            <span className="rec-r" style={{ flex: ex.recovery_colors.red || 0.001 }}>{ex.recovery_colors.red} rot</span>
          </div>
          <p className="tiny muted">Tage nach Bereitschaft (grün ab 67, rot unter 34). Belastung passend zur Bereitschaft: {ex.zone_counts.optimal} Tage optimal, {ex.zone_counts.erholsam} erholsam, {ex.zone_counts.ueber} darüber.</p>
          {ex.body.length > 0 && (
            <p className="small">{ex.body.map((b) => `${b.label} ${fmtNum(b.cur, 1)}${b.change != null ? ` (${b.change > 0 ? "+" : ""}${fmtNum(b.change, 1)})` : ""}`).join(" · ")}</p>
          )}
        </section>
      )}

      <section className="panel rp-card">
        <div className="rp-split">
          <div>
            <h3 className="rp-title">Erholsamer Schlaf</h3>
            <p className="small muted">Erholsamer Schlaf ist <b>REM</b> (geistige Erholung, das Gehirn sortiert Erinnerungen) und <b>Tiefschlaf</b> (körperliche Erholung). Am meisten davon bekommst du, wenn deine Schlafstunden zu deinem Schlafbedarf passen.</p>
          </div>
          <RestorativeCompare r={r} />
        </div>
        <h4 className="rp-sub">Geschlafene Stunden und Schlafbedarf</h4>
        <NeedChart days={r.restorative.days} />
        <h4 className="rp-sub">Erholsamer Schlaf (REM + Tiefschlaf)</h4>
        <StageBars days={r.restorative.days} />
      </section>

      <section className="panel rp-card">
        <h3 className="rp-title">Trainingsübersicht</h3>
        <div className="chips" style={{ marginBottom: "0.6rem" }}>
          {r.training.sports.map((s) => <span key={s.key} className="rp-legend"><i style={{ background: color(s.key) }} />{s.label}</span>)}
          <span className="rp-legend"><i style={{ background: "var(--panel-2)", border: "1px solid var(--line-2)" }} />Alltag</span>
        </div>
        <div className="rp-split">
          <div>
            <div className="rp-k">Auslastung nach Wochentag</div>
            {r.training.weekday.map((w) => {
              const max = Math.max(1, ...r.training.weekday.map((x) => x.total));
              return (
                <div key={w.wd} className="rp-wd">
                  <span>{w.wd}</span>
                  <span className="rp-stack">
                    {keys.map((k) => w.parts[k] > 0 && <i key={k} style={{ width: `${(w.parts[k] / max) * 100}%`, background: color(k) }} />)}
                    {w.rest > 0 && <i className="rest" style={{ width: `${(w.rest / max) * 100}%` }} />}
                  </span>
                  <b>{fmtNum(w.total, 1)}</b>
                </div>
              );
            })}
          </div>
          <div className="rp-mini-grid two">
            {[["Anzahl der Aktivitäten", r.training.total.count, r.training.prev.count, (s) => `${s.label}: ${s.count}×`, (x) => x],
              ["Ø Auslastung je Aktivität", r.training.total.avg_load, r.training.prev.avg_load, (s) => `${s.label}: ${fmtNum(s.avg_load, 1)}`, (x) => fmtNum(x, 1)],
              ["Gesamte Aktivitätsdauer", r.training.total.minutes, r.training.prev.minutes, (s) => `${s.label}: ${hm(s.minutes)}`, hm],
              ["Ø Aktivitätsdauer", r.training.total.avg_minutes, r.training.prev.avg_minutes, (s) => `${s.label}: ${hm(s.avg_minutes)}`, hm]].map(([l, cur, prev, line, f]) => (
              <div key={l}>
                <span className="rp-k">{l}</span>
                <strong>{f(cur)}<Arrow cur={cur} base={prev} /></strong>
                <small className="muted">vgl. mit {f(prev)} im {r.prev_title}</small>
                <ul className="rp-list">{r.training.sports.map((s) => <li key={s.key} style={{ color: color(s.key) }}><span>{line(s)}</span></li>)}</ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="grid-2">
        <section className="panel rp-card">
          <h3 className="rp-title">Herzfrequenz-Zonen</h3>
          <p className="tiny muted" style={{ marginTop: 0 }}>Zeit in den Zonen (% der maximalen Herzfrequenz {r.training.zones.hr_max}), nach Sportart.{r.training.zones.estimated ? ` ${r.training.zones.estimated} Einheiten ohne Pulsverlauf nach Durchschnittspuls geschätzt.` : ""}</p>
          {[...r.training.zones.labels].reverse().map((l, ri) => {
            const i = 5 - ri;
            const row = r.training.zones.rows[i];
            const max = Math.max(1, ...r.training.zones.totals);
            return (
              <div key={l} className="rp-wd">
                <span>{l}</span>
                <span className="rp-stack">{keys.map((k) => row[k] > 0 && <i key={k} style={{ width: `${(row[k] / max) * 100}%`, background: color(k) }} />)}</span>
                <b>{hm(r.training.zones.totals[i])}</b>
              </div>
            );
          })}
        </section>
        <section className="panel rp-card">
          <h3 className="rp-title">Trainingsintensität</h3>
          <p className="tiny muted" style={{ marginTop: 0 }}>Wie lange du für welche Auslastung gebraucht hast. Daran siehst du, welche Sportart dich schnell an dein Tagesziel bringt.</p>
          <IntensityScatter items={r.training.intensity} color={color} />
        </section>
      </div>

      <section className="panel rp-card">
        <h3 className="rp-title">Das Jahr im Überblick</h3>
        <YearHeat cal={r.calendar} k="load" title="Auslastung" color={(v) => (v ? `color-mix(in srgb, #2f8fdc ${Math.min(100, 15 + v)}%, var(--panel-2))` : "var(--panel-2)")} note="dunkler = mehr Belastung" />
        <YearHeat cal={r.calendar} k="readiness" title="Bereitschaft" color={(v) => (v == null ? "var(--panel-2)" : recColor(v))} note="grün hoch · gelb normal · rot niedrig" />
        <YearHeat cal={r.calendar} k="sleep" title="Schlafwert" color={(v) => (v == null ? "var(--panel-2)" : `color-mix(in srgb, #7fa0c8 ${Math.max(10, v - 20)}%, var(--panel-2))`)} note="dunkler = besserer Schlaf" />
      </section>

      <section className="panel rp-card">
        <h3 className="rp-title">Trainingsverhalten</h3>
        <p className="tiny muted" style={{ marginTop: 0 }}>7-Tage-Schnitt, wie deine Auslastung zum Zielbereich deiner Bereitschaft passte. Überanstrengung: mehr als empfohlen. Optimal: ausgeglichen. Erholsam: weniger als möglich.</p>
        <Behaviour data={r.behaviour} />
      </section>

      <section className="panel rp-card">
        <h3 className="rp-title">Physiologische Reaktion</h3>
        <p className="tiny muted" style={{ marginTop: 0 }}>Steigende HRV und sinkender Ruhepuls sind Zeichen besserer Fitness. Grün = Verbesserung, rot = Verschlechterung, schwarz = kaum Änderung, grau = zu wenige Daten (unter 10 Tage).</p>
        <Physio title="HRV-Anpassung" days={r.physio.hrv_days} months={r.physio.hrv} unit="ms" />
        <Physio title="Ruhepuls-Anpassung" days={r.physio.rhr_days} months={r.physio.rhr} unit="bpm" />
      </section>
    </div>
  );
}

function RestorativeCompare({ r }) {
  const x = r.restorative;
  const max = Math.max(1, ...x.need.filter(Boolean), ...x.asleep.filter(Boolean));
  const rmax = Math.max(1, ...x.deep.map((d, i) => (d || 0) + (x.rem[i] || 0)));
  const short = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sept.", "Okt.", "Nov.", "Dez."];
  const labels = [short[(r.month + 10) % 12], short[r.month - 1]];
  return (
    <div className="rp-rc">
      <div className="rp-rc-group">
        {[0, 1].map((i) => (
          <div key={i} className="rp-rc-col">
            <div className="rp-rc-bar" style={{ height: 120 }}>
              <i className="need" style={{ height: `${((x.need[i] || 0) / max) * 100}%` }} />
              <i className="asleep" style={{ height: `${((x.asleep[i] || 0) / max) * 100}%` }} />
            </div>
            <small>{labels[i]}</small><b className="c-need">{hm(x.need[i])}</b><b>{hm(x.asleep[i])}</b>
          </div>
        ))}
      </div>
      <div className="rp-rc-group">
        {[0, 1].map((i) => (
          <div key={i} className="rp-rc-col">
            <div className="rp-rc-bar stack" style={{ height: 120 }}>
              <i className="rem" style={{ height: `${((x.rem[i] || 0) / rmax) * 60}%` }} />
              <i className="deep" style={{ height: `${((x.deep[i] || 0) / rmax) * 60}%` }} />
            </div>
            <small>{labels[i]}</small><b className="c-rem">{hm(x.rem[i])}</b><b>{hm(x.deep[i])}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

function NeedChart({ days }) {
  const [ref, width] = useWidth(700);
  const H = 180, B = 30, T = 8, L = 34;
  const max = Math.max(600, ...days.map((d) => Math.max(d.need || 0, d.asleep || 0)));
  const x = (i) => L + (i + 0.5) * ((width - L) / days.length);
  const y = (v) => T + (1 - v / max) * (H - T - B);
  const line = (k) => days.map((d, i) => (d[k] == null ? null : `${x(i)},${y(d[k])}`)).filter(Boolean).join("L");
  return (
    <div ref={ref} className="rp-chart">
      <svg width={width} height={H}>
        {[0, 120, 240, 360, 480, 600].filter((v) => v <= max).map((v) => (
          <g key={v}><line x1={L} x2={width} y1={y(v)} y2={y(v)} className="rp-grid" /><text x={L - 5} y={y(v) + 3} className="rp-tick" textAnchor="end">{v / 60}:00</text></g>
        ))}
        <path d={`M${line("need")}`} className="rp-line need" />
        <path d={`M${line("asleep")}`} className="rp-line asleep" />
        {days.map((d, i) => d.asleep != null && <circle key={`a${i}`} cx={x(i)} cy={y(d.asleep)} r="2.6" className="rp-dot-asleep" />)}
        {days.map((d, i) => d.need != null && <circle key={`n${i}`} cx={x(i)} cy={y(d.need)} r="2.6" className="rp-dot-need" />)}
        {days.map((d, i) => <text key={d.day} x={x(i)} y={H - 16} className="rp-tick" textAnchor="middle">{d.wd}</text>)}
        {days.map((d, i) => <text key={`n${d.day}`} x={x(i)} y={H - 4} className="rp-tick" textAnchor="middle">{Number(d.day.slice(8))}</text>)}
      </svg>
      <div className="rp-legend-row"><span className="rp-legend"><i className="c-need-bg" />Schlafbedarf</span><span className="rp-legend"><i className="c-asleep-bg" />Schlafstunden</span></div>
    </div>
  );
}

function StageBars({ days }) {
  const max = Math.max(240, ...days.map((d) => (d.deep || 0) + (d.rem || 0)));
  return (
    <div className="rp-stagebars">
      {days.map((d) => (
        <div key={d.day} title={`${fmtDate(d.day)}: Tiefschlaf ${hm(d.deep)}, REM ${hm(d.rem)}`}>
          <span className="col"><i className="rem" style={{ height: `${((d.rem || 0) / max) * 100}%` }} /><i className="deep" style={{ height: `${((d.deep || 0) / max) * 100}%` }} /></span>
          <small>{d.wd}</small><small>{Number(d.day.slice(8))}</small>
        </div>
      ))}
      <div className="rp-legend-row"><span className="rp-legend"><i style={{ background: "#1d3346" }} />Tiefschlaf</span><span className="rp-legend"><i style={{ background: "#7fa3c4" }} />REM</span></div>
    </div>
  );
}

function IntensityScatter({ items, color }) {
  const [ref, width] = useWidth(420);
  const H = 240, L = 30, B = 26, T = 8, R = 8;
  const maxMin = Math.max(60, ...items.map((i) => i.minutes));
  const x = (m) => L + (m / maxMin) * (width - L - R);
  const y = (v) => T + (1 - v / 100) * (H - T - B);
  const ticks = [];
  for (let m = 60; m <= maxMin; m += 60) ticks.push(m);
  return (
    <div ref={ref}>
      <svg width={width} height={H}>
        {[[85, "maximal"], [60, "anstrengend"], [35, "moderat"], [10, "leicht"]].map(([v, l]) => (
          <g key={v}><line x1={L} x2={width - R} y1={y(v)} y2={y(v)} className="rp-grid" /><text x={L + 3} y={y(v) - 3} className="rp-tick">{l}</text></g>
        ))}
        {ticks.map((m) => <text key={m} x={x(m)} y={H - 8} className="rp-tick" textAnchor="middle">{m / 60}:00</text>)}
        {items.map((it, i) => <circle key={i} cx={x(it.minutes)} cy={y(it.load)} r="4.5" fill="none" stroke={color(it.sport)} strokeWidth="2.2"><title>{`${it.name || ""} ${fmtDate(it.day)}: ${hm(it.minutes)}, Auslastung ${fmtNum(it.load)}`}</title></circle>)}
      </svg>
    </div>
  );
}

function YearHeat({ cal, k, title, color, note }) {
  const weeks = Math.ceil(cal.days.length / 7);
  const wd = ["M", "D", "M", "D", "F", "S", "S"];
  return (
    <div className="rp-year">
      <div className="rp-year-head"><h4 className="rp-sub" style={{ margin: 0 }}>{title}</h4><span className="tiny muted">{note}</span></div>
      <div className="rp-year-body">
        <div className="rp-year-wd">{wd.map((l, i) => <span key={i}>{l} <b>{cal.weekday[k][i] != null ? `${cal.weekday[k][i]}` : ""}</b></span>)}</div>
        <div className="rp-year-grid" style={{ gridTemplateColumns: `repeat(${weeks}, minmax(2px, 1fr))` }}>
          {cal.days.map((d, i) => (
            <span key={d.day} style={{ gridColumn: Math.floor(i / 7) + 1, gridRow: (i % 7) + 1, background: color(d[k]) }} title={`${fmtDate(d.day)}: ${d[k] ?? "–"}`} />
          ))}
        </div>
      </div>
      <div className="rp-year-months">
        <span className="rp-k">Dein Schnitt</span>
        {cal.months.map((m) => <span key={m.start}><small>{m.month}</small><b>{m[k] ?? "–"}</b></span>)}
      </div>
    </div>
  );
}

function Behaviour({ data }) {
  const [ref, width] = useWidth(700);
  const H = 160, T = 6, B = 22;
  if (!data.length) return <p className="muted small">Noch zu wenige Tage mit Bereitschaft.</p>;
  const clip = (v) => Math.max(-2.5, Math.min(2.5, v));
  const x = (i) => (i / Math.max(1, data.length - 1)) * width;
  const y = (v) => T + (1 - (clip(v) + 2.5) / 5) * (H - T - B);
  const line = data.map((p, i) => `${x(i)},${y(p.value)}`).join("L");
  const below = `M${x(0)},${y(-1)}L${data.map((p, i) => `${x(i)},${y(Math.min(-1, p.value))}`).join("L")}L${x(data.length - 1)},${y(-1)}Z`;
  const above = `M${x(0)},${y(1)}L${data.map((p, i) => `${x(i)},${y(Math.max(1, p.value))}`).join("L")}L${x(data.length - 1)},${y(1)}Z`;
  const months = [];
  data.forEach((p, i) => { if (p.day.endsWith("-01")) months.push([i, new Date(`${p.day}T12:00:00`).toLocaleDateString("de-DE", { month: "short", year: "2-digit" })]); });
  return (
    <div ref={ref} className="rp-chart">
      <svg width={width} height={H}>
        <rect x="0" y={y(1)} width={width} height={y(-1) - y(1)} className="rp-band" />
        <text x="4" y={y(1.8)} className="rp-tick over">ÜBERANSTRENGUNG</text>
        <text x="4" y={y(0) + 3} className="rp-tick">OPTIMAL</text>
        <text x="4" y={y(-1.8)} className="rp-tick under">ERHOLSAM</text>
        <path d={above} className="rp-fill-over" />
        <path d={below} className="rp-fill-under" />
        <path d={`M${line}`} className="rp-line behav" />
        {months.map(([i, l]) => <text key={i} x={x(i)} y={H - 4} className="rp-tick" textAnchor="middle">{l}</text>)}
      </svg>
    </div>
  );
}

function Physio({ title, days, months, unit }) {
  const [ref, width] = useWidth(700);
  const H = 170, T = 24, B = 22, L = 30;
  if (!days.length) return <p className="muted small">{title}: noch keine Daten.</p>;
  const vals = days.map((d) => d.value);
  const lo = Math.min(...vals) - 3, hi = Math.max(...vals) + 3;
  const t0 = new Date(`${months[0].start}T00:00:00`).getTime();
  const t1 = new Date(`${months[months.length - 1].end}T23:59:59`).getTime();
  const x = (iso) => L + ((new Date(`${iso}T12:00:00`).getTime() - t0) / (t1 - t0)) * (width - L - 6);
  const y = (v) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  const path = days.map((d, i) => `${i ? "L" : "M"}${x(d.day)},${y(d.value)}`).join("");
  const col = { gruen: "var(--good)", rot: "var(--signal)", schwarz: "var(--chalk)", grau: "var(--mute)" };
  return (
    <div ref={ref} className="rp-chart">
      <h4 className="rp-sub">{title}</h4>
      <svg width={width} height={H}>
        <path d={path} className="rp-line physio" />
        {months.map((m) => m.avg != null && (
          <g key={m.start}>
            <line x1={x(m.start)} x2={x(m.end)} y1={y(m.avg)} y2={y(m.avg)} stroke={col[m.status]} strokeWidth="2.5" />
            <text x={x(m.start) + 2} y={y(m.avg) - 6} className="rp-tick strong">{m.avg} {unit}</text>
            {m.change != null && <text x={x(m.start) + 2} y={y(m.avg) + 13} className="rp-tick" fill={col[m.status]}>{m.change > 0 ? "+" : ""}{m.change} %</text>}
            <text x={(x(m.start) + x(m.end)) / 2} y={H - 4} className="rp-tick" textAnchor="middle">{m.month}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}
