import { Route, Routes } from "react-router";

import { AppLayout } from "./app/AppLayout";
import { HealthProvider } from "./hooks/useHealth";
import { AdminPage } from "./pages/AdminPage";
import { ChatPage } from "./pages/ChatPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export function App() {
  return (
    <HealthProvider>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<ChatPage />} />
          <Route path="admin" element={<AdminPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </HealthProvider>
  );
}
