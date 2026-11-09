import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

/* Update-Assistent: kleiner Hinweis unten in der Ecke, sobald eine neue Version auf GitHub bereitliegt (nur für Admins). */

const KEY = "bb-update-dismissed";

function dismissed(id) {
  try { return localStorage.getItem(KEY) === id; } catch { return false; }
}

export default function UpdateToast({ update }) {
  const [hidden, setHidden] = useState(() => !update || dismissed(update.id));
  const [state, setState] = useState(null); // null | "running" | Fehlertext
  const [open, setOpen] = useState(false);
  if (hidden || !update) return null;
  function later() {
    try { localStorage.setItem(KEY, update.id); } catch { /* egal */ }
    setHidden(true);
  }
  async function install() {
    setState("running");
    try {
      await api.post("/admin/update");
    } catch (e) {
      setState(e.message || "Update konnte nicht gestartet werden.");
    }
  }
  const sec = update.changes.some((c) => /bump|security|sicherheit|cve-|dependabot/i.test(c));
  return (
    <div className={`update-toast${sec ? " sec" : ""}`} role="status" aria-live="polite">
      <div className="update-toast-head">
        <span className="update-dot" aria-hidden="true" />
        <div>
          <strong>{sec ? "Sicherheitsupdate verfügbar" : "Update verfügbar"}</strong>
          <span className="muted small">{update.count} {update.count === 1 ? "Änderung" : "Änderungen"} · <button type="button" className="link quiet small" onClick={() => setOpen(!open)}>{open ? "weniger" : "Details"}</button></span>
        </div>
        <button type="button" className="update-x" aria-label="Später" onClick={later}>×</button>
      </div>
      {open && <ul className="update-list">{update.changes.map((c) => <li key={c}>{c.split("  ").slice(-1)[0]}</li>)}</ul>}
      {state === "running" ? (
        <p className="small" style={{ margin: 0 }}>Update läuft … Den Fortschritt siehst du unter <Link className="link" to="/admin">Administration</Link>. Die Seite lädt danach neu.</p>
      ) : (
        <>
          {state && <p className="small bad-text" style={{ margin: 0 }}>{state}</p>}
          <div className="update-actions">
            <button type="button" className="btn" onClick={later}>Später</button>
            <button type="button" className="btn primary" onClick={install}>Jetzt aktualisieren</button>
          </div>
        </>
      )}
    </div>
  );
}
