import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Navbar from "./components/Navbar";
import { useAuth } from "./auth";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import Dashboard from "./pages/Dashboard";
import Report from "./pages/Report";
import History from "./pages/History";
import type { ReactElement } from "react";

function RequireAuth({ children }: { children: ReactElement }) {
  const { isAuthed } = useAuth();
  const loc = useLocation();
  if (!isAuthed) return <Navigate to="/login" state={{ from: loc }} replace />;
  return children;
}

export default function App() {
  const { isAuthed } = useAuth();

  return (
    <div className="min-h-screen">
      {isAuthed && <Navbar />}
      <main className="mx-auto max-w-5xl px-4 py-8">
        <Routes>
          <Route
            path="/login"
            element={isAuthed ? <Navigate to="/" replace /> : <Login />}
          />
          <Route
            path="/signup"
            element={isAuthed ? <Navigate to="/" replace /> : <Signup />}
          />
          <Route
            path="/"
            element={
              <RequireAuth>
                <Dashboard />
              </RequireAuth>
            }
          />
          <Route
            path="/report/:id"
            element={
              <RequireAuth>
                <Report />
              </RequireAuth>
            }
          />
          <Route
            path="/history"
            element={
              <RequireAuth>
                <History />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
