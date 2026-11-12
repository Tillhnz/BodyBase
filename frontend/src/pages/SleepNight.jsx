import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { StageBar, useWidth } from "../components/charts.jsx";
import HrChart from "../components/HrChart.jsx";
import { Loading } from "../components/feedback.jsx";
import { EmptyState, Kpi, useAsync } from "../components/ui.jsx";
import { fmtDay, fmtMinutes, fmtNum, fmtTime } from "../fmt.js";
import { useDataVersion } from "../refresh.js";

/* Eine Nacht im Detail. */

const ROWS = [["awake", "Wach"], ["rem", "REM"], ["light", "Leicht"], ["deep", "Tief"]];

function Hypnogram({ night }) {
  const [ref, width] = useWidth(700);
  const H = 170, L = 52, T = 6, B = 22, R = 6;
  const total = night.in_bed_min;
  const x = (m) => L + (m / total) * (width - L - R);
  const rowH = (H - T - B) / ROWS.length;
  const y = (k) => T + ROWS.findIndex(([r]) => r === k) * rowH;
  const start = new Date(night.start);
  const ticks = [];
  const first = 60 - start.getMinutes();
  for (let m = first; m < total; m += 60) ticks.push(m);
  const step = Math.ceil(ticks.length / Math.max(2, Math.floor(width / 70)));
  return (
    <div ref={ref} className="hypno">
      <svg width={width} height={H} role="img" aria-label="Schlafphasen im Verlauf">
        {ROWS.map(([k, l]) => (
          <g key={k}>
            <line x1={L} x2={width - R} y1={y(k) + rowH / 2} y2={y(k) + rowH / 2} className="rp-grid" />
            <text x={L - 8} y={y(k) + rowH / 2 + 4} className="rp-tick" textAnchor="end">{l}</text>
          </g>
        ))}
        {night.stages.map(([a, b, k], i) => (
          <rect key={i} x={x(a)} y={y(k) + 3} width={Math.max(1, x(b) - x(a))} height={rowH - 6} rx="2" className={`st-${k}`} />
        ))}
        {ticks.filter((_, i) => i % step === 0).map((m) => {
          const t = new Date(start.getTime() + m * 60000);
          return <text key={m} x={x(m)} y={H - 4} className="rp-tick" textAnchor="middle">{`${String(t.getHours()).padStart(2, "0")}:00`}</text>;
        })}
      </svg>
    </div>
  );
}

function diffText(cur, base, unit = "", better = "up", digits = 0) {
  if (cur == null || base == null) return null;
  const d = cur - base;
  if (Math.abs(d) < 10 ** -digits / 2) return <span className="delta flat">wie üblich</span>;
  const good = (d > 0) === (better === "up");
  return <span className={`delta ${good ? "good" : "bad"}`}>{d > 0 ? "+" : "−"}{fmtNum(Math.abs(d), digits)}{unit} zum Schnitt</span>;
}

