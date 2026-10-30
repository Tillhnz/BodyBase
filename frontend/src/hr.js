// Pulsmessung live per Bluetooth (Web Bluetooth, Standard-Herzfrequenzdienst 0x180D).
// Funktioniert mit WHOOP (Heart Rate Broadcast), Brustgurten (Polar, Garmin HRM, Wahoo) und vielen Uhren im Sendemodus.
// Braucht Chrome/Edge (Android, Windows, macOS) und HTTPS. Safari auf dem iPhone unterstützt Web Bluetooth nicht.

const listeners = new Set();
let state = { status: "idle", bpm: null, device: null, error: null, at: 0 };
let device = null;
let wantConnected = false;
let retry = 0;

function emit(patch) {
  state = { ...state, ...patch };
  listeners.forEach((fn) => fn(state));
}

export function hrSupported() {
  return typeof navigator !== "undefined" && !!navigator.bluetooth && window.isSecureContext;
}

export function hrUnsupportedReason() {
  if (typeof navigator === "undefined" || !navigator.bluetooth) return "Dieser Browser kann kein Bluetooth. Nutze Chrome auf Android oder am Computer (Safari auf dem iPhone kann es nicht).";
  if (!window.isSecureContext) return "Bluetooth geht nur über HTTPS. Öffne BodyBase über deine HTTPS-Adresse.";
  return null;
}

export function subscribeHr(fn) {
  listeners.add(fn);
  fn(state);
  return () => listeners.delete(fn);
}

export function hrState() { return state; }

function parse(value) {
  const flags = value.getUint8(0);
  return flags & 0x01 ? value.getUint16(1, true) : value.getUint8(1);
}

function onValue(e) {
  const bpm = parse(e.target.value);
  if (bpm > 20 && bpm < 255) emit({ bpm, at: Date.now(), status: "connected" });
}

async function attach(dev) {
  emit({ status: "connecting", device: dev.name || "Pulsmesser", error: null });
  const server = await dev.gatt.connect();
  const service = await server.getPrimaryService("heart_rate");
  const ch = await service.getCharacteristic("heart_rate_measurement");
  ch.addEventListener("characteristicvaluechanged", onValue);
  await ch.startNotifications();
  retry = 0;
  emit({ status: "connected" });
}

async function onDisconnect() {
  if (!wantConnected || !device) { emit({ status: "idle", bpm: null }); return; }
  emit({ status: "reconnecting", bpm: null });
  while (wantConnected && retry < 8) {
    retry += 1;
    await new Promise((r) => setTimeout(r, Math.min(15000, 1000 * retry)));
    try { await attach(device); return; } catch { /* nächster Versuch */ }
  }
  emit({ status: "lost", error: "Verbindung verloren. Tippe auf den Puls, um neu zu verbinden." });
}

/** Gerät wählen (braucht einen Tipp) und verbinden. */
export async function connectHr() {
  const why = hrUnsupportedReason();
  if (why) throw new Error(why);
  wantConnected = true;
  try {
    const dev = await navigator.bluetooth.requestDevice({ filters: [{ services: ["heart_rate"] }], optionalServices: ["battery_service"] });
    if (device && device !== dev) device.removeEventListener("gattserverdisconnected", onDisconnect);
    device = dev;
    device.addEventListener("gattserverdisconnected", onDisconnect);
    await attach(device);
  } catch (e) {
    wantConnected = false;
    emit({ status: "idle", error: e.name === "NotFoundError" ? null : e.message });
    if (e.name !== "NotFoundError") throw e;
  }
}

/** Nach dem Neuladen ohne Auswahl wieder verbinden, wenn der Browser das Gerät kennt (Chrome mit getDevices). */
export async function reconnectKnownHr() {
  if (!hrSupported() || !navigator.bluetooth.getDevices || device) return false;
  try {
    const list = await navigator.bluetooth.getDevices();
    if (!list.length) return false;
    device = list[0];
    wantConnected = true;
    device.addEventListener("gattserverdisconnected", onDisconnect);
    await attach(device);
    return true;
  } catch {
    wantConnected = false;
    emit({ status: "idle" });
    return false;
  }
}

export function disconnectHr() {
  wantConnected = false;
  try { device?.gatt?.disconnect(); } catch { /* egal */ }
  emit({ status: "idle", bpm: null });
}

/** Herzfrequenzzonen nach Anteil an der maximalen Herzfrequenz. */
export const ZONES = [
  { name: "Zone 1", from: 0.5, color: "var(--c-body)" },
  { name: "Zone 2", from: 0.6, color: "var(--c-recovery)" },
  { name: "Zone 3", from: 0.7, color: "var(--c-nutrition)" },
  { name: "Zone 4", from: 0.8, color: "var(--c-activity)" },
  { name: "Zone 5", from: 0.9, color: "var(--c-heart)" },
];

export function maxHrFor(user) {
  const y = user?.birth_year;
  return y ? Math.round(208 - 0.7 * (new Date().getFullYear() - y)) : 190;
}

export function zoneOf(bpm, maxHr) {
  const p = bpm / maxHr;
  let z = -1;
  ZONES.forEach((zone, i) => { if (p >= zone.from) z = i; });
  return z;
}
