// Eigene, schematische Bewegungsanimation für Übungen ohne Foto: eine Strichfigur wechselt zwischen
// Start- und Endposition. Ein Muster je Bewegungsart (Kniebeuge, Rudern, Curl …), gewählt über Name und Muskeln.

// Punkte: H Kopf, N Hals/Schulter, P Hüfte, K Knie, F Fuß, E Ellbogen, W Hand; K2/F2 zweites Bein (falls anders)
const P = (o) => o;
const STAND = { H: [50, 13], N: [50, 22], P: [50, 50], K: [51, 71], F: [50, 92] };

export const POSES = {
  squat: [P({ ...STAND, E: [42, 28], W: [47, 21] }), P({ H: [58, 37], N: [55, 45], P: [37, 65], K: [58, 70], F: [50, 92], E: [47, 50], W: [53, 43] })],
  hinge: [P({ ...STAND, H: [52, 13], E: [51, 36], W: [51, 51] }), P({ H: [74, 37], N: [68, 41], P: [45, 52], K: [51, 72], F: [50, 92], E: [68, 56], W: [67, 70] })],
  lunge: [P({ ...STAND, K2: [48, 71], F2: [47, 92], E: [48, 36], W: [48, 51] }),
    P({ H: [49, 26], N: [49, 35], P: [48, 62], K: [64, 66], F: [64, 92], K2: [40, 82], F2: [26, 92], E: [48, 49], W: [48, 63] })],
  press_lying: [P({ H: [77, 61], N: [69, 64], P: [43, 66], K: [30, 60], F: [30, 92], E: [69, 52], W: [69, 40] }),
    P({ H: [77, 61], N: [69, 64], P: [43, 66], K: [30, 60], F: [30, 92], E: [60, 70], W: [68, 57] })],
  pushup: [P({ H: [81, 51], N: [73, 56], P: [46, 63], K: [32, 68], F: [17, 73], E: [73, 67], W: [73, 80] }),
    P({ H: [83, 69], N: [74, 73], P: [46, 76], K: [32, 78], F: [17, 79], E: [63, 72], W: [73, 80] })],
  overhead: [P({ ...STAND, E: [57, 32], W: [55, 22] }), P({ ...STAND, E: [53, 11], W: [52, 3] })],
  pulldown: [P({ H: [44, 26], N: [44, 36], P: [44, 64], K: [63, 64], F: [63, 90], E: [47, 15], W: [49, 5] }),
    P({ H: [43, 26], N: [44, 36], P: [44, 64], K: [63, 64], F: [63, 90], E: [36, 49], W: [48, 36] })],
  row: [P({ H: [71, 34], N: [65, 38], P: [44, 52], K: [50, 72], F: [48, 92], E: [65, 53], W: [65, 67] }),
    P({ H: [71, 34], N: [65, 38], P: [44, 52], K: [50, 72], F: [48, 92], E: [52, 46], W: [60, 56] })],
  curl: [P({ ...STAND, E: [52, 37], W: [54, 52] }), P({ ...STAND, E: [52, 37], W: [59, 25] })],
  triceps: [P({ ...STAND, H: [53, 13], N: [52, 22], E: [55, 38], W: [63, 30] }), P({ ...STAND, H: [53, 13], N: [52, 22], E: [55, 38], W: [57, 55] })],
  raise: [P({ ...STAND, E: [51, 37], W: [51, 51] }), P({ ...STAND, E: [63, 25], W: [75, 22] })],
  crunch: [P({ H: [79, 81], N: [70, 84], P: [46, 87], K: [33, 68], F: [22, 90], E: [80, 73], W: [83, 80] }),
    P({ H: [65, 62], N: [61, 70], P: [46, 87], K: [33, 68], F: [22, 90], E: [70, 58], W: [70, 65] })],
  plank: [P({ H: [81, 62], N: [73, 65], P: [46, 67], K: [32, 70], F: [17, 74], E: [73, 82], W: [85, 82] }),
    P({ H: [81, 61], N: [73, 64], P: [46, 63], K: [32, 69], F: [17, 74], E: [73, 82], W: [85, 82] })],
  calf: [P({ ...STAND, E: [49, 36], W: [49, 51] }), P({ H: [50, 7], N: [50, 16], P: [50, 44], K: [51, 65], F: [52, 90], E: [49, 30], W: [49, 45] })],
  bridge: [P({ H: [81, 85], N: [72, 86], P: [47, 89], K: [31, 67], F: [22, 91], E: [64, 90], W: [57, 91] }),
    P({ H: [81, 85], N: [72, 84], P: [49, 70], K: [31, 64], F: [22, 91], E: [64, 90], W: [57, 91] })],
  cardio: [P({ H: [55, 14], N: [53, 23], P: [49, 50], K: [60, 67], F: [55, 90], K2: [42, 72], F2: [33, 86], E: [44, 35], W: [50, 44] }),
    P({ H: [55, 14], N: [53, 23], P: [49, 50], K: [42, 72], F: [33, 86], K2: [60, 67], F2: [55, 90], E: [60, 35], W: [64, 26] })],
};

