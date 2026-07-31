import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
// The juice-pass layers, after the base system so overrides win:
import "./styles/fx-combat.css";
import "./styles/fx-hud.css";
import "./styles/fx-state.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
