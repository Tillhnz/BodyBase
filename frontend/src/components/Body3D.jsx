import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { fmtNum } from "../fmt.js";

// Interaktives 3D-Modell aus einfachen Körpern (Kapseln, Kugeln). Jedes Segment (Arme, Beine, Rumpf) wird nach
// dem gewählten Wert eingefärbt; Drehen mit Maus oder Finger, Antippen zeigt die Werte.

const PARTS = [
  // [Segment, Form, Radius, Länge, x, y, z, Neigung, Breite, Tiefe]
  ["torso", "capsule", 0.2, 0.36, 0, 1.24, 0, 0, 1.35, 0.72],      // Brustkorb
  ["torso", "capsule", 0.17, 0.16, 0, 0.93, 0, 0, 1.3, 0.75],      // Bauch / Taille
  ["torso", "sphere", 0.2, 0, 0, 0.78, 0, 0, 1.25, 0.8],           // Becken
  ["torso", "sphere", 0.105, 0, -0.29, 1.43, 0, 0, 1, 1],          // Schultern
  ["torso", "sphere", 0.105, 0, 0.29, 1.43, 0, 0, 1, 1],
  ["neck", "capsule", 0.055, 0.08, 0, 1.56, 0, 0, 1, 1],
  ["head", "sphere", 0.125, 0, 0, 1.73, 0.01, 0, 0.9, 1.05],
  ["right_arm", "capsule", 0.072, 0.26, -0.35, 1.25, 0, -0.1, 1, 1],
  ["right_arm", "capsule", 0.058, 0.25, -0.385, 0.93, 0.02, -0.04, 1, 1],
  ["hand", "sphere", 0.055, 0, -0.4, 0.73, 0.03, 0, 0.8, 0.6],
  ["left_arm", "capsule", 0.072, 0.26, 0.35, 1.25, 0, 0.1, 1, 1],
  ["left_arm", "capsule", 0.058, 0.25, 0.385, 0.93, 0.02, 0.04, 1, 1],
  ["hand", "sphere", 0.055, 0, 0.4, 0.73, 0.03, 0, 0.8, 0.6],
  ["right_leg", "capsule", 0.105, 0.34, -0.12, 0.5, 0, 0.03, 1, 1],
  ["right_leg", "capsule", 0.075, 0.36, -0.13, 0.1, -0.01, 0, 1, 1],
  ["foot", "box", 0.08, 0.2, -0.13, -0.15, 0.05, 0, 1, 1],
  ["left_leg", "capsule", 0.105, 0.34, 0.12, 0.5, 0, -0.03, 1, 1],
  ["left_leg", "capsule", 0.075, 0.36, 0.13, 0.1, -0.01, 0, 1, 1],
  ["foot", "box", 0.08, 0.2, 0.13, -0.15, 0.05, 0, 1, 1],
];
export const PART_LABEL = { torso: "Rumpf", right_arm: "Rechter Arm", left_arm: "Linker Arm", right_leg: "Rechtes Bein", left_leg: "Linkes Bein" };

function cssColor(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return new THREE.Color(v || fallback);
}

/**
 * values: { torso: {value, text}, left_arm: …} – value 0..1 bestimmt die Farbstärke (bei "change" −1..1).
 * mode: "muscle" | "fat" | "change"
 */
