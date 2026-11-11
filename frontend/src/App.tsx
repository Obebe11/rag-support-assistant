import { Route, Routes } from "react-router";

import { AppShell } from "./app/AppShell";
import { HealthProvider } from "./hooks/useHealth";
import { AdminPage } from "./pages/AdminPage";
import { ChatPage } from "./pages/ChatPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export function App() {
  return (
    <HealthProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<ChatPage />} />
          <Route path="admin" element={<AdminPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </HealthProvider>
  );
}
