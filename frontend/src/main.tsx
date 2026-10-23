import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { initAuth } from "./auth";
import "./styles.css";

const root = ReactDOM.createRoot(document.getElementById("root")!);

initAuth()
  .then(() =>
    root.render(
      <React.StrictMode>
        <App />
      </React.StrictMode>,
    ),
  )
  .catch((e: Error) =>
    root.render(
      <div className="boot-error">
        <h1>Legal Cockpit can't start</h1>
        <p>{e.message}</p>
      </div>,
    ),
  );
