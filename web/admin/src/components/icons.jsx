import React from "../react-shim.js";

// Minimal self-hosted line-icon set (no icon font / CDN). Each entry is a
// Feather-style 24x24 stroke path. Icons are decorative by default
// (aria-hidden) — callers add their own visible text label.
const PATHS = {
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  shield: "M12 3l7 3v6c0 4.5-3 8-7 9-4-1-7-4.5-7-9V6z",
  home: "M4 11l8-7 8 7v9a1 1 0 01-1 1h-4v-6H9v6H5a1 1 0 01-1-1z",
  inbox: "M3 5h18l-2 9H5zM3 5v14a1 1 0 001 1h16a1 1 0 001-1V5M8 12h2a2 2 0 004 0h2",
  users: "M9 11a3 3 0 100-6 3 3 0 000 6zM3 20a6 6 0 0112 0M16 8a3 3 0 110 6M15 20a6 6 0 016-4",
  building: "M4 21V5a1 1 0 011-1h9a1 1 0 011 1v16M15 21h5V10l-5-3M8 8h.01M8 12h.01M8 16h.01M12 8h.01M12 12h.01M12 16h.01",
  history: "M3 12a9 9 0 109-9v4M3 12l4-2M3 12l3 3M12 7v5l4 2",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  pulse: "M22 12h-4l-3 8-4-16-3 8H2",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  search: "M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.35-4.35",
  bell: "M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9zM13.73 21a2 2 0 01-3.46 0",
  logout: "M9 21H5a1 1 0 01-1-1V4a1 1 0 011-1h4M16 17l5-5-5-5M21 12H9",
  "chevron-down": "M6 9l6 6 6-6",
  "chevron-right": "M9 6l6 6-6 6",
  close: "M18 6L6 18M6 6l12 12",
  check: "M20 6L9 17l-5-5",
  plus: "M12 5v14M5 12h14",
  edit: "M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4z",
  trash: "M3 6h18M8 6V4a1 1 0 011-1h6a1 1 0 011 1v2m3 0v14a1 1 0 01-1 1H7a1 1 0 01-1-1V6",
  upload: "M12 16V4M6 10l6-6 6 6M4 20h16",
  download: "M12 4v12M6 12l6 6 6-6M4 20h16",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z M12 15a3 3 0 100-6 3 3 0 000 6z",
  filter: "M4 5h16l-6 8v6l-4-2v-4z",
  menu: "M4 7h16M4 12h16M4 17h16",
  alert: "M12 9v4m0 4h.01M10.3 3.9L2.7 17a1.5 1.5 0 001.3 2.2h16a1.5 1.5 0 001.3-2.2L13.7 3.9a1.5 1.5 0 00-2.6 0z",
  refresh: "M4 4v6h6M20 20v-6h-6M4 10a8 8 0 0114.9-3.8M20 14a8 8 0 01-14.9 3.8",
  image: "M4 4h16v16H4zM4 16l5-5 4 4 3-3 4 4M9 9a1 1 0 100-2 1 1 0 000 2z",
  star: "M12 2l3 7h7l-5.5 4.3L18 21l-6-4.3L6 21l1.5-7.7L2 9h7z",
  external: "M14 4h6v6M20 4L10 14M6 4H5a1 1 0 00-1 1v14a1 1 0 001 1h14a1 1 0 001-1v-1",
  spinner: "M12 3a9 9 0 100 18",
};

export function Icon({ name, size = 18, className = "", spin = false, title }) {
  const d = PATHS[name] || PATHS.grid;
  return React.createElement(
    "svg",
    {
      width: size,
      height: size,
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: 2,
      strokeLinecap: "round",
      strokeLinejoin: "round",
      className: `icon${spin ? " icon-spin" : ""}${className ? ` ${className}` : ""}`,
      "aria-hidden": title ? undefined : "true",
      role: title ? "img" : undefined,
    },
    title ? React.createElement("title", null, title) : null,
    React.createElement("path", { d }),
  );
}
