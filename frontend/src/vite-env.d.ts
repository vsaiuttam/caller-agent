/// <reference types="vite/client" />

/** From package.json, stamped at build time (vite.config.ts `define`). */
declare const __APP_VERSION__: string;
/** Short commit SHA from the host's build env (Vercel, Render, CI), or "". */
declare const __BUILD_SHA__: string;
/** YYYY-MM-DD the bundle was built. */
declare const __BUILD_DATE__: string;
