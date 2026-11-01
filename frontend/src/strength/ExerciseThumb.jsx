import { useEffect, useState } from "react";
import MoveAnim from "./MoveAnim.jsx";

/**
 * Vorschaubild einer Übung. Zwei Fotos (Start- und Endposition) im Wechsel ergeben die Animation:
 * immer bei animate, sonst beim Darüberfahren. Ohne Bild: farbiger Kreis mit Anfangsbuchstaben.
 */
export default function ExerciseThumb({ media, name, primary, equipment, size = 40, animate = false, color, className = "" }) {
  const [hover, setHover] = useState(false);
  const [frame, setFrame] = useState(0);
  const [failed, setFailed] = useState(false);
  const run = (animate || hover) && media && !failed;
  useEffect(() => {
    if (!run) { setFrame(0); return undefined; }
    const t = setInterval(() => setFrame((f) => 1 - f), animate ? 1100 : 750);
    return () => clearInterval(t);
  }, [run, animate]);
  useEffect(() => setFailed(false), [media]);
  if (!media || failed) {  // kein Foto: eigene, schematische Bewegungsanimation
    return (
      <span className={className} style={{ display: "contents" }} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
        <MoveAnim name={name} primary={primary} equipment={equipment} size={size} animate={animate || hover} color={color} />
      </span>
    );
  }
  const src = (n) => `/api/strength/media/${encodeURIComponent(media)}/${n}.jpg`;
  return (
    <span className={`ex-thumb ${className}`} style={{ width: size, height: size }} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      role="img" aria-label={name ? `Bewegungsablauf ${name}` : "Übung"}>
      <img src={src(0)} alt="" loading="lazy" onError={() => setFailed(true)} />
      {(run || frame === 1) && <img src={src(1)} alt="" loading="lazy" className={frame === 1 ? "show" : ""} />}
    </span>
  );
}
