import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "../api.js";
import { decodePolyline, Route } from "./charts.jsx";

let configPromise = null;
function loadMapConfig() {
  if (!configPromise) configPromise = api.get("/map-config").catch((e) => { configPromise = null; throw e; });
  return configPromise;
}
export function resetMapConfig() { configPromise = null; }

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/**
 * Echte Karte mit Strecke, Start und Ziel. hover = [lat, lng] setzt einen Marker (aus den Verlaufsdiagrammen).
 * Ohne Kartenserver (offline, gesperrt) bleibt die gezeichnete Strecke als Ersatz.
 */
export default function RouteMap({ polyline, hover, height = 420 }) {
  const boxRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const [cfg, setCfg] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => { loadMapConfig().then(setCfg).catch(() => setFailed(true)); }, []);

  useEffect(() => {
    if (!cfg || !boxRef.current) return undefined;
    const pts = decodePolyline(polyline || "");
    if (pts.length < 2) return undefined;
    const map = L.map(boxRef.current, { zoomControl: true, scrollWheelZoom: false, attributionControl: true });
    mapRef.current = map;
    const tiles = L.tileLayer(cfg.url, {
      maxZoom: cfg.max_zoom, subdomains: cfg.subdomains, attribution: cfg.attribution,
      referrerPolicy: "strict-origin-when-cross-origin", // OpenStreetMap verlangt einen Referer
    }).addTo(map);
    let errors = 0;
    tiles.on("tileerror", () => { errors += 1; if (errors > 12) setFailed(true); });
    const color = cssVar("--c-activity", "#f5a524");
    L.polyline(pts, { color: "#0d1119", weight: 7, opacity: 0.35 }).addTo(map);
    const line = L.polyline(pts, { color, weight: 4, opacity: 0.95, lineJoin: "round" }).addTo(map);
    L.circleMarker(pts[0], { radius: 7, color: "#0d1119", weight: 2, fillColor: cssVar("--good", "#5ee2a0"), fillOpacity: 1 }).addTo(map).bindTooltip("Start");
    L.circleMarker(pts[pts.length - 1], { radius: 7, color: "#0d1119", weight: 2, fillColor: cssVar("--signal", "#ff5d6c"), fillOpacity: 1 }).addTo(map).bindTooltip("Ziel");
    markerRef.current = L.circleMarker(pts[0], { radius: 7, color: "#fff", weight: 2, fillColor: color, fillOpacity: 1, interactive: false });
    map.fitBounds(line.getBounds(), { padding: [24, 24] });
    map.on("click", () => map.scrollWheelZoom.enable());
    map.on("mouseout", () => map.scrollWheelZoom.disable());
    return () => { map.remove(); mapRef.current = null; markerRef.current = null; };
  }, [polyline, cfg]);

  useEffect(() => {
    const m = markerRef.current, map = mapRef.current;
    if (!m || !map) return;
    if (hover) {
      m.setLatLng(hover);
      if (!map.hasLayer(m)) m.addTo(map);
    } else if (map.hasLayer(m)) {
      map.removeLayer(m);
    }
  }, [hover]);

  if (failed) return <Route polyline={polyline} />;
  return <div className={`route-map${cfg && !cfg.dark ? " light-tiles" : ""}`} ref={boxRef} style={{ height }} />;
}
