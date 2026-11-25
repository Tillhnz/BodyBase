import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "../api.js";
import { decodePolyline, useWidth } from "../components/charts.jsx";
import { Loading } from "../components/feedback.jsx";
import { loadMapConfig } from "../components/RouteMap.jsx";
import { EmptyState, Kpi } from "../components/ui.jsx";
import { fmtNum } from "../fmt.js";

/* Heatmap aller Strecken + Explorer-Kacheln (Zoomstufe 14) mit Zeitreise über die Jahre. */

const SPORT = {
  ride: ["Rad", "#ff8a3d"], run: ["Laufen", "#ff4d8d"], walk: ["Gehen", "#4cc9f0"], hike: ["Wandern", "#7ae582"],
  swim: ["Schwimmen", "#3a86ff"], ski: ["Ski", "#c77dff"],
};
const sportName = (s) => SPORT[s]?.[0] || s;
const sportColor = (s) => SPORT[s]?.[1] || "#b388ff";
const MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];

function TilesChart({ timeline, year }) {
  const [ref, width] = useWidth(700);
  if (!timeline.length) return null;
  const H = 140, L0 = 36, B = 18, T = 8;
  const n = timeline.length, bw = Math.max(1, (width - L0) / n);
  const maxNew = Math.max(...timeline.map((t) => t.new), 1);
  const maxTot = timeline[n - 1].total || 1;
  const y = (v, m) => T + (1 - v / m) * (H - T - B);
  const line = timeline.map((t, i) => `${i ? "L" : "M"}${(L0 + i * bw + bw / 2).toFixed(1)},${y(t.total, maxTot).toFixed(1)}`).join("");
  const yearsSeen = [];
  return (
    <div ref={ref} className="tiles-chart">
      <svg width={width} height={H} role="img" aria-label="Neu entdeckte Kacheln je Monat und insgesamt">
        {[0, 0.5, 1].map((f) => <g key={f}><line x1={L0} x2={width} y1={y(maxTot * f, maxTot)} y2={y(maxTot * f, maxTot)} className="rp-grid" />
          <text x={L0 - 4} y={y(maxTot * f, maxTot) + 4} textAnchor="end" className="rp-tick">{fmtNum(maxTot * f)}</text></g>)}
        {timeline.map((t, i) => {
          const yr = t.month.slice(0, 4);
          const label = !yearsSeen.includes(yr) && (yearsSeen.push(yr), true);
          return (
            <g key={t.month}>
              <rect x={L0 + i * bw + bw * 0.15} y={y(t.new, maxNew)} width={Math.max(1, bw * 0.7)} height={H - B - y(t.new, maxNew)} rx="1.5"
                className={`tc-bar${year && Number(yr) === year ? " hi" : ""}`}><title>{`${MONTHS[Number(t.month.slice(5)) - 1]} ${yr}: ${t.new} neue Kacheln (gesamt ${t.total})`}</title></rect>
              {label && <text x={L0 + i * bw} y={H - 4} className="rp-tick">{yr}</text>}
            </g>
          );
        })}
        <path d={line} className="tc-line" />
      </svg>
      <div className="need-legend tiny muted"><span><i className="lg-bar" style={{ background: "var(--iris)" }} />neue Kacheln je Monat</span><span><i className="lg-slept" style={{ borderColor: "var(--good)" }} />insgesamt</span></div>
    </div>
  );
}

