import { useState } from "react";
import { Link } from "react-router-dom";
import ExercisePicker from "./ExercisePicker.jsx";
import ExerciseThumb from "./ExerciseThumb.jsx";
import {
  GROUP_COLORS, REST_OPTIONS, SET_TYPES, colLabel, columnsFor, emptySet, fmtClock, fmtRest, newKey, parseNum, setText, toDraftBlock,
} from "./shared.js";

/**
 * Übungen mit Sätzen bearbeiten.
 * mode: "log" (laufendes Training mit Abhaken und Pause), "edit" (fertiges Training), "plan" (Routine)
 */
export default function BlockEditor({ blocks, onChange, mode, byId, meta, previous = {}, onSetDone }) {
  const [picker, setPicker] = useState(null); // { replace: key } oder { add: true }
  const update = (key, fn) => onChange(blocks.map((b) => (b.key === key ? fn(b) : b)));

  function addExercises(ids) {
    const fresh = ids.map((id) => {
      const prev = previous[String(id)];
      const n = prev?.length ? Math.min(prev.length, 8) : 3;
      return toDraftBlock({ exercise_id: id, rest_s: 90, sets: Array.from({ length: n }, (_, i) => ({ type: prev?.[i]?.type || "normal" })) });
    });
    if (picker?.replace) {
      onChange(blocks.flatMap((b) => (b.key === picker.replace ? [{ ...fresh[0], sets: b.sets.map((s) => ({ ...s, done: false })) }] : [b])));
    } else {
      onChange([...blocks, ...fresh]);
    }
    setPicker(null);
  }

  function move(key, dir) {
    const i = blocks.findIndex((b) => b.key === key);
    const j = i + dir;
    if (j < 0 || j >= blocks.length) return;
    const next = blocks.slice();
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  }

  function toggleSuperset(key) {
    const i = blocks.findIndex((b) => b.key === key);
    const b = blocks[i];
    if (b.superset != null) { // aus dem Supersatz lösen
      onChange(blocks.map((x) => (x.key === key ? { ...x, superset: null } : x)));
      return;
    }
    const nextB = blocks[i + 1];
    if (!nextB) return;
    const id = nextB.superset ?? Math.max(0, ...blocks.map((x) => x.superset ?? -1)) + 1;
    onChange(blocks.map((x) => (x.key === key || x.key === nextB.key ? { ...x, superset: id } : x)));
  }

  return (
    <div className="blocks">
      {blocks.map((b, i) => (
        <ExerciseBlock key={b.key} block={b} index={i} count={blocks.length} mode={mode} ex={byId?.get(b.exercise_id)} meta={meta}
          previous={previous[String(b.exercise_id)]} onChange={(fn) => update(b.key, fn)}
          onRemove={() => onChange(blocks.filter((x) => x.key !== b.key))} onMove={(d) => move(b.key, d)}
          onReplace={() => setPicker({ replace: b.key })} onSuperset={() => toggleSuperset(b.key)}
          nextInSuperset={blocks[i + 1]?.superset != null && blocks[i + 1]?.superset === b.superset}
          onSetDone={onSetDone} />
      ))}
      <button type="button" className="btn primary block-add" onClick={() => setPicker({ add: true })}>+ Übung hinzufügen</button>
      {picker && <ExercisePicker multi={!picker.replace} title={picker.replace ? "Übung ersetzen" : "Übungen hinzufügen"}
        onClose={() => setPicker(null)} onPick={addExercises} />}
    </div>
  );
}

