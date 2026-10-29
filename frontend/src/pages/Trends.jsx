import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { LineChart, useWidth } from "../components/charts.jsx";
import { Loading } from "../components/feedback.jsx";
import { EmptyState, Segmented, useAsync } from "../components/ui.jsx";
import { fmtMetric, fmtNum } from "../fmt.js";
import { CATEGORY_ORDER, useMeta } from "../meta.js";

const PRESETS = [
  { a: "sleep_duration", b: "hrv", lag: 0, label: "Schlaf und HRV" },
  { a: "active_minutes", b: "resting_hr", lag: 1, label: "Training und Ruhepuls am Folgetag" },
  { a: "steps", b: "weight", lag: 0, label: "Schritte und Gewicht" },
  { a: "calories_in", b: "weight", lag: 1, label: "Kalorien und Gewicht am Folgetag" },
  { a: "stress", b: "sleep_score", lag: 0, label: "Stress und Schlafwert" },
];

function strength(r) {
  const a = Math.abs(r);
  if (a < 0.1) return "kein erkennbarer Zusammenhang";
  if (a < 0.3) return "ein schwacher Zusammenhang";
  if (a < 0.5) return "ein mittlerer Zusammenhang";
  return "ein deutlicher Zusammenhang";
}

function Scatter({ pairs, a, b }) {
  const [ref, width] = useWidth();
  if (pairs.length < 3) return <div ref={ref} />;
  const h = 260, pad = 44;
  const xs = pairs.map((p) => p.a), ys = pairs.map((p) => p.b);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const X = (v) => pad + ((v - x0) / (x1 - x0 || 1)) * (width - pad - 12);
  const Y = (v) => 10 + (1 - (v - y0) / (y1 - y0 || 1)) * (h - pad - 10);
  const n = pairs.length, mx = xs.reduce((s, v) => s + v, 0) / n, my = ys.reduce((s, v) => s + v, 0) / n;
  const sxx = xs.reduce((s, v) => s + (v - mx) ** 2, 0);
  const slope = sxx ? xs.reduce((s, v, i) => s + (v - mx) * (ys[i] - my), 0) / sxx : 0;
  const yAt = (x) => my + slope * (x - mx);
  return (
    <div ref={ref}>
      <svg className="chart" width={width} height={h} viewBox={`0 0 ${width} ${h}`} role="img" aria-label="Streudiagramm">
        <line className="chart-grid" x1={pad} x2={width - 12} y1={h - pad + 6} y2={h - pad + 6} />
        <line className="chart-grid" x1={pad} x2={pad} y1={10} y2={h - pad + 6} />
        <text className="chart-axis" x={pad} y={h - pad + 22}>{fmtMetric(a, x0, false)}</text>
        <text className="chart-axis" x={width - 12} y={h - pad + 22} textAnchor="end">{fmtMetric(a, x1, false)}</text>
        <text className="chart-axis" x={(width + pad) / 2} y={h - 6} textAnchor="middle">{a.label}</text>
        <text className="chart-axis" x={pad - 6} y={Y(y1) + 4} textAnchor="end">{fmtMetric(b, y1, false)}</text>
        <text className="chart-axis" x={pad - 6} y={Y(y0) + 4} textAnchor="end">{fmtMetric(b, y0, false)}</text>
        {pairs.map((p) => <circle key={p.day} cx={X(p.a)} cy={Y(p.b)} r={4} fill="var(--iris)" opacity="0.55"><title>{p.day}</title></circle>)}
        <line x1={X(x0)} x2={X(x1)} y1={Y(yAt(x0))} y2={Y(yAt(x1))} stroke="var(--chalk)" strokeWidth="1.5" strokeDasharray="6 4" opacity="0.6" />
      </svg>
    </div>
  );
}