export default function SleepNight() {
  const { day } = useParams();
  const navigate = useNavigate();
  const v = useDataVersion();
  const [{ data: n, error }] = useAsync(() => api.get(`/sleep/night/${day}`), [day, v]);
  if (error) return <EmptyState title="Nacht nicht gefunden" text={error.message}><Link className="btn" to="/sleep">Zurück</Link></EmptyState>;
  if (!n) return <Loading rows={3} />;
  const m = n.main;
  const wk = n.week_avg;
  const better = { respiratory_rate: "down", resting_hr: "down", spo2: "up", hrv: "up", skin_temp_dev: "down" };
  return (
    <div className="cat-sleep sleep-night">
      <div className="page-head">
        <div>
          <p style={{ margin: 0 }}><Link className="link quiet small" to="/sleep">Schlaf</Link></p>
          <h1>Nacht zum {fmtDay(n.day)}</h1>
          {m && <p>{fmtTime(m.start)} – {fmtTime(m.end)} · {m.source_name}{n.sessions.filter((s) => !s.nap).length > 1 ? ` (bevorzugte von ${n.sessions.filter((s) => !s.nap).length} Quellen)` : ""}</p>}
        </div>
        <div className="actions">
          <button type="button" className="btn" disabled={!n.prev} onClick={() => navigate(`/sleep/${n.prev}`)}>‹ Nacht davor</button>
          <button type="button" className="btn" disabled={!n.next} onClick={() => navigate(`/sleep/${n.next}`)}>Nacht danach ›</button>
        </div>
      </div>
      {!m ? <EmptyState title="Keine Schlafdaten in dieser Nacht" text="Für diesen Tag gibt es nur Tageswerte oder gar nichts." /> : (
        <>
          <div className="kpis">
            <Kpi label="Geschlafen" value={fmtMinutes(m.asleep_min)} sub={wk.asleep != null ? `Schnitt ${fmtMinutes(wk.asleep)}` : null} />
            <Kpi label="Im Bett" value={fmtMinutes(m.in_bed_min)} />
            <Kpi label="Bedarf" value={fmtMinutes(n.need)} sub={[n.debt != null ? (n.debt > 0 ? `${fmtMinutes(n.debt)} zu wenig` : "gedeckt") : null, ...(n.need_parts || []).filter((p) => p.key !== "base").map((p) => `+${p.min} ${p.label}`)].filter(Boolean).join(" · ") || null} />
            {n.score && <Kpi label="Schlafwert" value={fmtNum(n.score.value)} sub={wk.sleep != null ? `Schnitt ${fmtNum(wk.sleep)}` : null} />}
            {m.score != null && <Kpi label={`Wert ${m.source_name}`} value={fmtNum(m.score)} />}
            {n.readiness && <Kpi label="Bereitschaft danach" value={fmtNum(n.readiness.value)} />}
          </div>

          <section className="panel">
            <div className="panel-head"><h2>Schlafphasen</h2>
              <div className="stage-legend" style={{ margin: 0 }}><span><i className="st-deep" />Tief</span><span><i className="st-light" />Leicht</span><span><i className="st-rem" />REM</span><span><i className="st-awake" />Wach</span></div>
            </div>
            {m.stages?.length ? <Hypnogram night={m} /> : <p className="muted small">Diese Quelle liefert keinen Verlauf der Phasen, nur die Summen.</p>}
            {m.deep_min != null && (
              <>
                <StageBar deep={m.deep_min} rem={m.rem_min} light={m.light_min} awake={m.awake_min} />
                <div className="night-stages">
                  {[["deep_min", "Tief", wk.deep], ["rem_min", "REM", wk.rem], ["light_min", "Leicht", null], ["awake_min", "Wach", null]].map(([k, l, base]) => (
                    <div key={k}>
                      <span className="rp-k">{l}</span>
                      <strong>{fmtMinutes(m[k])}</strong>
                      <small className="muted">{m.asleep_min && m[k] != null && k !== "awake_min" ? `${fmtNum((m[k] / m.asleep_min) * 100)} % · ` : ""}{base != null ? `Schnitt ${fmtMinutes(base)}` : ""}</small>
                    </div>
                  ))}
                </div>
              </>
            )}
          </section>

          {n.hr && (
            <section className="panel">
              <div className="panel-head"><h2>Puls in der Nacht</h2><span className="tiny muted">{n.hr.source}</span></div>
              <HrChart series={n.hr} height={170} />
            </section>
          )}

          <div className="grid-2">
            {n.score && (
              <section className="panel">
                <div className="panel-head"><h2>Schlafwert {fmtNum(n.score.value)}</h2><span className="tiny muted">So setzt er sich zusammen</span></div>
                <ul className="score-parts" style={{ borderTop: 0, paddingTop: 0, "--c": "var(--c-sleep)" }}>
                  {n.score.parts.map((p) => (
                    <li key={p.key}><span className="lbl">{p.label}</span><span className="bar"><i style={{ width: `${p.score}%` }} /></span><span className="num">{p.score}</span><span className="txt">{p.text}</span></li>
                  ))}
                </ul>
              </section>
            )}
            <section className="panel">
              <div className="panel-head"><h2>Körper in der Nacht</h2><span className="tiny muted">gegenüber 30 Tagen</span></div>
              {Object.keys(n.metrics).length ? (
                <table className="table compact"><tbody>
                  {Object.entries(n.metrics).map(([k, x]) => (
                    <tr key={k}><td>{x.label}</td><td className="num"><strong>{fmtNum(x.value, k === "skin_temp_dev" || k === "respiratory_rate" ? 1 : 0)} {x.unit}</strong></td>
                      <td className="num">{diffText(x.value, x.avg30, ` ${x.unit}`, better[k], k === "skin_temp_dev" || k === "respiratory_rate" ? 1 : 0)}</td></tr>
                  ))}
                </tbody></table>
              ) : <p className="muted small">Keine Werte für HRV, Ruhepuls, Atemfrequenz oder SpO₂.</p>}
              <h3 className="sub-h">Am Tag davor</h3>
              <p className="small" style={{ margin: 0 }}>Auslastung {fmtNum(n.prev_load)}{n.late_training.length ? ` · spätes Training: ${n.late_training.map((t) => `${t.name} bis ${t.end}`).join(", ")}` : " · kein spätes Training"}</p>
            </section>
          </div>

          {n.sessions.length > 1 && (
            <section className="panel">
              <div className="panel-head"><h2>Alle Quellen dieser Nacht</h2></div>
              <div className="table-wrap">
                <table className="table compact">
                  <thead><tr><th>Quelle</th><th>Zeit</th><th className="num">Geschlafen</th><th className="num">Tief</th><th className="num">REM</th><th className="num">Leicht</th><th className="num">Wach</th><th className="num">Wert</th><th className="num">Ø Puls</th><th className="num">HRV</th></tr></thead>
                  <tbody>{n.sessions.map((s) => (
                    <tr key={s.id} className={s.chosen ? "chosen" : ""}>
                      <td>{s.source_name}{s.chosen ? " ✓" : ""}{s.nap ? " (Nickerchen)" : ""}</td>
                      <td>{fmtTime(s.start)}–{fmtTime(s.end)}</td>
                      <td className="num">{fmtMinutes(s.asleep_min)}</td><td className="num">{fmtMinutes(s.deep_min)}</td><td className="num">{fmtMinutes(s.rem_min)}</td>
                      <td className="num">{fmtMinutes(s.light_min)}</td><td className="num">{fmtMinutes(s.awake_min)}</td>
                      <td className="num">{s.score != null ? fmtNum(s.score) : "–"}</td><td className="num">{s.avg_hr != null ? fmtNum(s.avg_hr) : "–"}</td><td className="num">{s.hrv != null ? fmtNum(s.hrv) : "–"}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              <p className="tiny muted">✓ = genutzt. Welche Quelle Vorrang hat, legst du unter Konto → Datenquellen fest.</p>
            </section>
          )}
        </>
      )}
    </div>
  );
}
