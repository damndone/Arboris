import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";

const root = document.getElementById("root");

// V1.5.1 T6 — ThemeProvider lives inside <App /> (src/App.tsx) so the
// test harness gets it for free when it renders App directly.
if (root) {
  createRoot(root).render(
    <StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </StrictMode>
  );
}
