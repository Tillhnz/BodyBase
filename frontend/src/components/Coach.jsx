import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

const ICON = { warn: "!", tip: "→", good: "✓" };

/** Hinweise und Lob aus den letzten zwei Wochen. */
export default function Coach({ refreshKey, compact }) {
  const [items, setItems] = useState(null);
  useEffect(() => { api.get("/insights").then(setItems).catch(() => setItems([])); }, [refreshKey]);
  if (!items) return null;
  return (
    <section className="panel coach">
      <div className="panel-head"><h2>Coach</h2><span className="tiny muted">letzte Woche im Vergleich zu den Wochen davor</span></div>
      {!items.length ? <p className="muted small">Gerade gibt es nichts anzumerken.</p> : (
        <ul className="coach-list">
          {(compact ? items.slice(0, 5) : items).map((x, i) => (
            <li key={i} className={`coach-item ${x.type}`}>
              <span className="coach-icon" aria-hidden="true">{ICON[x.type]}</span>
              <div>
                {x.area && <span className={`coach-area area-${x.area}`}>{x.area}</span>}
                <strong>{x.title}</strong>
                <p>{x.text}</p>
                {x.advice && <p className="coach-advice"><b>Empfehlung:</b> {x.advice}</p>}
                {x.link && <Link className="link small" to={x.link}>Ansehen →</Link>}
                {x.exercises?.length > 0 && (
                  <div className="chips">
                    {x.exercises.map((e) => <Link key={e.id} className="chip" to={`/strength/exercise/${e.id}`}>{e.name}{e.known ? " ★" : ""}</Link>)}
                  </div>
                )}
                {x.habit_id && <Link className="link small" to="/habits">Eintragen →</Link>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
