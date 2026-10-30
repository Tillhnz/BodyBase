import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { api } from "../api.js";
import ThemeToggle from "./ThemeToggle.jsx";
import { BrandMark } from "./ui.jsx";

export const NAV = [
  { to: "/", label: "Übersicht", short: "Start", end: true, icon: "M4 12 A8 8 0 1 1 12 20 M12 8 A4 4 0 1 1 8 12 M12 12 H12.01" },
  { to: "/activities", label: "Aktivitäten", short: "Training", icon: "M13 4 A1.6 1.6 0 1 0 13.01 4 M8 21 L11 14 L14 16 V21 M6 11 L9 8 L13 8.5 L16 12 L19 13" },
  { to: "/strength", label: "Kraft", icon: "M4 9 V15 M7 7 V17 M17 7 V17 M20 9 V15 M7 12 H17" },
  { to: "/sleep", label: "Schlaf", icon: "M20 14.5 A8 8 0 1 1 9.5 4 A6.5 6.5 0 0 0 20 14.5 Z" },
  { to: "/health", label: "Gesundheit", short: "Körper", icon: "M12 20 C6 16 3 12.5 3 9 A4.5 4.5 0 0 1 12 6.5 A4.5 4.5 0 0 1 21 9 C21 12.5 18 16 12 20 Z M7 11 H9.5 L11 8.5 L13 13 L14.5 11 H17" },
  { to: "/trends", label: "Trends", desk: true, icon: "M3 17 L9 11 L13 15 L21 7 M15 7 H21 V13" },
  { to: "/sources", label: "Quellen", icon: "M12 3 V9 M12 15 V21 M3 12 H9 M15 12 H21 M12 12 H12.01 M5.6 5.6 L9 9 M15 15 L18.4 18.4 M18.4 5.6 L15 9 M9 15 L5.6 18.4" },
  { to: "/settings", label: "Einstellungen", short: "Konto", icon: "M12 9 A3 3 0 1 0 12.01 9 M12 3 V5 M12 19 V21 M3 12 H5 M19 12 H21 M5.6 5.6 L7 7 M17 17 L18.4 18.4 M18.4 5.6 L17 7 M7 17 L5.6 18.4" },
];

/** Rahmen: Seitenleiste am Computer, schmale Kopfzeile und Tabs am unteren Rand auf dem Handy. */
export default function Shell({ user, onLogout, children }) {
  const { pathname } = useLocation();
  const [ver, setVer] = useState(null);
  useEffect(() => {
    api.get("/version").then(setVer).catch(() => {});
  }, []);
  useEffect(() => {
    const hit = [...NAV].reverse().find((n) => (n.end ? pathname === n.to : pathname.startsWith(n.to)));
    const extra = pathname.startsWith("/admin") ? "Administration" : pathname.startsWith("/metric") ? "Messgröße" : null;
    document.title = extra ? `${extra} · BodyBase` : hit ? `${hit.label} · BodyBase` : "BodyBase";
  }, [pathname]);
  return (
    <div className="shell">
      <a className="skip-link" href="#inhalt">Zum Inhalt springen</a>
      <aside className="sidebar">
        <div className="brand-row">
          <Link to="/" className="brand"><BrandMark className="brand-mark" />BodyBase</Link>
          <ThemeToggle />
        </div>
        <nav aria-label="Hauptmenü">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={n.desk ? "desk-only" : undefined}>
              <svg viewBox="0 0 24 24" className="nav-icon" aria-hidden="true" focusable="false"><path d={n.icon} /></svg>
              <span className="nav-label">{n.label}</span>
              {n.short && <span className="nav-short" aria-hidden="true">{n.short}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="muted small">{user.name || user.email}</span>
          {user.is_admin && <NavLink className="link desk-only" to="/admin">Administration</NavLink>}
          <button className="link quiet" onClick={onLogout}>Abmelden</button>
          {ver && (
            <div className="version-line">
              <span className="muted tiny">Version {ver.version}</span>
              {ver.update_available && (user.is_admin
                ? <NavLink className="update-hint" to="/admin">Update verfügbar</NavLink>
                : <span className="update-hint">Update verfügbar</span>)}
            </div>
          )}
        </div>
      </aside>
      <main className="main" id="inhalt" tabIndex={-1}>
        <div className="page" key={pathname}>{children}</div>
      </main>
    </div>
  );
}