function ExerciseBlock({ block, index, count, mode, ex, meta, previous, onChange, onRemove, onMove, onReplace, onSuperset, nextInSuperset, onSetDone }) {
  const [menu, setMenu] = useState(false);
  const [showNote, setShowNote] = useState(!!block.notes);
  const kind = ex?.kind || "weight_reps";
  const cols = columnsFor(kind);
  const setSet = (key, patch) => onChange((b) => ({ ...b, sets: b.sets.map((s) => (s.key === key ? { ...s, ...patch } : s)) }));

  function addSet() {
    onChange((b) => {
      const last = b.sets[b.sets.length - 1];
      const s = emptySet(last?.type === "warmup" ? "normal" : last?.type || "normal");
      if (last) { s.kg = last.kg; s.reps = last.reps; s.duration_s = last.duration_s; s.distance_m = last.distance_m; }
      return { ...b, sets: [...b.sets, s] };
    });
  }

  function toggleDone(s, i) {
    const nowDone = !s.done;
    const patch = { done: nowDone };
    if (nowDone) { // leere Felder mit den Werten vom letzten Mal füllen, wie in Hevy
      const p = previous?.[i];
      for (const c of cols) {
        if (s[c] === "" || s[c] == null) {
          if (c === "distance_m" && p?.distance_m != null) patch[c] = p.distance_m / 1000;
          else if (p?.[c] != null) patch[c] = p[c];
        }
      }
      const hasValue = cols.some((c) => (patch[c] ?? s[c]) !== "" && (patch[c] ?? s[c]) != null);
      if (!hasValue) return; // nichts eingetragen und kein Vorwert
    }
    setSet(s.key, patch);
    if (nowDone && onSetDone) onSetDone(block);
  }

  let n = 0;
  const groupColor = GROUP_COLORS[ex?.group] || "var(--iris)";
  return (
    <section className={`panel block${block.superset != null ? " in-superset" : ""}${nextInSuperset ? " superset-next" : ""}`} style={{ "--c": groupColor }}>
      <div className="block-head">
        <ExerciseThumb media={ex?.media} name={ex?.name} primary={ex?.primary} equipment={ex?.equipment} size={46} color={groupColor} />
        <div className="block-title">
          {ex ? <Link to={`/strength/exercise/${ex.id}`} className="link">{ex.name}</Link> : <strong>Übung</strong>}
          <div className="tiny muted">
            {ex ? `${meta?.muscles?.[ex.primary] || ex.primary}` : ""}
            {block.superset != null && <span className="pill iris" style={{ marginLeft: "0.4rem" }}>Supersatz {block.superset + 1}</span>}
          </div>
        </div>
        {mode !== "edit" && (
          <select className="rest-select" value={block.rest_s ?? 0} aria-label="Pause"
            onChange={(e) => onChange((b) => ({ ...b, rest_s: Number(e.target.value) }))}>
            {REST_OPTIONS.map((r) => <option key={r} value={r}>⏱ {fmtRest(r)}</option>)}
          </select>
        )}
        <div className="menu-wrap">
          <button type="button" className="icon-btn" aria-label="Optionen" onClick={() => setMenu(!menu)}>⋯</button>
          {menu && (
            <div className="menu" onMouseLeave={() => setMenu(false)}>
              <button type="button" onClick={() => { setShowNote(true); setMenu(false); }}>Notiz</button>
              <button type="button" onClick={() => { onReplace(); setMenu(false); }}>Übung ersetzen</button>
              <button type="button" disabled={block.superset == null && index === count - 1} onClick={() => { onSuperset(); setMenu(false); }}>
                {block.superset != null ? "Aus Supersatz lösen" : "Supersatz mit nächster"}</button>
              <button type="button" disabled={index === 0} onClick={() => { onMove(-1); setMenu(false); }}>Nach oben</button>
              <button type="button" disabled={index === count - 1} onClick={() => { onMove(1); setMenu(false); }}>Nach unten</button>
              <button type="button" className="danger" onClick={() => { onRemove(); setMenu(false); }}>Entfernen</button>
            </div>
          )}
        </div>
      </div>
      {showNote && (
        <textarea className="block-note" rows={1} placeholder="Notiz zur Übung (z. B. Sitzhöhe 4)" value={block.notes || ""}
          onChange={(e) => onChange((b) => ({ ...b, notes: e.target.value }))} />
      )}
      <div className={`sets-grid cols-${cols.length}${mode === "log" ? " with-check" : ""}`}>
        <div className="sets-h">Satz</div>
        <div className="sets-h">Vorher</div>
        {cols.map((c) => <div key={c} className="sets-h">{colLabel(c, kind)}</div>)}
        {mode === "log" && <div className="sets-h" aria-label="Erledigt">✓</div>}
        {block.sets.map((s, i) => {
          if (s.type !== "warmup") n += 1;
          const p = previous?.[i];
          return (
            <SetRow key={s.key} s={s} label={s.type === "warmup" ? "W" : String(n)} prev={p} kind={kind} cols={cols} mode={mode}
              onChange={(patch) => setSet(s.key, patch)} onToggle={() => toggleDone(s, i)}
              onRemove={() => onChange((b) => ({ ...b, sets: b.sets.filter((x) => x.key !== s.key) }))} />
          );
        })}
      </div>
      <button type="button" className="btn small ghost add-set" onClick={addSet}>+ Satz</button>
    </section>
  );
}

