import { Link } from "react-router-dom";
import { api } from "../api.js";
import { LineChart } from "../components/charts.jsx";
import { Loading } from "../components/feedback.jsx";
import { EmptyState, useAsync } from "../components/ui.jsx";
import { fmtNum } from "../fmt.js";
import { useDataVersion } from "../refresh.js";

/* Biologisches Alter: Schätzung aus allen Messwerten, mit Begründung je Messwert. */

const yrs = (v) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${fmtNum(Math.abs(v), 1)} J.`;

function Hero({ r }) {
  const younger = r.delta < 0;
  const lo = Math.min(r.age, r.bio_age) - 8, hi = Math.max(r.age, r.bio_age) + 8;
  const pos = (v) => `${((v - lo) / (hi - lo)) * 100}%`;
  return (
    <section className="panel bio-hero">
      <div className="bio-main">
        <span className="rp-k">Biologisches Alter</span>
        <strong className="bio-num">{fmtNum(r.bio_age, 1)}</strong>
        <span className={`bio-delta ${younger ? "good" : r.delta > 0 ? "bad" : ""}`}>
          {Math.abs(r.delta) < 0.5 ? "entspricht deinem Alter" : `${fmtNum(Math.abs(r.delta), 1)} Jahre ${younger ? "jünger" : "älter"} als dein Alter (${fmtNum(r.age, 0)})`}
        </span>
      </div>
      <div className="bio-scale" aria-hidden="true">
        <div className="bio-track" />
        <div className="bio-span" style={{ left: pos(Math.min(r.age, r.bio_age)), width: `calc(${pos(Math.max(r.age, r.bio_age))} - ${pos(Math.min(r.age, r.bio_age))})` }} data-good={younger} />
        <i className="bio-mark age" style={{ left: pos(r.age) }}><span>{fmtNum(r.age, 0)} tatsächlich</span></i>
        <i className="bio-mark bio" style={{ left: pos(r.bio_age) }}><span>{fmtNum(r.bio_age, 1)} biologisch</span></i>
      </div>
      <p className="tiny muted" style={{ margin: 0 }}>
        Aussagekraft {Math.round(r.confidence * 100)} % – je mehr Bereiche gemessen werden, desto genauer.{" "}
        Schätzung aus Studien zur Sterblichkeit, keine medizinische Diagnose.
      </p>
    </section>
  );
}

function Factor({ f, max }) {
  const w = Math.min(50, (Math.abs(f.impact) / max) * 50);
  return (
    <li className="bio-factor">
      <div className="bio-f-head">
        <strong>{f.label}</strong>
        <span className="bio-f-val">{f.value != null ? `${fmtNum(f.value, f.value % 1 ? 1 : 0)} ${f.unit}` : ""}</span>
        <span className={`bio-f-years ${f.impact < -0.05 ? "good" : f.impact > 0.05 ? "bad" : "flat"}`}>{yrs(f.impact)}</span>
      </div>
      <div className="bio-bar" aria-hidden="true">
        <i className={f.impact < 0 ? "good" : "bad"} style={f.impact < 0 ? { right: "50%", width: `${w}%` } : { left: "50%", width: `${w}%` }} />
      </div>
      <p className="small" style={{ margin: 0 }}>{f.text}</p>
      <span className="tiny muted">{f.n ? `${f.n} Tage · ` : ""}Studie: {f.source}</span>
    </li>
  );
}

export function BioAgeView() {
  const v = useDataVersion();
  const [{ data: r, error }] = useAsync(() => api.get("/bio-age"), [v]);
  if (error) return <EmptyState title="Nicht verfügbar" text={error.message} />;
  if (!r) return <Loading rows={3} />;
  if (!r.ready) {
    return (
      <EmptyState title="Biologisches Alter noch nicht berechenbar" text={r.reason}>
        {r.reason.includes("Geburtsjahr") ? <Link className="btn primary" to="/settings">Zum Profil</Link> : null}
        {r.missing?.length ? <ul className="small" style={{ textAlign: "left" }}>{r.missing.map((m) => <li key={m.key}><b>{m.label}</b>: {m.how}</li>)}</ul> : null}
      </EmptyState>
    );
  }
  const max = Math.max(1, ...r.factors.map((f) => Math.abs(f.impact)));
  const good = r.factors.filter((f) => f.impact < -0.05), bad = r.factors.filter((f) => f.impact > 0.05);
  return (
    <div className="bio">
      <Hero r={r} />
      <section className="panel">
        <div className="panel-head"><h2>Warum?</h2><span className="tiny muted">Beitrag jedes Messwerts in Jahren</span></div>
        <p className="small" style={{ marginTop: 0 }}>
          {good.length ? <>Jünger machen dich vor allem <b>{good.slice(0, 2).map((f) => f.label).join(" und ")}</b>. </> : null}
          {bad.length ? <>Älter machen dich <b>{bad.slice(-2).reverse().map((f) => f.label).join(" und ")}</b>.</> : "Kein Messwert zieht dich nach oben."}
        </p>
        <ul className="bio-factors">{r.factors.map((f) => <Factor key={f.key} f={f} max={max} />)}</ul>
      </section>
      <div className="grid-2">
        {r.levers.length > 0 && (
          <section className="panel">
            <div className="panel-head"><h2>Größte Hebel</h2></div>
            <ul className="bio-levers">
              {r.levers.map((l) => <li key={l.key}><span><b>{l.label}</b><small className="muted">{l.text}</small></span><strong className="good-text">{yrs(l.years)}</strong></li>)}
            </ul>
          </section>
        )}
        {r.missing.length > 0 && (
          <section className="panel">
            <div className="panel-head"><h2>Würde genauer machen</h2></div>
            <ul className="bio-levers">{r.missing.map((m) => <li key={m.key}><span><b>{m.label}</b><small className="muted">{m.how}</small></span></li>)}</ul>
          </section>
        )}
      </div>
      {r.history.length > 2 && (
        <section className="panel">
          <div className="panel-head"><h2>Verlauf</h2><span className="tiny muted">biologisch (Linie) und tatsächlich (gestrichelt), jeweils zum Monatsende</span></div>
          <LineChart data={r.history.map((h) => ({ day: h.day, value: h.bio_age }))} compare={r.history.map((h) => ({ day: h.day, value: h.age }))} format={(x) => fmtNum(x, 1)} label="Biologisches Alter" />
        </section>
      )}
      <details className="panel bio-method">
        <summary>So wird gerechnet</summary>
        <p className="small">Große Studien zeigen, wie stark jeder Messwert das Sterberisiko verändert (z. B. senkt jede zusätzliche Fitnessstufe von 3,5 ml/kg/min VO₂max das Risiko um etwa 13 %). Das Risiko steigt mit jedem Lebensjahr um rund 9 %. Daraus wird für jeden Messwert errechnet, wie vielen Lebensjahren er entspricht.</p>
        <p className="small">Weil Werte zusammenhängen (Fitness senkt auch den Ruhepuls), wird die Summe um ein Viertel gedämpft, jeder Wert zählt höchstens 8 Jahre und das Ergebnis liegt höchstens 15 Jahre neben deinem Alter. Genutzt werden die Mediane der letzten 90 Tage, Körperwerte bis ein Jahr alt.</p>
        <p className="small">Blutwerte wie Blutzucker, Cholesterin und Entzündungswerte fehlen in Wearable-Daten, deshalb ist es eine Orientierung, kein Laborbefund.</p>
      </details>
    </div>
  );
}
