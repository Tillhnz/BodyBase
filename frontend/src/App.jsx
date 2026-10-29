import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, logoutRequest, setUnauthorizedHandler } from "./api.js";
import Shell from "./components/Shell.jsx";
import { ErrorBoundary, FeedbackHost } from "./components/feedback.jsx";
import { loadMeta, resetMeta } from "./meta.js";
import Activities, { ActivityDetail } from "./pages/Activities.jsx";
import Admin from "./pages/Admin.jsx";
import Health from "./pages/Health.jsx";
import Home from "./pages/Home.jsx";
import Login from "./pages/Login.jsx";
import MetricDetail from "./pages/MetricDetail.jsx";
import Settings from "./pages/Settings.jsx";
import Sleep from "./pages/Sleep.jsx";
import Sources from "./pages/Sources.jsx";
import Trends from "./pages/Trends.jsx";

export default function App() {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadUser = useCallback(async () => {
    try {
      const me = await api.get("/me");
      await loadMeta().catch(() => {});
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    await logoutRequest();
    resetMeta();
    setUser(null);
    navigate("/login");
  }, [navigate]);

  useEffect(() => {
    setUnauthorizedHandler(() => { setUser(null); navigate("/login"); });
    loadUser();
  }, [loadUser, navigate]);

  if (loading) return <div className="center muted">Lade …</div>;

  if (!user) {
    return (
      <>
        <FeedbackHost />
        <Routes>
          <Route path="/login" element={<Login onLoggedIn={loadUser} />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </>
    );
  }

  return (
    <>
      <FeedbackHost />
      <Shell user={user} onLogout={logout}>
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Home user={user} />} />
            <Route path="/activities" element={<Activities />} />
            <Route path="/activities/:id" element={<ActivityDetail />} />
            <Route path="/sleep" element={<Sleep />} />
            <Route path="/health" element={<Health />} />
            <Route path="/metric/:key" element={<MetricDetail user={user} onUser={setUser} />} />
            <Route path="/trends" element={<Trends />} />
            <Route path="/sources" element={<Sources user={user} />} />
            <Route path="/settings" element={<Settings user={user} onChange={setUser} />} />
            {user.is_admin && <Route path="/admin" element={<Admin user={user} />} />}
            <Route path="/login" element={<Navigate to="/" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ErrorBoundary>
      </Shell>
    </>
  );
}