function SetRow({ s, label, prev, kind, cols, mode, onChange, onToggle, onRemove }) {
  const [open, setOpen] = useState(false);
  const t = SET_TYPES.find((x) => x.value === s.type) || SET_TYPES[0];
  const ph = (c) => {
    if (!prev) return "";
    if (c === "distance_m") return prev.distance_m != null ? String(prev.distance_m / 1000).replace(".", ",") : "";
    if (c === "duration_s") return prev.duration_s != null ? fmtClock(prev.duration_s) : "";
    return prev[c] != null ? String(prev[c]).replace(".", ",") : "";
  };
  const show = (c) => {
    const v = s[c];
    if (v === "" || v == null) return "";
    if (c === "duration_s" && typeof v === "number") return fmtClock(v);
    return String(v).replace(".", ",");
  };
  function copyPrev() {
    if (!prev) return;
    const patch = {};
    for (const c of cols) {
      if (c === "distance_m") patch[c] = prev.distance_m != null ? prev.distance_m / 1000 : "";
      else patch[c] = prev[c] ?? "";
    }
    onChange(patch);
  }
  return (
    <>
      <div className="set-type-wrap">
        <button type="button" className={`set-label t-${s.type}`} onClick={() => setOpen(!open)} aria-label={`Satz ${label}, ${t.label}`}>{label}</button>
        {open && (
          <div className="menu" onMouseLeave={() => setOpen(false)}>
            {SET_TYPES.map((x) => (
              <button type="button" key={x.value} className={x.value === s.type ? "on" : ""} onClick={() => { onChange({ type: x.value }); setOpen(false); }}>
                <span className={`set-label t-${x.value}`}>{x.short || "1"}</span> {x.label}</button>
            ))}
            <button type="button" className="danger" onClick={() => { onRemove(); setOpen(false); }}>Satz löschen</button>
          </div>
        )}
      </div>
      <button type="button" className="set-prev" onClick={copyPrev} disabled={!prev} title="Werte vom letzten Mal übernehmen">
        {prev ? setText(prev, kind) : "–"}
      </button>
      {cols.map((c) => (
        <input key={c} className={`set-input${s.done ? " done" : ""}`} inputMode={c === "duration_s" ? "numeric" : c === "reps" ? "numeric" : "decimal"}
          value={show(c)} placeholder={ph(c)} aria-label={colLabel(c, kind)}
          onChange={(e) => onChange({ [c]: c === "duration_s" ? e.target.value : e.target.value.replace(/[^0-9.,-]/g, "") })}
          onFocus={(e) => e.target.select()} />
      ))}
      {mode === "log" && (
        <button type="button" className={`set-check${s.done ? " on" : ""}`} onClick={onToggle} aria-pressed={s.done} aria-label="Satz erledigt">✓</button>
      )}
    </>
  );
}

export { newKey, parseNum };
