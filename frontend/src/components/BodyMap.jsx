import { useState } from "react";
import { fmtNum } from "../fmt.js";

// Eigene, schematische Körperfigur aus Flächen. Jede Fläche gehört zu einem Muskel (Schlüssel wie im Backend).
// Ohne Schlüssel = neutrale Teile (Kopf, Hände, Knie, Füße).
const mirror = (d) => d.replace(/(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)/g, (m, x, y) => `${160 - Number(x)} ${y}`);

const E = (cx, cy, rx, ry, rot = 0) => ({ cx, cy, rx, ry, rot });
const P = (d) => ({ d });

function both(muscle, shape) {
  if (shape.d) return [{ muscle, ...shape }, { muscle, d: mirror(shape.d) }];
  return [{ muscle, ...shape }, { muscle, ...shape, cx: 160 - shape.cx, rot: -shape.rot }];
}

const HEAD = [{ ...E(80, 22, 14, 16) }, { ...P("M73 37 L87 37 L88 50 L72 50 Z"), muscle: "neck" }];

const FRONT = [
  ...HEAD,
  ...both("traps", P("M72 48 L58 56 L72 55 Z")),
  ...both("shoulders", E(50, 64, 11, 11, -20)),
  ...both("chest", P("M79 56 L62 57 Q53 64 56 81 Q66 90 79 86 Z")),
  ...both("biceps", E(46, 97, 7, 17, 8)),
  ...both("forearms", P("M41 116 Q33 138 33 160 L41 161 Q47 140 51 119 Z")),
  ...both(null, E(37, 170, 5.5, 8, 5)),
  { muscle: "abs", d: "M70 90 L90 90 L90 148 Q80 157 70 148 Z" },
  ...both("abs", P("M58 88 L68 92 L68 147 L62 141 Q55 116 58 88 Z")),
  { muscle: null, d: "M62 151 Q80 168 98 151 L99 166 Q80 182 61 166 Z" },
  ...both("abductors", E(57, 172, 5, 11, 5)),
  ...both("adductors", P("M78 174 L67 182 L73 224 L79 214 Z")),
  ...both("quads", P("M61 178 Q53 212 60 251 L72 253 Q76 220 70 186 Z")),
  ...both(null, E(66, 259, 6.5, 6)),
  ...both("calves", P("M60 267 Q56 297 62 327 L68 327 Q72 297 71 267 Z")),
  ...both(null, E(64, 334, 7.5, 4)),
];

const BACK = [
  ...HEAD,
  ...both("upper_back", P("M78 63 L66 61 L60 74 L66 92 L78 97 Z")),
  { muscle: "traps", d: "M80 40 L60 56 L71 61 L80 94 L89 61 L100 56 Z" },
  ...both("shoulders", E(50, 64, 11, 11, 20)),
  ...both("lats", P("M60 77 Q53 101 64 131 L78 141 L78 100 L66 95 Z")),
  ...both("triceps", E(46, 95, 7.5, 17, 8)),
  ...both("forearms", P("M41 116 Q33 138 33 160 L41 161 Q47 140 51 119 Z")),
  ...both(null, E(37, 170, 5.5, 8, 5)),
  { muscle: "lower_back", d: "M70 128 L90 128 L90 153 Q80 160 70 153 Z" },
  ...both("abductors", E(56, 168, 5, 11, 5)),
  ...both("glutes", P("M80 158 L66 156 Q56 166 59 182 Q68 192 80 186 Z")),
  ...both("hamstrings", P("M60 188 Q55 222 62 253 L74 253 Q78 222 77 192 Z")),
  ...both(null, E(67, 259, 6.5, 6)),
  ...both("calves", E(66, 290, 8.5, 23, 2)),
  ...both(null, E(65, 334, 7.5, 4)),
];

export const MUSCLE_LABELS = {
  chest: "Brust", shoulders: "Schultern", triceps: "Trizeps", biceps: "Bizeps", forearms: "Unterarme", lats: "Latissimus",
  upper_back: "Oberer Rücken", traps: "Nacken (Trapez)", lower_back: "Unterer Rücken", abs: "Bauch", glutes: "Gesäß",
  quads: "Oberschenkel vorn", hamstrings: "Oberschenkel hinten", calves: "Waden", adductors: "Adduktoren",
  abductors: "Abduktoren", neck: "Hals",
};

