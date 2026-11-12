import { useEffect, useState } from "react";
import { api } from "../api.js";
import { toast } from "../components/feedback.jsx";

/* Abend-Erinnerung an offene Gewohnheiten (Push über die App ntfy). */
export default function Reminder() {
  const [c, setC] = useState(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get("/habit-reminder").then(setC).catch(() => {}); }, []);
  if (!c) return null;
  async function save(next) {
    setBusy(true);
    try {
      const r = await api.put("/habit-reminder", { enabled: next.enabled, time: next.time, topic: next.topic });
      setC({ ...c, ...r });
      toast(r.enabled ? `Erinnerung um ${r.time} Uhr aktiv` : "Erinnerung aus");
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  async function test() {
    try { await api.post("/habit-reminder/test"); toast("Test-Nachricht verschickt"); } catch (e) { toast(e.message, "error"); }
  }
  return (
    <section className="panel reminder-panel">
      <button type="button" className="reminder-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>🔔 Abend-Erinnerung</span>
        <span className="muted small">{c.enabled ? `täglich ${c.time} Uhr, wenn noch etwas offen ist` : "aus"} {open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <form className="reminder-form" onSubmit={(e) => { e.preventDefault(); save(c); }}>
          <label className="check"><input type="checkbox" checked={c.enabled} onChange={(e) => setC({ ...c, enabled: e.target.checked })} />Erinnern, wenn abends noch Gewohnheiten offen sind</label>
          <label>Uhrzeit<input type="time" value={c.time} onChange={(e) => setC({ ...c, time: e.target.value })} /></label>
          <label>ntfy-Thema{c.server_topic ? " (leer = Server-Thema)" : ""}
            <input value={c.topic} placeholder={c.server_topic ? "Server-Thema" : "z. B. bodybase-till-7f3k"} onChange={(e) => setC({ ...c, topic: e.target.value.trim() })} />
          </label>
          <p className="tiny muted" style={{ margin: 0 }}>Die Nachricht kommt über die App <b>ntfy</b> (Thema dort abonnieren) und öffnet beim Antippen die Gewohnheiten-Seite. Ist alles erledigt, kommt nichts.</p>
          <div className="actions">
            <button type="button" className="btn" onClick={test}>Test senden</button>
            <button className="btn primary" disabled={busy}>Speichern</button>
          </div>
        </form>
      )}
    </section>
  );
}
