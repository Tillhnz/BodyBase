import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { confirmDialog, toast } from "./feedback.jsx";
import { CopyField, Modal, Segmented } from "./ui.jsx";
import { fmtAgo, fmtDate } from "../fmt.js";

/** Persönliche API-Schlüssel: anlegen (einmal anzeigen), Liste mit letzter Nutzung, widerrufen. */
export default function ApiKeys() {
  const [keys, setKeys] = useState(null);
  const [creating, setCreating] = useState(false);
  const [fresh, setFresh] = useState(null);
  useEffect(() => { api.get("/me/api-keys").then(setKeys).catch(() => setKeys([])); }, []);
  async function revoke(k) {
    if (!(await confirmDialog(`Schlüssel „${k.name}“ widerrufen? Programme, die ihn nutzen, verlieren sofort den Zugriff.`, { confirmLabel: "Widerrufen" }))) return;
    await api.del(`/me/api-keys/${k.id}`);
    setKeys((cur) => cur.filter((x) => x.id !== k.id));
  }
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>API</h2>
        <Link className="link small" to="/api-docs">Dokumentation</Link>
      </div>
      <p className="muted small" style={{ marginTop: 0 }}>Schlüssel für andere Programme, z. B. Home Assistant, Skripte oder Auswertungen. Konto, Passwort und Administration bleiben damit gesperrt.</p>
      {keys?.length ? (
        <div className="linked-list">
          {keys.map((k) => (
            <div key={k.id} className="version-row">
              <span><strong>{k.name}</strong> <span className={`pill${k.scope === "write" ? " warn" : ""}`}>{k.scope === "write" ? "lesen & schreiben" : "nur lesen"}</span></span>
              <span className="muted small"><code>{k.prefix}…</code> · {k.last_used_at ? `zuletzt ${fmtAgo(k.last_used_at)}` : "noch nie benutzt"}{k.expires_at ? ` · bis ${fmtDate(k.expires_at)}` : ""}</span>
              <button className="link quiet small" onClick={() => revoke(k)}>Widerrufen</button>
            </div>
          ))}
        </div>
      ) : keys ? <p className="muted small">Noch kein Schlüssel.</p> : null}
      <div className="actions"><button className="btn" onClick={() => setCreating(true)}>Neuer Schlüssel</button></div>
      {creating && <CreateKey onClose={() => setCreating(false)} onCreated={(k) => { setCreating(false); setFresh(k); setKeys((cur) => [k, ...(cur || [])]); }} />}
      {fresh && (
        <Modal title="Schlüssel erstellt" onClose={() => setFresh(null)}>
          <p>Kopiere den Schlüssel jetzt. Er wird <strong>nur dieses eine Mal</strong> angezeigt.</p>
          <CopyField value={fresh.key} label="API-Schlüssel" />
          <p className="small muted">Mitschicken als <code>Authorization: Bearer {fresh.prefix}…</code> oder <code>X-API-Key</code>.</p>
          <div className="actions"><Link className="btn" to="/api-docs" onClick={() => setFresh(null)}>Zur Dokumentation</Link><button className="btn primary" onClick={() => setFresh(null)}>Fertig</button></div>
        </Modal>
      )}
    </section>
  );
}

function CreateKey({ onClose, onCreated }) {
  const [name, setName] = useState("");
  const [scope, setScope] = useState("read");
  const [expires, setExpires] = useState("");
  async function save(e) {
    e.preventDefault();
    try {
      onCreated(await api.post("/me/api-keys", { name, scope, expires_days: expires ? Number(expires) : null }));
    } catch (err) { toast(err.message, "error"); }
  }
  return (
    <Modal title="Neuer API-Schlüssel" onClose={onClose}>
      <form className="stack" onSubmit={save}>
        <label>Wofür?<input value={name} onChange={(e) => setName(e.target.value)} placeholder="z. B. Home Assistant" required maxLength={80} /></label>
        <div>
          <div className="field-label">Rechte</div>
          <Segmented value={scope} onChange={setScope} label="Rechte" options={[{ value: "read", label: "Nur lesen" }, { value: "write", label: "Lesen & schreiben" }]} />
          <p className="hint">Schreiben braucht es nur, wenn das Programm Werte, Trainings oder Gewohnheiten eintragen soll.</p>
        </div>
        <label>Gültig (Tage, leer = unbegrenzt)<input inputMode="numeric" value={expires} onChange={(e) => setExpires(e.target.value.replace(/\D/g, ""))} /></label>
        <div className="actions"><button className="btn primary">Erstellen</button><button type="button" className="btn" onClick={onClose}>Abbrechen</button></div>
      </form>
    </Modal>
  );
}
