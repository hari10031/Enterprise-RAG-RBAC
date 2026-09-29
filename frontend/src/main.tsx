import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { Shell } from "./components/Shell";
import "./index.css";
import { Account } from "./pages/Account";
import { Chat } from "./pages/Chat";
import { Login } from "./pages/Login";
import { Documents } from "./pages/admin/Documents";
import { Folders } from "./pages/admin/Folders";
import { Health } from "./pages/admin/Health";
import { People } from "./pages/admin/People";

function App() {
  const { me, loading } = useAuth();
  if (loading) return <div className="grid h-dvh place-items-center text-graphite">Loading…</div>;
  if (!me) return <Login />;
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/chat" element={<Chat />} />
        <Route path="/chat/:conversationId" element={<Chat />} />
        <Route path="/account" element={<Account />} />
        {me.is_admin && (
          <>
            <Route path="/admin/documents" element={<Documents />} />
            <Route path="/admin/groups" element={<People />} />
            <Route path="/admin/folders" element={<Folders />} />
            <Route path="/admin/health" element={<Health />} />
          </>
        )}
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
