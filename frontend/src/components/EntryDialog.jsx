import { useState } from "react";
import { api } from "../api.js";
import { useMeta } from "../meta.js";
import { toast } from "./feedback.jsx";
import { Modal } from "./ui.jsx";

const MANUAL = ["weight", "body_fat", "muscle_mass", "waist", "bp_systolic", "bp_diastolic", "resting_hr", "hrv", "spo2", "body_temp",
  "glucose", "vo2max", "steps", "water", "calories_in", "protein", "mindful_minutes"];

function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

/** Wert von Hand eintragen. Blutdruck: beide Werte auf einmal. */
export default function EntryDialog({ metric: initial, onClose, onSaved }) {
  const meta = useMeta();
  const [metric, setMetric] = useState(initial && MANUAL.includes(initial) ? initial : initial || "weight");
  const [value, setValue] = useState("");
  const [value2, setValue2] = useState("");
  const [when, setWhen] = useState(nowLocal());
  const [busy, setBusy] = useState(false);
  const isBp = metric === "bp_systolic" || metric === "bp_diastolic";
  const m = meta?.byKey[metric];
  const options = MANUAL.includes(metric) ? MANUAL : [metric, ...MANUAL];

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const time = new Date(when).toISOString();
      const num = (s) => Number(String(s).replace(",", "."));
      if (isBp) {
        await api.post("/entries", { metric: "bp_systolic", value: num(value), time });
        await api.post("/entries", { metric: "bp_diastolic", value: num(value2), time });
      } else {
        await api.post("/entries", { metric, value: num(value), time });
      }
      toast("Gespeichert");
      onSaved?.();
      onClose();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Wert eintragen" onClose={onClose}>
      <form className="stack" onSubmit={save}>
        <label>Messgröße
          <select value={isBp ? "bp_systolic" : metric} onChange={(e) => setMetric(e.target.value)}>
            {options.filter((k) => k !== "bp_diastolic").map((k) => (
              <option key={k} value={k}>{k === "bp_systolic" ? "Blutdruck" : meta?.byKey[k]?.label || k}</option>
            ))}
          </select>
        </label>
        {isBp ? (
          <div className="form-grid">
            <label>Systolisch (mmHg)<input inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} required /></label>
            <label>Diastolisch (mmHg)<input inputMode="decimal" value={value2} onChange={(e) => setValue2(e.target.value)} required /></label>
          </div>
        ) : (
          <label>Wert{m?.unit ? ` (${m.unit})` : ""}
            <input inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} required autoFocus />
          </label>
        )}
        <label>Zeitpunkt<input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} required /></label>
        <div className="actions">
          <button type="button" className="btn" onClick={onClose}>Abbrechen</button>
          <button className="btn primary" disabled={busy}>Speichern</button>
        </div>
      </form>
    </Modal>
  );
}
