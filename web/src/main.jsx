import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import Admin from "./routes/Admin.jsx";
import App from "./routes/App.jsx";
import Archive from "./routes/Archive.jsx";
import Clean from "./routes/Clean.jsx";
import Overlay from "./routes/Overlay.jsx";
import Home from "./routes/Home.jsx";
import OutputStage from "./routes/OutputStage.jsx";
import NotFound from "./routes/NotFound.jsx";
import Dashboard from "./routes/Dashboard.jsx";
import Rooms from "./routes/Rooms.jsx";
import Guide from "./routes/Guide.jsx";
import { isPublicDeployment } from "./lib/publicBackend.js";
import "./index.css";
import "./glass.css";
import "./night.css";
import "./landing.css";
import "./public-pages.css";

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
        <Route path="/" element={<Home />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/salas" element={<Rooms />} />
        <Route path="/guia" element={<Guide />} />
        <Route path="/app" element={<App />} />
        <Route path="/overlay/:stageId" element={<Overlay />} />
        {!isPublicDeployment && <Route path="/operator" element={<Admin />} />}
        {!isPublicDeployment && <Route path="/operator/rooms" element={<Admin />} />}
        {!isPublicDeployment && <Route path="/operator/broadcasts" element={<Admin />} />}
        {!isPublicDeployment && <Route path="/operator/archive" element={<Admin />} />}
        {!isPublicDeployment && <Route path="/operator/integrations" element={<Admin />} />}
        {!isPublicDeployment && <Route path="/operator/system" element={<Admin />} />}
        {!isPublicDeployment && <Route path="/operator/setup" element={<Admin />} />}
        {!isPublicDeployment && <Route path="/operator/output/:stageId" element={<OutputStage />} />}
        {!isPublicDeployment && <Route path="/admin" element={<Admin />} />}
        <Route path="/captions/clean" element={<Clean />} />
        {!isPublicDeployment && <Route path="/archive/:stageId" element={<Archive />} />}
        {!isPublicDeployment && <Route path="/operator/archive/:sessionId" element={<Archive />} />}
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
