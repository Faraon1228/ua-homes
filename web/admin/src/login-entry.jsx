import React from "./react-shim.js";
import { LoginApp } from "./LoginApp.jsx";
import { api } from "./lib/apiClient.js";

// If a valid staff session cookie already exists, skip the form entirely.
api
  .get("/auth/session")
  .then(() => {
    window.location.replace("./dashboard.html");
  })
  .catch(() => {
    /* Not authenticated — stay on the login form. */
  });

const root = document.getElementById("root");
if (root && window.ReactDOM?.createRoot) {
  window.ReactDOM.createRoot(root).render(React.createElement(LoginApp));
}
