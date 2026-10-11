import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { AppProvider } from "./app/AppProvider";
import "./styles/globals.css";
import "./styles/responsive.css";
import "./styles/tokens.css";

const root = document.querySelector<HTMLDivElement>("#root");

if (root === null) {
  throw new Error("Sortax root element is missing");
}

createRoot(root).render(
  <StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </StrictMode>,
);
