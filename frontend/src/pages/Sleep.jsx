import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { useDataVersion } from "../refresh.js";
import { StageBar, useWidth } from "../components/charts.jsx";
import { Loading } from "../components/feedback.jsx";
import { EmptyState, Kpi, Segmented, useAsync } from "../components/ui.jsx";
import { fmtClock, fmtDay, fmtDayShort, fmtMinutes, fmtNum, fmtTime } from "../fmt.js";

const RANGES = [{ value: 14, label: "14 Nächte" }, { value: 30, label: "30 Nächte" }, { value: 90, label: "90 Nächte" }, { value: 365, label: "1 Jahr" }];

/** Nächte als gestapelte Balken: Tief, Leicht, REM, wach. Ohne Phasen nur die Gesamtdauer. */
function SleepBars({ nights, goal }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const navigate = useNavigate();
  const h = 240, pad = { l: 40, r: 8, t: 10, b: 24 };
  const max = Math.max(goal || 0, ...nights.map((n) => (n.asleep_min || 0) + (n.awake_min || 0)), 60);
  const hi = Math.ceil(max / 60) * 60;
  const n = nights.length;
  const w = width - pad.l - pad.r, bh = h - pad.t - pad.b;
  const slot = w / Math.max(1, n);
  const bw = Math.max(2, slot * 0.7);
  const y = (m) => pad.t + bh - (m / hi) * bh;
  const ticks = [];
  for (let t = 0; t <= hi; t += hi > 600 ? 120 : 60) ticks.push(t);
  return (
    <div className="chart-wrap" ref={ref}>
      <svg className="chart" width={width} height={h} viewBox={`0 0 ${width} ${h}`} role="img" aria-label="Schlaf pro Nacht" onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}><line className="chart-grid" x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} />
            <text className="chart-axis" x={pad.l - 6} y={y(t) + 4} textAnchor="end">{t / 60} h</text></g>
        ))}
        {nights.map((nt, i) => {
          const x = pad.l + i * slot + (slot - bw) / 2;
          const staged = nt.deep_min != null || nt.rem_min != null;
          const parts = staged
            ? [["st-deep", nt.deep_min], ["st-light", nt.light_min], ["st-rem", nt.rem_min], ["st-awake", nt.awake_min]]
            : [["st-light", nt.asleep_min], ["st-awake", nt.awake_min]];
          let acc = 0;
          return (
            <g key={nt.day} onMouseEnter={() => setHover({ nt, x: x + bw / 2 })} onClick={() => nt.start && navigate(`/sleep/${nt.day}`)} style={{ cursor: nt.start ? "pointer" : undefined }}>
              <rect x={pad.l + i * slot} y={pad.t} width={slot} height={bh} fill="transparent" />
              {parts.map(([cls, v]) => {
                if (!v) return null;
                const y0 = y(acc + v), hh = y(acc) - y(acc + v);
                acc += v;
                return <rect key={cls} className={cls} x={x} y={y0} width={bw} height={Math.max(0, hh)} rx={Math.min(3, bw / 3)} />;
              })}
            </g>
          );
        })}
        {goal ? <line className="chart-goal" x1={pad.l} x2={width - pad.r} y1={y(goal)} y2={y(goal)} /> : null}
        {nights.map((nt, i) => (i % Math.ceil(n / Math.max(2, Math.floor(width / 70))) === 0
          ? <text key={nt.day} className="chart-axis" x={pad.l + i * slot + slot / 2} y={h - 6} textAnchor="middle">{fmtDayShort(nt.day)}</text> : null))}
      </svg>
      {hover && (
        <div className="chart-tip" style={{ left: Math.min(width - 80, Math.max(80, hover.x)), top: y(hover.nt.asleep_min || 0) }}>
          <strong>{fmtMinutes(hover.nt.asleep_min)}</strong> <span className="muted">{fmtDay(hover.nt.day)}</span>
          {hover.nt.deep_min != null && <div className="tiny muted">Tief {fmtMinutes(hover.nt.deep_min)} · REM {fmtMinutes(hover.nt.rem_min)}</div>}
        </div>
      )}
    </div>
  );
}