export default function Body3D({ values, mode, height = 380 }) {
  const box = useRef(null);
  const meshes = useRef([]);
  const [tip, setTip] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setFailed(true);  // kein WebGL (z. B. ältere Geräte)
      return undefined;
    }
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(el.clientWidth, height);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, el.clientWidth / height, 0.1, 50);
    camera.position.set(0, 0.95, 4.2);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 1.4));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(2, 3, 4);
    scene.add(sun);
    const back = new THREE.DirectionalLight(0x99aaff, 0.6);
    back.position.set(-2, 1, -3);
    scene.add(back);
    const group = new THREE.Group();
    scene.add(group);
    meshes.current = PARTS.map(([part, form, r, len, x, y, z, tilt, sx = 1, sz = 1]) => {
      const geo = form === "sphere" ? new THREE.SphereGeometry(r, 32, 20)
        : form === "box" ? new THREE.BoxGeometry(r * 1.4, r, len) : new THREE.CapsuleGeometry(r, len, 8, 24);
      const mat = new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0.05 });
      const m = new THREE.Mesh(geo, mat);
      m.position.set(x, y, z);
      m.rotation.z = tilt;
      m.scale.set(sx, 1, sz);
      m.userData.part = part;
      group.add(m);
      return m;
    });
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0.85, 0);
    controls.enablePan = false;
    controls.minDistance = 2.2;
    controls.maxDistance = 6;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 1.2;
    controls.enableDamping = true;
    controls.addEventListener("start", () => { controls.autoRotate = false; });
    controls.update();

    const ray = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    function pick(ev) {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      ray.setFromCamera(pointer, camera);
      const hit = ray.intersectObjects(meshes.current)[0];
      const part = hit?.object.userData.part;
      setTip(PART_LABEL[part] ? { part, x: ev.clientX - rect.left, y: ev.clientY - rect.top } : null);
    }
    renderer.domElement.addEventListener("click", pick);

    let raf = 0;
    const loop = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(loop); };
    loop();
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth || 300;
      renderer.setSize(w, height);
      camera.aspect = w / height;
      camera.updateProjectionMatrix();
    });
    ro.observe(el);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      renderer.domElement.removeEventListener("click", pick);
      controls.dispose();
      meshes.current.forEach((m) => { m.geometry.dispose(); m.material.dispose(); });
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [height]);

  // Farben je Modus und Wert
  useEffect(() => {
    const neutral = cssColor("--line-2", "#33435c");
    const base = mode === "fat" ? cssColor("--c-nutrition", "#f2d15b") : cssColor("--c-body", "#4cc9f0");
    const up = cssColor("--good", "#5ee2a0");
    const down = cssColor("--signal", "#ff5d6c");
    const skin = cssColor("--mute", "#8b97ab");
    for (const m of meshes.current) {
      const v = values?.[m.userData.part];
      let c;
      if (!PART_LABEL[m.userData.part]) c = skin.clone().lerp(neutral, 0.5);
      else if (!v || v.value == null) c = neutral.clone();
      else if (mode === "change") c = neutral.clone().lerp(v.value >= 0 ? up : down, Math.min(1, Math.abs(v.value)));
      else c = neutral.clone().lerp(base, 0.25 + 0.75 * Math.max(0, Math.min(1, v.value)));
      m.material.color.copy(c);
    }
  }, [values, mode]);

  const t = tip && values?.[tip.part];
  if (failed) return <p className="muted small">Dein Browser kann keine 3D-Grafik anzeigen.</p>;
  return (
    <div className="body3d" ref={box} style={{ height }}>
      {tip && (
        <div className="body3d-tip" style={{ left: Math.max(70, tip.x), top: tip.y }}>
          <strong>{PART_LABEL[tip.part]}</strong>
          {t?.lines?.map((l) => <span key={l}>{l}</span>) || <span className="muted">keine Messung</span>}
        </div>
      )}
      <span className="body3d-hint tiny muted">Ziehen zum Drehen · Antippen für Werte</span>
    </div>
  );
}

/** Werte je Segment aus /body-segments für den gewählten Modus. */
export function segmentValues(segments, mode) {
  const out = {};
  const changes = [];
  for (const s of segments || []) {
    if (!PART_LABEL[s.part]) continue;
    const mus = s.muscle?.last, fat = s.fat?.last;
    const total = (mus || 0) + (fat || 0);
    const lines = [
      mus != null ? `Muskeln ${fmtNum(mus, 1)} kg${s.muscle?.change != null ? ` (${s.muscle.change > 0 ? "+" : ""}${fmtNum(s.muscle.change, 1)})` : ""}` : null,
      fat != null ? `Fett ${fmtNum(fat, 1)} kg${s.fat?.change != null ? ` (${s.fat.change > 0 ? "+" : ""}${fmtNum(s.fat.change, 1)})` : ""}` : null,
      mus != null && fat != null ? `Fettanteil ${fmtNum((fat / total) * 100, 0)} %` : null,
    ].filter(Boolean);
    let value = null;
    if (mode === "muscle" && mus != null) value = fat != null ? (mus / total - 0.5) / 0.45 : 1;
    if (mode === "fat" && fat != null) value = mus != null ? Math.min(1, (fat / total) / 0.4) : 1;
    if (mode === "change" && s.muscle?.change != null) { value = s.muscle.change; changes.push(Math.abs(value)); }
    out[s.part] = { value, lines };
  }
  if (mode === "change") {
    const max = Math.max(0.2, ...changes);
    for (const k of Object.keys(out)) if (out[k].value != null) out[k].value /= max;
  }
  return out;
}
