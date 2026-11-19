import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/tokens.css";
import "./styles/kit.css";
import "./styles/toast.css";
import "./styles/accounts.css";
import "./styles/billing.css";
import "./styles/workspace.css";
import "./styles/views.css";
import "./styles/fixes.css";

const theme = localStorage.getItem("butter.theme") ?? "dark";
document.documentElement.dataset.theme = theme;

// Window chrome differs per OS: macOS overlays the traffic lights on the left,
// Windows draws its controls on the right. CSS keys off this attribute.
const ua = navigator.userAgent;
const platform = /Windows/i.test(ua)
  ? "windows"
  : /Mac OS X|Macintosh/i.test(ua)
    ? "macos"
    : /Linux/i.test(ua)
      ? "linux"
      : "unknown";
document.documentElement.dataset.platform = platform;

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
