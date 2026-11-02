import { Link } from "react-router-dom";
import { fmtMinutes, fmtNum, fmtTime } from "../fmt.js";
import { StageBar } from "./charts.jsx";

/* Die drei eigenen Tageswerte von BodyBase: Bereitschaft, Auslastung, Schlaf (je 0–100). */

function readinessInfo(v) {
  if (v >= 75) return ["hoch", "Gut erholt. Heute verträgst du eine fordernde Einheit."];
  if (v >= 55) return ["mittel", "Normal erholt. Training wie geplant."];
  if (v >= 40) return ["gedämpft", "Etwas angeschlagen. Lieber locker oder kürzer."];
  return ["niedrig", "Wenig erholt. Ruhe und Schlaf bringen heute am meisten."];
}

function loadInfo(v, [lo, hi]) {
  if (v > hi) return ["über Ziel", "Mehr als für heute sinnvoll. Morgen lieber ruhiger."];
  if (v >= lo) return ["im Ziel", "Passt gut zu deiner Bereitschaft."];
  if (v === 0) return ["ruhig", `Heute passt eine Auslastung von ${lo} bis ${hi}.`];
  return ["noch Luft", `Bis ${lo}–${hi} passt heute gut zu deiner Bereitschaft.`];
}

function sleepInfo(v) {
  if (v >= 85) return ["sehr gut", "Sehr erholsam geschlafen."];
  if (v >= 70) return ["gut", "Ordentlich geschlafen."];
  if (v >= 50) return ["mäßig", "Etwas zu wenig Erholung in der Nacht."];
  return ["schwach", "Kurze oder unruhige Nacht."];
}

const dayLabel = (iso, today) => (iso && iso !== today ? " · von gestern" : "");

function History({ data, k, today }) {
  return (
    <div className="score-hist" aria-label="Verlauf der letzten 14 Tage">
      {data.map((d) => (
        <span key={d.day} className={d.day === today ? "today" : ""} title={`${d.day}: ${d[k] ?? "–"}`}>
          {d[k] != null ? <i style={{ height: `${Math.max(6, d[k])}%` }} /> : <b />}
        </span>
      ))}
    </div>
  );
}

function Parts({ parts }) {
  if (!parts?.length) return null;
  return (
    <ul className="score-parts">
      {parts.map((p) => (
        <li key={p.key}>
          <span className="lbl">{p.label}</span>
          <span className="bar">{p.weight > 0 && <i style={{ width: `${p.score}%` }} />}</span>
          <span className="num">{p.weight > 0 ? p.score : "!"}</span>
          <span className="txt">{p.text}</span>
        </li>
      ))}
    </ul>
  );
}

function Card({ cat, title, metric, value, level, text, children, history, hk, today, sub }) {
  return (
    <section className={`panel score-card cat-${cat}`}>
      <div className="score-head">
        <Link to={`/metric/${metric}`} className="score-title">{title}</Link>
        {level && <span className="pill">{level}</span>}
      </div>
      <div className="score-main">
        <div className="score-num">{value != null ? fmtNum(value) : "–"}</div>
        <History data={history} k={hk} today={today} />
      </div>
      {sub && <div className="score-sub">{sub}</div>}
      <p className="score-text">{text}</p>
      {children}
    </section>
  );
}

export default function ScoreCards({ scores, sleep, goals = [] }) {
  if (!scores) return null;
  const today = scores.day;
  const rd = scores.readiness;
  const ld = scores.load;
  const sl = scores.sleep;
  const [rLevel, rText] = rd ? readinessInfo(rd.value) : [null, "Sobald HRV, Ruhepuls oder Schlaf von ein paar Tagen vorliegen, berechnet BodyBase hier deine Bereitschaft."];
  const [lLevel, lText] = loadInfo(ld.value, ld.target);
  const [sLevel, sText] = sl ? sleepInfo(sl.value) : [null, "Keine Schlafdaten der letzten Nacht."];
  const [lo, hi] = ld.target;
  const steps = goals.find((g) => g.key === "steps");
  const active = goals.find((g) => g.key === "active_minutes");

  return (
    <>
      <div className="score-row">
        <Card cat="recovery" title="Bereitschaft" metric="bb_readiness" value={rd?.value} level={rd && rLevel + dayLabel(rd.day, today)}
          text={rText} history={scores.history} hk="readiness" today={today}>
          <Parts parts={rd?.parts} />
        </Card>

        <Card cat="activity" title="Auslastung" metric="bb_load" value={ld.value} level={lLevel} text={lText}
          history={scores.history} hk="load" today={today}
          sub={(
            <div className="load-track" aria-label={`Zielbereich ${lo} bis ${hi}`}>
              <span className="zone" style={{ left: `${lo}%`, width: `${hi - lo}%` }} />
              <i style={{ left: `${Math.min(100, ld.value)}%` }} />
            </div>
          )}>
          <ul className="score-parts">
            <li><span className="lbl">Training</span><span className="txt wide">{ld.count ? `${ld.count} ${ld.count === 1 ? "Einheit" : "Einheiten"}, Last ${fmtNum(ld.training)}` : "noch keins heute"}</span></li>
            <li><span className="lbl">Alltag</span><span className="txt wide">{steps?.value != null ? `${fmtNum(steps.value)} Schritte` : "–"}{active?.value != null ? ` · ${fmtNum(active.value)} aktive Minuten` : ""}</span></li>
            {ld.acwr != null && (
              <li><span className="lbl">7 Tage</span><span className="txt wide">{fmtNum(ld.acwr, 1)}× so viel wie in den 4 Wochen davor
                {ld.acwr > 1.5 ? " – viel auf einmal" : ld.acwr < 0.8 ? " – eher wenig" : ""}</span></li>
            )}
            <li><span className="lbl">Gestern</span><span className="txt wide">Auslastung {fmtNum(ld.yesterday)}</span></li>
          </ul>
        </Card>

        <Card cat="sleep" title="Schlaf" metric="bb_sleep" value={sl?.value} level={sl && sLevel + dayLabel(sl.day, today)}
          text={sText} history={scores.history} hk="sleep" today={today}
          sub={sleep && (
            <div className="score-night">
              <strong>{fmtMinutes(sleep.asleep_min)}</strong>
              <span className="muted small"> · {fmtTime(sleep.start)} bis {fmtTime(sleep.end)}</span>
              <StageBar deep={sleep.deep_min} rem={sleep.rem_min} light={sleep.light_min} awake={sleep.awake_min} />
            </div>
          )}>
          <Parts parts={sl?.parts} />
        </Card>
      </div>
    </>
  );
}
