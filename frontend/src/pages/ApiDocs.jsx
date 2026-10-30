import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Loading } from "../components/feedback.jsx";
import { CopyField } from "../components/ui.jsx";

const HIDE = ["/api/auth/", "/api/admin", "/api/me/api-keys", "/api/me/delete", "/api/oauth/", "/api/frame-policy"];
const METHOD_ORDER = { get: 0, post: 1, put: 2, patch: 3, delete: 4 };
const TAG_LABEL = {
  data: "Daten", strength: "Krafttraining", habits: "Gewohnheiten & Coach", account: "Konto & Einträge", connections: "Quellen",
  imports: "Importe & Empfang", map: "Karten", version: "Version", default: "Sonstiges",
};

function resolve(spec, schema, depth = 0) {
  if (!schema || depth > 4) return schema;
  if (schema.$ref) return resolve(spec, schema.$ref.split("/").slice(1).reduce((o, k) => o?.[k], spec), depth + 1);
  if (schema.anyOf) return { ...schema, type: schema.anyOf.map((x) => resolve(spec, x, depth + 1)?.type).filter(Boolean).join(" | ") };
  return schema;
}

export default function ApiDocs() {
  const [spec, setSpec] = useState(null);
  const [q, setQ] = useState("");
  useEffect(() => { fetch("/api/openapi.json").then((r) => r.json()).then(setSpec).catch(() => setSpec(false)); }, []);
  const base = `${window.location.origin}/api`;
  const groups = useMemo(() => {
    if (!spec) return [];
    const out = {};
    for (const [path, ops] of Object.entries(spec.paths || {})) {
      if (HIDE.some((h) => path.startsWith(h))) continue;
      for (const [method, op] of Object.entries(ops)) {
        const tag = op.tags?.[0] || "default";
        const text = `${method} ${path} ${op.summary || ""} ${op.description || ""}`.toLowerCase();
        if (q && !text.includes(q.toLowerCase())) continue;
        (out[tag] = out[tag] || []).push({ path, method, op });
      }
    }
    return Object.entries(out).map(([tag, list]) => [tag, list.sort((a, b) => a.path.localeCompare(b.path) || METHOD_ORDER[a.method] - METHOD_ORDER[b.method])]);
  }, [spec, q]);
  if (spec === null) return <Loading rows={3} />;

  return (
    <div className="api-docs">
      <div className="page-head">
        <div>
          <p style={{ margin: 0 }}><Link className="link quiet small" to="/settings">Einstellungen</Link></p>
          <h1>API</h1>
          <p>Alle Daten aus BodyBase für deine eigenen Programme. Die Beschreibung kommt direkt vom Server und ist immer aktuell.</p>
        </div>
        <div className="actions"><a className="btn" href="/api/openapi.json" target="_blank" rel="noreferrer">OpenAPI (JSON)</a></div>
      </div>

      <div className="grid-2">
        <section className="panel">
          <h2>Schnellstart</h2>
          <ol className="steps">
            <li>Unter <Link className="link" to="/settings">Einstellungen → API</Link> einen Schlüssel erzeugen (nur lesen reicht für Auswertungen).</li>
            <li>Bei jeder Anfrage mitschicken: <code>Authorization: Bearer bbk_…</code> oder <code>X-API-Key: bbk_…</code></li>
            <li>Basisadresse:</li>
          </ol>
          <CopyField value={base} label="Basisadresse" />
          <p className="small muted">Zeiten sind UTC (ISO 8601), Tage JJJJ-MM-TT, Gewicht in kg, Strecken in Metern, Dauer in Sekunden.</p>
        </section>
        <section className="panel">
          <h2>Beispiele</h2>
          <Example title="Tageswerte der letzten 30 Tage (z. B. Gewicht)" code={`curl -H "Authorization: Bearer $BODYBASE_KEY" \\\n  "${base}/metrics/weight?days=30"`} />
          <Example title="Letzte Aktivitäten" code={`curl -H "X-API-Key: $BODYBASE_KEY" "${base}/activities?limit=10"`} />
          <Example title="Liegestütze eintragen (Schlüssel mit Schreibrecht)" code={`curl -X POST -H "Authorization: Bearer $BODYBASE_KEY" \\\n  -H "Content-Type: application/json" -d '{"add": 20}' \\\n  "${base}/habits/1/log"`} />
          <Example title="Werte senden (Waage, Skript, Node-RED)" code={`curl -X POST -H "Authorization: Bearer $BODYBASE_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{"samples": [{"metric": "weight", "value": 79.4}]}' \\\n  "${base}/ingest/json"`} />
          <Example title="Home Assistant (configuration.yaml)" code={`rest:
  - resource: ${base}/summary?keys=resting_hr,weight,hrv
    headers:
      Authorization: !secret bodybase_auth   # "Bearer bbk_…"
    scan_interval: 900
    sensor:
      - name: "Ruhepuls"
        unit_of_measurement: "bpm"
        value_template: >
          {{ (value_json | selectattr('key','eq','resting_hr') | first).last.value }}`} />
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Alle Endpunkte</h2>
          <input type="search" placeholder="Suchen, z. B. sleep oder habits" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 280 }} />
        </div>
        {spec === false && <p className="muted">Die Beschreibung konnte nicht geladen werden.</p>}
        {groups.map(([tag, list]) => (
          <div key={tag} className="api-group">
            <h3>{TAG_LABEL[tag] || tag}</h3>
            {list.map((e) => <Endpoint key={e.method + e.path} spec={spec} {...e} />)}
          </div>
        ))}
      </section>
    </div>
  );
}