export default function Trends() {
  const meta = useMeta();
  const [params, setParams] = useSearchParams();
  const a = params.get("a") || "sleep_duration";
  const b = params.get("b") || "hrv";
  const lag = Number(params.get("lag") || 0);
  const days = Number(params.get("days") || 90);
  const [{ data: overview }] = useAsync(() => api.get("/overview"), []);
  const [{ data, loading, error }] = useAsync(() => api.get(`/compare?a=${a}&b=${b}&days=${days}&lag=${lag}`), [a, b, days, lag]);
  if (!meta || !overview) return <Loading rows={2} />;
  const set = (patch) => setParams({ a, b, lag: String(lag), days: String(days), ...patch });
  const available = meta.metrics.filter((m) => overview.metrics[m.key]);
  const select = (value, key) => (
    <select value={value} onChange={(e) => set({ [key]: e.target.value })}>
      {CATEGORY_ORDER.map((c) => {
        const ms = available.filter((m) => m.category === c);
        return ms.length ? <optgroup key={c} label={meta.categories[c]}>{ms.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}</optgroup> : null;
      })}
      {!available.find((m) => m.key === value) && <option value={value}>{meta.byKey[value]?.label || value} (keine Daten)</option>}
    </select>
  );
  const ma = meta.byKey[a], mb = meta.byKey[b];
  return (
    <>
      <div className="page-head">
        <div><h1>Trends</h1><p>Zwei Messgrößen nebeneinander. Hängt dein Ruhepuls vom Training ab, dein Gewicht von den Schritten? Hier siehst du es.</p></div>
      </div>
      {available.length < 2 ? (
        <EmptyState title="Zu wenige Daten" text="Für Vergleiche braucht es mindestens zwei Messgrößen mit Werten." />
      ) : (
        <>
          <section className="panel">
            <div className="form-grid">
              <label>Erste Messgröße{select(a, "a")}</label>
              <label>Zweite Messgröße{select(b, "b")}</label>
            </div>
            <div className="actions">
              <Segmented value={days} onChange={(v) => set({ days: String(v) })} label="Zeitraum"
                options={[{ value: 30, label: "30 Tage" }, { value: 90, label: "90 Tage" }, { value: 365, label: "1 Jahr" }]} />
              <Segmented value={lag} onChange={(v) => set({ lag: String(v) })} label="Versatz"
                options={[{ value: 0, label: "gleicher Tag" }, { value: 1, label: "zweite am Folgetag" }]} />
            </div>
            <div className="chips" style={{ marginTop: "1rem" }}>
              {PRESETS.map((p) => (
                <button key={p.label} className="chip" onClick={() => set({ a: p.a, b: p.b, lag: String(p.lag) })}>{p.label}</button>
              ))}
            </div>
          </section>
          {error ? <p className="error">{error.message}</p> : loading && !data ? <Loading rows={1} /> : data && (
            <>
              <div className="grid-2">
                <section className={`panel cat-${ma?.category}`}><div className="panel-head"><h2>{ma?.label}</h2></div>
                  <LineChart data={data.series_a} height={180} format={(v) => fmtMetric(ma, v, false)} /></section>
                <section className={`panel cat-${mb?.category}`}><div className="panel-head"><h2>{mb?.label}</h2></div>
                  <LineChart data={data.series_b} height={180} format={(v) => fmtMetric(mb, v, false)} /></section>
              </div>
              <section className="panel">
                <div className="panel-head"><h2>Zusammenhang</h2>{data.r != null && <span className="pill iris">r = {fmtNum(data.r, 2)}</span>}</div>
                {data.r != null ? (
                  <p>Über {data.pairs.length} Tage zeigt sich {strength(data.r)}
                    {Math.abs(data.r) >= 0.1 && <>: Ist {ma?.label} höher, {data.r > 0 ? "steigt" : "sinkt"} meist {mb?.label}{lag ? " am Folgetag" : ""}</>}.
                    <span className="muted"> Ein Zusammenhang ist noch keine Ursache.</span></p>
                ) : <p className="muted">Für eine Auswertung braucht es mindestens fünf Tage, an denen beide Werte vorliegen.</p>}
                <Scatter pairs={data.pairs} a={ma} b={mb} />
              </section>
            </>
          )}
        </>
      )}
    </>
  );
}