function Figure({ shapes, values, max, title, hover, setHover, color }) {
  return (
    <svg className="body-fig" viewBox="20 2 120 342" role="img" aria-label={title}>
      {shapes.map((s, i) => {
        const v = s.muscle ? values[s.muscle] || 0 : 0;
        const t = s.muscle && max > 0 ? Math.min(1, v / max) : 0;
        const fill = t > 0 ? `color-mix(in srgb, ${color} ${Math.round(28 + 72 * t)}%, var(--body-base))` : undefined;
        const cls = `body-part${s.muscle ? " m" : " n"}${hover && hover === s.muscle ? " hl" : ""}`;
        const props = {
          className: cls, style: fill ? { fill } : undefined,
          onMouseEnter: s.muscle ? () => setHover(s.muscle) : undefined,
          onClick: s.muscle ? () => setHover(hover === s.muscle ? null : s.muscle) : undefined,
        };
        const label = s.muscle ? <title>{`${MUSCLE_LABELS[s.muscle] || s.muscle}: ${fmtNum(v, v % 1 ? 1 : 0)}`}</title> : null;
        return s.d
          ? <path key={i} d={s.d} {...props}>{label}</path>
          : <ellipse key={i} cx={s.cx} cy={s.cy} rx={s.rx} ry={s.ry} transform={s.rot ? `rotate(${s.rot} ${s.cx} ${s.cy})` : undefined} {...props}>{label}</ellipse>;
      })}
      {title === "Vorne"
        ? <path className="body-line" d="M80 92 L80 150 M71 106 L89 106 M71 121 L89 121 M71 136 L89 136" />
        : <path className="body-line" d="M80 96 L80 152" />}
      <text x="80" y="352" textAnchor="middle" className="body-cap">{title}</text>
    </svg>
  );
}

/**
 * Körperkarte vorne und hinten. values: { muscle: Zahl }. unit: Beschriftung der Zahl (z. B. "Sätze").
 * list: daneben die Regionen als Rangliste.
 */
export default function BodyMap({ values = {}, unit = "", color = "var(--c-activity)", list = true, size = "md", detail }) {
  const [hover, setHover] = useState(null);
  const entries = Object.entries(values).filter(([m, v]) => v > 0 && MUSCLE_LABELS[m]).sort((a, b) => b[1] - a[1]);
  const max = entries.length ? entries[0][1] : 0;
  const hv = hover != null ? values[hover] || 0 : null;
  return (
    <div className={`body-map size-${size}${list ? " with-list" : ""}`} onMouseLeave={() => setHover(null)} style={{ "--body-accent": color }}>
      <div className="body-figs">
        <Figure shapes={FRONT} values={values} max={max} title="Vorne" hover={hover} setHover={setHover} color={color} />
        <Figure shapes={BACK} values={values} max={max} title="Hinten" hover={hover} setHover={setHover} color={color} />
        {hover && (
          <div className="body-tip"><strong>{MUSCLE_LABELS[hover]}</strong>
            <span>{hv ? `${fmtNum(hv, hv % 1 ? 1 : 0)} ${unit}` : "nicht trainiert"}</span>
            {detail?.[hover] && <span className="tiny muted">{detail[hover]}</span>}
          </div>
        )}
      </div>
      {list && (
        <ol className="body-list">
          {entries.slice(0, 10).map(([m, v]) => (
            <li key={m} className={hover === m ? "hl" : ""} onMouseEnter={() => setHover(m)}>
              <span>{MUSCLE_LABELS[m]}</span>
              <span className="body-bar"><i style={{ width: `${(v / max) * 100}%` }} /></span>
              <span className="num">{fmtNum(v, v % 1 && v < 10 ? 1 : 0)}</span>
            </li>
          ))}
          {!entries.length && <li className="muted small">Im Zeitraum nichts trainiert.</li>}
        </ol>
      )}
    </div>
  );
}

/** Werte aus Übungsblöcken eines Trainings: Arbeitssätze, Nebenmuskeln halb. */
export function valuesFromBlocks(blocks) {
  const out = {};
  for (const b of blocks || []) {
    const n = (b.sets || []).filter((s) => s.type !== "warmup").length;
    if (!n) continue;
    if (b.primary && MUSCLE_LABELS[b.primary]) out[b.primary] = (out[b.primary] || 0) + n;
    for (const m of b.secondary || []) if (MUSCLE_LABELS[m]) out[m] = (out[m] || 0) + n * 0.5;
  }
  return out;
}
