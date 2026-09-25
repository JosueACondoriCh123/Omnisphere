import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import Admin from "./routes/Admin.jsx";
import App from "./routes/App.jsx";
import Archive from "./routes/Archive.jsx";
import Clean from "./routes/Clean.jsx";
import Overlay from "./routes/Overlay.jsx";
import "./index.css";

// OBS must start transparent on its very first painted frame, before effects run.
if (globalThis.location?.pathname.startsWith("/overlay/")) {
  document.documentElement.dataset.surface = "overlay";
  document.body.dataset.surface = "overlay";
}

let updateServiceWorker;
updateServiceWorker = registerSW({
  immediate: true,
  onNeedRefresh() {
    updateServiceWorker?.(true);
  },
});

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/app" replace />} />
        <Route path="/app" element={<App />} />
        <Route path="/overlay/:stageId" element={<Overlay />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/captions/clean" element={<Clean />} />
        <Route path="/archive/:stageId" element={<Archive />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
