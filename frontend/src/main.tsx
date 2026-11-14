import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { ToastProvider } from "./components/ui";
import { PrefsProvider } from "./i18n";
import "./styles/app.css";
import "./styles/configuration.css";
import "./styles/calendar.css";
import "./styles/modern.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PrefsProvider>
      <ToastProvider>
        <App />
      </ToastProvider>
    </PrefsProvider>
  </StrictMode>,
);