const RULES = [
  ["cardio", /treadmill|laufband|run|lauf|bike|rad|ergometer|elliptical|crosstrainer|stair|stepper|rowing machine|rudergerät|seil|rope|sprint|jog/],
  ["bridge", /hip thrust|hüft|bridge|bridge|glute/],
  ["calf", /calf|wade/],
  ["plank", /plank|unterarmstütz|seitstütz|side bridge|hollow|dead hang/],
  ["crunch", /crunch|sit.?up|bauch|leg raise|knee raise|beinheben|knieheben|russian|dead bug|v.?up|toes/],
  ["lunge", /lunge|ausfall|split|step.?up|bulgar/],
  ["hinge", /deadlift|kreuzheb|rdl|romanian|rumän|good morning|swing|hyperext|back ext|rückenstreck/],
  ["squat", /squat|kniebeug|leg press|beinpresse|hack|thruster|wall sit/],
  ["pulldown", /pulldown|latzug|latzieh|pull.?up|klimmz|chin/],
  ["row", /row|ruder|face pull|shrug/],
  ["overhead", /overhead press|shoulder press|military|schulterdr|nackendr|arnold|push press/],
  ["pushup", /push.?up|liegest|dip/],
  ["press_lying", /bench|bankdr|chest press|brustpresse|fly|flies|fliegende|pullover|überzug|floor press/],
  ["triceps", /tricep|trizeps|pushdown|skull|french|kickback|extension/],
  ["curl", /curl/],
  ["raise", /raise|heben|reverse fly|rear delt/],
];
const BY_MUSCLE = { quads: "squat", glutes: "bridge", hamstrings: "hinge", lower_back: "hinge", calves: "calf", chest: "press_lying",
  shoulders: "overhead", lats: "pulldown", upper_back: "row", traps: "row", biceps: "curl", triceps: "triceps", forearms: "curl",
  abs: "crunch", cardio: "cardio", full_body: "squat", adductors: "lunge", abductors: "lunge" };

export function patternFor(name, primary) {
  const s = (name || "").toLowerCase();
  for (const [p, re] of RULES) if (re.test(s)) return p;
  return BY_MUSCLE[primary] || "curl";
}

function path(p) {
  const pt = (k) => `${p[k][0]},${p[k][1]}`;
  const leg2 = p.K2 ? `M${pt("P")} L${pt("K2")} L${pt("F2")}` : `M${pt("P")} L${pt("K")} L${pt("F")}`;
  return `M${pt("N")} L${pt("P")} M${pt("P")} L${pt("K")} L${pt("F")} ${leg2} M${pt("N")} L${pt("E")} L${pt("W")}`;
}

const HEAVY = { barbell: "plate", ez_bar: "plate", smith: "plate", plate: "plate", dumbbell: "bell", kettlebell: "bell" };

export default function MoveAnim({ name, primary, equipment, size = 44, animate = true, color = "var(--c-activity)" }) {
  const pattern = patternFor(name, primary);
  const [a, b] = POSES[pattern];
  const dur = pattern === "plank" ? "3.2s" : pattern === "cardio" ? "0.9s" : "2.4s";
  const spline = { calcMode: "spline", keyTimes: "0;0.5;1", keySplines: "0.45 0 0.55 1;0.45 0 0.55 1" };
  const weight = HEAVY[equipment];
  const anim = (attr, va, vb) => (animate ? <animate attributeName={attr} values={`${va};${vb};${va}`} dur={dur} repeatCount="indefinite" {...spline} /> : null);
  return (
    <span className="move-anim" style={{ width: size, height: size, "--c": color }} role="img" aria-label={`Bewegungsablauf ${name || ""}`}>
      <svg viewBox="0 0 100 100">
        <line x1="6" y1="94" x2="94" y2="94" className="mv-ground" />
        {pattern === "press_lying" && <line x1="22" y1="72" x2="80" y2="72" className="mv-bench" />}
        <path d={path(a)} className="mv-body">{anim("d", path(a), path(b))}</path>
        <circle cx={a.H[0]} cy={a.H[1]} r="7" className="mv-head">{anim("cx", a.H[0], b.H[0])}{anim("cy", a.H[1], b.H[1])}</circle>
        {weight && (
          <circle cx={a.W[0]} cy={a.W[1]} r={weight === "plate" ? 8 : 4.5} className="mv-weight">{anim("cx", a.W[0], b.W[0])}{anim("cy", a.W[1], b.W[1])}</circle>
        )}
      </svg>
    </span>
  );
}
