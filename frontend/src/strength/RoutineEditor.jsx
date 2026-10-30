import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { confirmDialog, Loading, toast } from "../components/feedback.jsx";
import BlockEditor from "./BlockEditor.jsx";
import { fromDraftBlock, routineToBlocks, startWorkout, useExercises } from "./shared.js";

export default function RoutineEditor() {
  const { id } = useParams();
  const isNew = id === "new";
  const navigate = useNavigate();
  const ex = useExercises();
  const [r, setR] = useState(isNew ? { name: "", folder: "", notes: "", blocks: [] } : null);
  const [busy, setBusy] = useState(false);
  const [previous, setPrevious] = useState({});

  useEffect(() => {
    if (isNew) return;
    api.get(`/strength/routines/${id}`).then((x) => setR({ ...x, folder: x.folder || "", notes: x.notes || "", blocks: routineToBlocks(x) }))
      .catch((e) => { toast(e.message, "error"); navigate("/strength"); });
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const ids = r ? [...new Set(r.blocks.map((b) => b.exercise_id))].join(",") : "";
  useEffect(() => {
    if (ids) api.post("/strength/previous", { ids: ids.split(",").map(Number) }).then(setPrevious).catch(() => {});
  }, [ids]);

  if (!r || !ex) return <Loading rows={3} />;

  async function save() {
    setBusy(true);
    try {
      const body = { name: r.name, folder: r.folder, notes: r.notes, exercises: r.blocks.map((b) => fromDraftBlock(b)) };
      const saved = isNew ? await api.post("/strength/routines", body) : await api.put(`/strength/routines/${id}`, body);
      toast("Routine gespeichert");
      if (isNew) navigate(`/strength/routine/${saved.id}`, { replace: true });
      return saved;
    } catch (err) {
      toast(err.message, "error");
      return null;
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (!(await confirmDialog(`Routine „${r.name}“ löschen? Bisherige Trainings bleiben erhalten.`))) return;
    await api.del(`/strength/routines/${id}`);
    navigate("/strength");
  }
  async function start() {
    const saved = await save();
    if (!saved) return;
    const ok = await startWorkout(navigate, { name: saved.name, routine: saved, blocks: routineToBlocks(saved) });
    if (!ok) toast("Es läuft schon ein Training.", "error");
  }

  return (
    <div className="strength-log">
      <div className="page-head">
        <div>
          <p style={{ margin: 0 }}><Link className="link quiet small" to="/strength">Kraft</Link></p>
          <h1>{isNew ? "Neue Routine" : r.name || "Routine"}</h1>
          <p>Lege Übungen, Sätze und Zielwerte fest. Beim Training stehen sie als Vorgabe bereit.</p>
        </div>
        <div className="actions">
          {!isNew && <button className="btn danger" onClick={remove}>Löschen</button>}
          <button className="btn" onClick={save} disabled={busy}>Speichern</button>
          <button className="btn primary" onClick={start} disabled={busy || !r.blocks.length}>Speichern und starten</button>
        </div>
      </div>
      <section className="panel">
        <div className="form-grid">
          <label>Name<input value={r.name} onChange={(e) => setR({ ...r, name: e.target.value })} placeholder="z. B. Push A" maxLength={120} /></label>
          <label>Ordner (optional)<input value={r.folder} onChange={(e) => setR({ ...r, folder: e.target.value })} placeholder="z. B. PPL" maxLength={80} /></label>
        </div>
        <label style={{ marginTop: "1rem" }}>Notiz<textarea rows={2} value={r.notes} onChange={(e) => setR({ ...r, notes: e.target.value })} /></label>
      </section>
      <BlockEditor blocks={r.blocks} onChange={(blocks) => setR({ ...r, blocks })} mode="plan" byId={ex.byId} meta={ex.meta} previous={previous} />
    </div>
  );
}
