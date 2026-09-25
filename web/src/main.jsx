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
        <Route path="/" element={<Home />} />
        <Route path="/app" element={<App />} />
        <Route path="/overlay/:stageId" element={<Overlay />} />
        <Route path="/operator" element={<Admin />} />
        <Route path="/operator/rooms" element={<Admin />} />
        <Route path="/operator/broadcasts" element={<Admin />} />
        <Route path="/operator/archive" element={<Admin />} />
        <Route path="/operator/integrations" element={<Admin />} />
        <Route path="/operator/system" element={<Admin />} />
        <Route path="/operator/output/:stageId" element={<OutputStage />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/captions/clean" element={<Clean />} />
        <Route path="/archive/:stageId" element={<Archive />} />
        <Route path="/operator/archive/:sessionId" element={<Archive />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