function NeedChart({ history }) {
  const [ref, width] = useWidth(700);
  const H = 150, L = 34, R = 6, T = 8, B = 20;
  const vals = history.flatMap((h) => [h.need, h.asleep || 0]);
  const hi = Math.ceil((Math.max(...vals, 480) + 30) / 60) * 60, lo = Math.max(0, Math.floor((Math.min(...vals.filter(Boolean), 360) - 60) / 60) * 60);
  const n = history.length, step = (width - L - R) / n;
  const x = (i) => L + i * step + step / 2;
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const bw = Math.max(1.5, Math.min(18, step * 0.62));
  const needPath = history.map((h, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(h.need).toFixed(1)}`).join("");
  const pts = history.map((h, i) => (h.asleep ? [x(i), y(h.asleep)] : null));
  let sleptPath = "";
  pts.forEach((p, i) => { if (p) sleptPath += `${sleptPath && pts[i - 1] ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`; });
  const ticks = [];
  for (let v = lo; v <= hi; v += 60) ticks.push(v);
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(width / 64))));
  return (
    <div ref={ref} className="need-chart">
      <svg width={width} height={H} role="img" aria-label="Schlafbedarf und Schlafdauer je Nacht">
        {ticks.map((v) => <g key={v}><line x1={L} x2={width - R} y1={y(v)} y2={y(v)} className="rp-grid" /><text x={L - 6} y={y(v) + 4} textAnchor="end" className="rp-tick">{v / 60} h</text></g>)}
        {history.map((h, i) => h.asleep ? (
          <rect key={h.day} x={x(i) - bw / 2} y={y(h.asleep)} width={bw} height={Math.max(0, H - B - y(h.asleep))} rx={Math.min(3, bw / 2)}
            className={`need-bar${h.asleep >= h.need ? " ok" : ""}`}><title>{`${fmtDay(h.day)}: ${fmtMinutes(h.asleep)} geschlafen, Bedarf ${fmtMinutes(h.need)}`}</title></rect>
        ) : null)}
        {n <= 60 && <path d={sleptPath} className="need-slept" />}
        <path d={needPath} className="need-line" />
        {history.map((h, i) => (i % every === 0 ? <text key={h.day} x={x(i)} y={H - 4} textAnchor="middle" className="rp-tick">{h.day.slice(8, 10)}.{h.day.slice(5, 7)}.</text> : null))}
      </svg>
      <div className="need-legend tiny muted"><span><i className="lg-bar" />geschlafen</span><span><i className="lg-need" />Bedarf</span>{n <= 60 && <span><i className="lg-slept" />Verlauf</span>}</div>
    </div>
  );
}

function Tonight({ days }) {
  const v = useDataVersion();
  const [{ data: n }] = useAsync(() => api.get(`/sleep/need?days=${days}`), [days, v]);
  if (!n) return <section className="panel tonight"><Loading rows={1} /></section>;
  const shown = n.history.filter((h) => h.asleep);
  const debt = shown.reduce((s, h) => s + Math.max(0, h.need - h.asleep), 0);
  return (
    <section className="panel tonight">
      <div className="tonight-main">
        <div>
          <span className="rp-k">Schlafbedarf heute Nacht</span>
          <strong className="tonight-num">{fmtMinutes(n.need)}</strong>
          {n.bedtime && <span className="small muted">Ins Bett um <b>{n.bedtime}</b> für Aufstehen um {n.wake}</span>}
        </div>
        <ul className="tonight-parts">
          {n.parts.map((p) => (
            <li key={p.key}><span>{p.label}{p.text ? <small className="muted"> · {p.text}</small> : null}</span><b>{p.key === "base" ? fmtMinutes(p.min) : `+${p.min} min`}</b></li>
          ))}
        </ul>
      </div>
      <div className="panel-head" style={{ margin: 0 }}><h3 className="sub-h" style={{ margin: 0 }}>Bedarf und Schlaf</h3>
        <span className="tiny muted">{shown.length ? `${shown.filter((h) => h.asleep >= h.need).length} von ${shown.length} Nächten gedeckt · ${fmtMinutes(debt)} Fehlbetrag gesamt` : "keine Nächte im Zeitraum"}</span></div>
      <NeedChart history={n.history} />
      <p className="tiny muted" style={{ margin: 0 }}>Grundbedarf {n.custom_base ? "aus deinen Einstellungen" : "nach Alter"}, plus Belastung vom Vortag, ein Teil der Schlafschuld der letzten Woche und mehr, wenn HRV, Ruhepuls oder Atmung auf fehlende Erholung deuten.</p>
    </section>
  );
}

export default function Sleep() {
  const [days, setDays] = useState(30);
  const v = useDataVersion();
  const [{ data, loading }] = useAsync(() => api.get(`/sleep?days=${days}`), [days, v]);
  if (loading && !data) return <Loading rows={2} />;
  const nights = data?.nights || [];
  const avg = data?.avg || {};
  return (
    <div className="cat-sleep">
      <div className="page-head">
        <div><h1>Schlaf</h1><p>Pro Nacht zählt die bevorzugte Quelle. Nickerchen bleiben außen vor.</p></div>
        <Segmented value={days} onChange={setDays} options={RANGES} label="Zeitraum" />
      </div>
      <Tonight days={days} />
      {!nights.length ? (
        <EmptyState title="Noch keine Schlafdaten" text="Oura, WHOOP, Garmin, Fitbit, Withings, Polar oder Apple Health liefern Schlafphasen.">
          <Link className="btn primary" to="/sources">Quellen</Link>
        </EmptyState>
      ) : (
        <>
          <div className="kpis">
            <Kpi label="Ø Schlafdauer" value={fmtMinutes(avg.asleep_min)} sub={data.goal ? `Ziel ${fmtMinutes(data.goal)}` : null} />
            {avg.deep_min != null && <Kpi label="Ø Tiefschlaf" value={fmtMinutes(avg.deep_min)} sub={avg.asleep_min ? `${fmtNum((avg.deep_min / avg.asleep_min) * 100)} % der Nacht` : null} />}
            {avg.rem_min != null && <Kpi label="Ø REM" value={fmtMinutes(avg.rem_min)} sub={avg.asleep_min ? `${fmtNum((avg.rem_min / avg.asleep_min) * 100)} % der Nacht` : null} />}
            {avg.score != null && <Kpi label="Ø Schlafwert" value={fmtNum(avg.score)} />}
            {data.bedtime_avg != null && <Kpi label="Ø Einschlafen" value={fmtClock(data.bedtime_avg)} sub={data.wake_avg != null ? `Aufwachen ${fmtClock(data.wake_avg)}` : null} />}
            {avg.hrv != null && <Kpi label="Ø HRV nachts" value={fmtNum(avg.hrv)} unit="ms" />}
          </div>
          <section className="panel">
            <div className="panel-head"><h2>Nächte</h2>
              <div className="stage-legend" style={{ margin: 0 }}>
                <span><i className="st-deep" />Tief</span><span><i className="st-light" />Leicht</span><span><i className="st-rem" />REM</span><span><i className="st-awake" />Wach</span>
              </div>
            </div>
            <SleepBars nights={nights} goal={data.goal} />
          </section>
          <section className="panel">
            <div className="panel-head"><h2>Letzte Nächte</h2></div>
            <ul className="list">
              {[...nights].reverse().slice(0, 14).map((n) => (
                <li key={n.day}><Link to={`/sleep/${n.day}`} className="night-row" style={{ display: "grid", gridTemplateColumns: "minmax(110px, 160px) minmax(0, 1fr) auto", gap: "1rem", alignItems: "center", padding: "0.65rem 0" }}>
                  <div><strong>{fmtDay(n.day)}</strong><div className="tiny muted">{n.start ? `${fmtTime(n.start)} – ${fmtTime(n.end)}` : n.source_name}</div></div>
                  {n.deep_min != null ? <StageBar deep={n.deep_min} rem={n.rem_min} light={n.light_min} awake={n.awake_min} /> : <span className="muted small">ohne Phasen</span>}
                  <div style={{ textAlign: "right" }}><strong style={{ fontFamily: "var(--font-display)", fontSize: "1.2rem" }}>{fmtMinutes(n.asleep_min)}</strong>
                    {n.score != null && <div className="tiny muted">Wert {fmtNum(n.score)}</div>}</div>
                </Link></li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
