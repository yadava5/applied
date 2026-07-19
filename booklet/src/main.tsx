import React from "react";
import ReactDOM from "react-dom/client";
import { Booklet } from "./Booklet";

// Self-hosted fonts — Plus Jakarta Sans + Instrument Serif ship as @fontsource
// npm packages; Vite bundles the .woff2 binaries into /assets so puppeteer's
// headless export renders identical glyphs to the dev preview. Monaspace Neon
// is served from /public/fonts (see ./styles/fonts.css).
import "@fontsource/plus-jakarta-sans/400.css";
import "@fontsource/plus-jakarta-sans/500.css";
import "@fontsource/plus-jakarta-sans/600.css";
import "@fontsource/plus-jakarta-sans/700.css";
import "@fontsource/instrument-serif/400.css";
import "@fontsource/instrument-serif/400-italic.css";
import "./styles/fonts.css";
import "./styles/reset.css";
import "./styles/print.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Booklet />
  </React.StrictMode>,
);