function ExplorerMap({ data, show, cfg }) {
  const box = useRef(null);
  const map = useRef(null);
  const layers = useRef({});
  const fitted = useRef(false);

  useEffect(() => {
    if (!cfg || !box.current) return undefined;
    const m = L.map(box.current, { zoomControl: true, scrollWheelZoom: true, preferCanvas: true, worldCopyJump: true });
    map.current = m;
    L.tileLayer(cfg.url, { maxZoom: cfg.max_zoom, subdomains: cfg.subdomains, attribution: cfg.attribution, referrerPolicy: "strict-origin-when-cross-origin" }).addTo(m);
    m.setView([51, 10], 6);
    return () => { m.remove(); map.current = null; layers.current = {}; fitted.current = false; };
  }, [cfg]);

  useEffect(() => {
    const m = map.current;
    if (!m || !data) return;
    Object.values(layers.current).forEach((l) => l.remove());
    layers.current = {};
    const canvas = L.canvas({ padding: 0.5 });
    if (show.tiles) {
      const g = L.layerGroup();
      for (const t of data.tiles) {
        L.rectangle(t.b, { renderer: canvas, weight: 0.5, color: t.new ? "#ffd166" : "#7c8cff", opacity: 0.6, fillColor: t.new ? "#ffd166" : "#7c8cff", fillOpacity: t.new ? 0.35 : 0.16, interactive: false }).addTo(g);
      }
      for (const b of data.cluster_tiles) L.rectangle(b, { renderer: canvas, weight: 0, fillColor: "#5ee2a0", fillOpacity: 0.12, interactive: false }).addTo(g);
      if (data.square.b) L.rectangle(data.square.b, { renderer: canvas, weight: 3, color: "#5ee2a0", fill: false, interactive: false }).addTo(g).bindTooltip(`Größtes Quadrat ${data.square.size}×${data.square.size}`);
      if (show.target) {
        for (const b of data.target.missing) L.rectangle(b, { renderer: canvas, weight: 2, color: "#ff5d6c", dashArray: "4 4", fillColor: "#ff5d6c", fillOpacity: 0.18 }).addTo(g).bindTooltip("Fehlt fürs nächste Quadrat");
      }
      layers.current.tiles = g.addTo(m);
    }
    const r = L.layerGroup();
    const bounds = L.latLngBounds([]);
    for (const a of data.routes) {
      const pts = decodePolyline(a.poly);
      if (pts.length < 2) continue;
      const line = L.polyline(pts, { renderer: canvas, color: show.bySport ? sportColor(a.sport) : "#ff6b3d", weight: 2.2, opacity: 0.45, lineJoin: "round" });
      line.bindTooltip(`${a.name || sportName(a.sport)} · ${a.day.split("-").reverse().join(".")} · ${fmtNum(a.km, 1)} km`, { sticky: true });
      line.on("click", () => { window.location.href = `/activities/${a.id}`; });
      line.addTo(r);
      bounds.extend(line.getBounds());
    }
    layers.current.routes = r.addTo(m);
    if (!fitted.current && bounds.isValid()) {
      // auf den Bereich mit den meisten Strecken (Zuhause) zoomen, nicht auf den Urlaub am anderen Ende
      if (data.near.home) m.fitBounds(L.latLngBounds(data.near.home).pad(6));
      else m.fitBounds(bounds, { padding: [20, 20] });
      fitted.current = true;
    }
  }, [data, show]);

  return <div ref={box} className="explorer-map" />;
}

