// Die Anmeldung steckt in einem HttpOnly-Cookie, das Skripte nicht lesen können.
// Jede Anfrage trägt die Kennung X-BB-Request; ohne sie lehnt das Backend schreibende Anfragen ab (Schutz vor CSRF).

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => (onUnauthorized = fn);

async function request(method, path, body, opts = {}) {
  const headers = { "X-BB-Request": "1" };
  let payload;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { method, headers, credentials: "same-origin", body: payload, signal: opts.signal });
  if (res.status === 401 && !path.startsWith("/auth/")) onUnauthorized();
  if (!res.ok) {
    let msg = `Fehler ${res.status}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") msg = data.detail;
      else if (Array.isArray(data.detail)) msg = data.detail.map((d) => String(d.msg).replace(/^Value error, /, "")).join(", ");
    } catch {
      /* keine JSON-Antwort */
    }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  get: (p, o) => request("GET", p, undefined, o),
  post: (p, b) => request("POST", p, b ?? {}),
  put: (p, b) => request("PUT", p, b ?? {}),
  del: (p) => request("DELETE", p),
  upload: (p, form) => request("POST", p, form),
};

/** Große Datei als Anfragekörper hochladen, mit Fortschritt (für den Apple-Health-Export). */
export function uploadRaw(path, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("X-BB-Request", "1");
    xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name).slice(0, 200));
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* leer */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error((data && typeof data.detail === "string" && data.detail) || `Fehler ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("Verbindung abgebrochen"));
    xhr.send(file);
  });
}

/** Große Datei in Teilstücken hochladen (ein Proxy davor erlaubt oft nur 1 MB je Anfrage). */
export async function uploadChunked(path, file, headers = {}, onProgress) {
  const size = 900 * 1024;
  const total = Math.max(1, Math.ceil(file.size / size));
  const id = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  let result = null;
  for (let i = 0; i < total; i += 1) {
    const part = file.slice(i * size, (i + 1) * size);
    let tries = 0;
    for (;;) {
      try {
        const r = await fetch(`/api${path}`, {
          method: "POST", credentials: "same-origin", body: part,
          headers: { "X-BB-Request": "1", "X-Upload-Id": id, "X-Chunk-Index": String(i), "X-Chunk-Total": String(total),
            "X-Filename": encodeURIComponent(file.name).slice(0, 200), "Content-Type": "application/octet-stream", ...headers },
        });
        const data = await r.json().catch(() => null);
        if (!r.ok) {
          const err = new Error((data && typeof data.detail === "string" && data.detail) || `Fehler ${r.status}`);
          err.fatal = r.status < 500;
          throw err;
        }
        result = data;
        break;
      } catch (e) {
        tries += 1;
        if (e.fatal || tries >= 3) throw e;
        await new Promise((res) => setTimeout(res, 1000 * tries));
      }
    }
    if (onProgress) onProgress((i + 1) / total);
  }
  return result;
}

export async function logoutRequest() {
  try { await fetch("/api/auth/logout", { method: "POST", headers: { "X-BB-Request": "1" }, credentials: "same-origin" }); } catch { /* egal */ }
}
