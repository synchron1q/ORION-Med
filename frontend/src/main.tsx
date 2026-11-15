// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.getRegistrations().then((regs) => {
    for (const reg of regs) {
      reg.unregister();
    }
  });
  if ("caches" in window) {
    caches.keys().then((keys) => {
      for (const k of keys) {
        caches.delete(k);
      }
    });
  }
}