export default function Heatmap() {
  const [cfg, setCfg] = useState(null);
  const [sports, setSports] = useState(null); // null = alle
  const [year, setYear] = useState(null); // null = alle Jahre, sonst bis/in diesem Jahr
  const [mode, setMode] = useState("upto"); // upto = bis einschließlich, only = nur dieses Jahr
  const [show, setShow] = useState({ tiles: true, target: true, bySport: true });
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => { loadMapConfig().then(setCfg).catch(() => setError("Kartenserver nicht erreichbar")); }, []);
  const query = useMemo(() => {
    const q = new URLSearchParams();
    if (sports?.length) q.set("sports", sports.join(","));
    if (year) { q.set("to", year); q.set("highlight", year); if (mode === "only") q.set("from", year); }
    return q.toString();
  }, [sports, year, mode]);
  useEffect(() => {
    let stop = false;
    api.get(`/explorer?${query}`).then((d) => { if (!stop) setData(d); }).catch((e) => setError(e.message));
    return () => { stop = true; };
  }, [query]);

  // Zeitreise: Jahr für Jahr abspielen
  useEffect(() => {
    if (!playing || !data) return undefined;
    const ys = data.years;
    const t = setTimeout(() => {
      const i = year ? ys.indexOf(year) : -1;
      if (i + 1 >= ys.length) { setPlaying(false); return; }
      setYear(ys[i + 1]);
    }, 1600);
    return () => clearTimeout(t);
  }, [playing, year, data]);

  if (error && !data) return <EmptyState title="Heatmap nicht verfügbar" text={error} />;
  if (!data) return <Loading rows={3} />;
  if (!data.years.length) {
    return <EmptyState title="Noch keine Strecken" text="Sobald Aktivitäten mit GPS da sind (Strava, Garmin, Health Connect, Import), entsteht hier deine Heatmap."><Link className="btn" to="/sources">Quellen verbinden</Link></EmptyState>;
  }
  const s = data.stats;
  const nearPct = data.near.total ? Math.round((data.near.done / data.near.total) * 100) : 0;
  const allSports = data.sports;
  const active = sports || allSports;
  const toggleSport = (sp) => {
    const next = active.includes(sp) ? active.filter((x) => x !== sp) : [...active, sp];
    setSports(next.length === allSports.length || !next.length ? null : next);
  };
  const thisYear = data.per_year.find((p) => p.year === (year || new Date().getFullYear()));

  return (
    <div className="explorer">
      <div className="page-head">
        <div>
          <p style={{ margin: 0 }}><Link className="link quiet small" to="/activities">Aktivitäten</Link></p>
          <h1>Heatmap & Entdecken</h1>
          <p>Alle Strecken, die du je gefahren und gelaufen bist – und wie viel Neues du entdeckst.</p>
        </div>
      </div>

      <div className="kpis">
        <Kpi label="Entdeckte Kacheln" value={fmtNum(s.tiles)} sub={year ? `bis ${year}` : "insgesamt"} />
        <Kpi label={`Neu ${year || new Date().getFullYear()}`} value={fmtNum(year ? s.new_in_range : thisYear?.new || 0)} />
        <Kpi label="Größtes Quadrat" value={`${data.square.size}×${data.square.size}`} sub={`nächstes: noch ${data.target.count} Kacheln`} />
        <Kpi label="Größter Cluster" value={fmtNum(data.cluster)} />
        <Kpi label="Umkreis Zuhause" value={`${nearPct} %`} sub={`${data.near.done} von ${data.near.total} Kacheln (≈ 9 km)`} />
      </div>

      <section className="panel explorer-panel">
        <div className="explorer-filters">
          <div className="chips" role="group" aria-label="Sportarten">
            {allSports.map((sp) => (
              <button key={sp} type="button" className={`chip${active.includes(sp) ? " on" : ""}`} onClick={() => toggleSport(sp)}>
                <i style={{ background: sportColor(sp) }} />{sportName(sp)}
              </button>
            ))}
          </div>
          <div className="year-row">
            <button type="button" className="btn small" onClick={() => { if (playing) setPlaying(false); else { setYear(data.years[0]); setMode("upto"); setPlaying(true); } }}>
              {playing ? "■ Stopp" : "▶ Zeitreise"}
            </button>
            <input type="range" min={0} max={data.years.length} value={year ? data.years.indexOf(year) : data.years.length}
              onChange={(e) => { const i = Number(e.target.value); setPlaying(false); setYear(i >= data.years.length ? null : data.years[i]); }}
              aria-label="Jahr" />
            <b className="year-label">{year || "Alle"}</b>
            {year && (
              <select value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Zeitraum">
                <option value="upto">alles bis {year}</option>
                <option value="only">nur {year}</option>
              </select>
            )}
          </div>
          <div className="chips">
            <label className="check small"><input type="checkbox" checked={show.tiles} onChange={(e) => setShow({ ...show, tiles: e.target.checked })} />Kacheln</label>
            <label className="check small"><input type="checkbox" checked={show.target} onChange={(e) => setShow({ ...show, target: e.target.checked })} />Nächstes Quadrat</label>
            <label className="check small"><input type="checkbox" checked={show.bySport} onChange={(e) => setShow({ ...show, bySport: e.target.checked })} />Farben je Sportart</label>
          </div>
        </div>
        {cfg ? <ExplorerMap data={data} show={show} cfg={cfg} /> : <Loading rows={2} />}
        <p className="tiny muted" style={{ margin: "0.4rem 0 0" }}>
          {fmtNum(s.activities)} Aktivitäten · {fmtNum(s.km)} km. Kacheln = Zoomstufe 14 (rund 1,5 × 1,5 km). <span style={{ color: "#ffd166" }}>■</span> neu im gewählten Jahr,{" "}
          <span style={{ color: "#5ee2a0" }}>□</span> größtes Quadrat, <span style={{ color: "#ff5d6c" }}>▭</span> fehlt fürs nächste.
        </p>
      </section>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-head"><h2>Entdeckt über die Zeit</h2></div>
          <TilesChart timeline={data.timeline} year={year} />
        </section>
        <section className="panel">
          <div className="panel-head"><h2>Deine nächsten Ziele</h2></div>
          <ul className="explorer-goals">
            <li><b>Quadrat {data.target.size}×{data.target.size}</b><span>Es fehlen noch <b>{data.target.count}</b> Kacheln – rot gestrichelt auf der Karte.</span></li>
            <li><b>Rund um Zuhause</b><span>{data.near.total - data.near.done} unentdeckte Kacheln im Umkreis von etwa 9 km.</span></li>
            {data.per_year.length > 1 && (() => {
              const best = data.per_year.reduce((a, b) => (b.new > a.new ? b : a));
              const cur = data.per_year.find((p) => p.year === new Date().getFullYear());
              return <li><b>Rekordjahr {best.year}</b><span>{best.new} neue Kacheln{cur ? ` – dieses Jahr bisher ${cur.new}` : ""}.</span></li>;
            })()}
          </ul>
          <div className="year-bars">
            {data.per_year.map((p) => (
              <button key={p.year} type="button" className={year === p.year ? "on" : ""} onClick={() => { setPlaying(false); setYear(p.year); }}
                title={`${p.new} neue Kacheln`}>
                <span style={{ height: `${(p.new / Math.max(...data.per_year.map((x) => x.new), 1)) * 100}%` }} />
                <small>{String(p.year).slice(2)}</small>
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
