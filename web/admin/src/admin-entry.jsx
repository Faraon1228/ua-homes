import React from "./react-shim.js";
import { AdminApp } from "./AdminApp.jsx";
import { ErrorBoundary } from "./components/ErrorBoundary.jsx";

const root = document.getElementById("root");
if (root && window.ReactDOM?.createRoot) {
  window.ReactDOM.createRoot(root).render(
    React.createElement(ErrorBoundary, null, React.createElement(AdminApp)),
  );
}
