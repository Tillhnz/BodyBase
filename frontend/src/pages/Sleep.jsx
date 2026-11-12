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

function Tonight() {
  const v = useDataVersion();
  const [{ data: n }] = useAsync(() => api.get("/sleep/need"), [v]);
  if (!n) return null;
  const max = Math.max(...n.history.map((h) => Math.max(h.need, h.asleep || 0)), 1);
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
      <div className="tonight-hist" aria-label="Bedarf und Schlaf der letzten 14 Nächte">
        {n.history.map((h) => (
          <div key={h.day} title={`${h.day}: Bedarf ${fmtMinutes(h.need)}, geschlafen ${h.asleep ? fmtMinutes(h.asleep) : "–"}`}>
            <i className={`slept${h.asleep && h.asleep >= h.need ? " ok" : ""}`} style={{ height: `${((h.asleep || 0) / max) * 100}%` }} />
            <i className="needline" style={{ bottom: `${(h.need / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <p className="tiny muted" style={{ margin: 0 }}>Grundbedarf {n.custom_base ? "aus deinen Einstellungen" : "nach Alter"}, plus Belastung vom Vortag, ein Teil der Schlafschuld der letzten Woche und mehr, wenn HRV, Ruhepuls oder Atmung auf fehlende Erholung deuten. Balken: geschlafen, Strich: Bedarf.</p>
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
      {!nights.length ? (
        <EmptyState title="Noch keine Schlafdaten" text="Oura, WHOOP, Garmin, Fitbit, Withings, Polar oder Apple Health liefern Schlafphasen.">
          <Link className="btn primary" to="/sources">Quellen</Link>
        </EmptyState>
      ) : (
        <>
          <Tonight />
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