function Example({ title, code }) {
  return (
    <div className="api-example">
      <div className="small" style={{ fontWeight: 500 }}>{title}</div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

function Endpoint({ spec, path, method, op }) {
  const [open, setOpen] = useState(false);
  const [vals, setVals] = useState({});
  const [result, setResult] = useState(null);
  const params = (op.parameters || []).filter((p) => p.in === "path" || p.in === "query");
  const bodyRef = op.requestBody?.content?.["application/json"]?.schema;
  const body = resolve(spec, bodyRef);
  async function tryIt() {
    let p = path.replace(/^\/api/, "");
    for (const prm of params.filter((x) => x.in === "path")) p = p.replace(`{${prm.name}}`, encodeURIComponent(vals[prm.name] || ""));
    const qs = params.filter((x) => x.in === "query" && vals[x.name]).map((x) => `${x.name}=${encodeURIComponent(vals[x.name])}`).join("&");
    try {
      setResult({ ok: true, data: await api.get(p + (qs ? `?${qs}` : "")) });
    } catch (e) {
      setResult({ ok: false, data: e.message });
    }
  }
  return (
    <div className={`api-ep${open ? " open" : ""}`}>
      <button type="button" className="api-ep-head" onClick={() => setOpen(!open)}>
        <span className={`api-method m-${method}`}>{method.toUpperCase()}</span>
        <code>{path}</code>
        <span className="muted small api-sum">{op.summary}</span>
      </button>
      {open && (
        <div className="api-ep-body">
          {op.description && <p className="small" style={{ whiteSpace: "pre-wrap" }}>{op.description}</p>}
          {params.length > 0 && (
            <table className="table compact">
              <thead><tr><th>Parameter</th><th>Ort</th><th>Typ</th>{method === "get" && <th>Wert</th>}</tr></thead>
              <tbody>{params.map((p) => {
                const sch = resolve(spec, p.schema) || {};
                return (
                  <tr key={p.name}><td><code>{p.name}</code>{p.required ? " *" : ""}</td><td className="small muted">{p.in}</td>
                    <td className="small muted">{sch.type || ""}{sch.default != null ? ` (Standard ${sch.default})` : ""}</td>
                    {method === "get" && <td><input className="api-input" value={vals[p.name] || ""} onChange={(e) => setVals({ ...vals, [p.name]: e.target.value })} /></td>}</tr>
                );
              })}</tbody>
            </table>
          )}
          {body?.properties && (
            <>
              <div className="small" style={{ fontWeight: 500, margin: "0.6rem 0 0.3rem" }}>Inhalt (JSON)</div>
              <table className="table compact"><tbody>{Object.entries(body.properties).map(([k, v]) => {
                const sch = resolve(spec, v) || {};
                return <tr key={k}><td><code>{k}</code>{body.required?.includes(k) ? " *" : ""}</td><td className="small muted">{sch.type || ""}</td></tr>;
              })}</tbody></table>
            </>
          )}
          {bodyRef && !body?.properties && <p className="small muted">Inhalt: freies JSON-Objekt (siehe Beschreibung).</p>}
          {method === "get" && (
            <div className="actions"><button className="btn small" onClick={tryIt}>Ausprobieren (mit deiner Anmeldung)</button></div>
          )}
          {result && <pre className={`api-result${result.ok ? "" : " bad"}`}><code>{typeof result.data === "string" ? result.data : JSON.stringify(result.data, null, 2).slice(0, 20000)}</code></pre>}
        </div>
      )}
    </div>
  );
}
