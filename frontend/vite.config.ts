import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Where the FastAPI process is listening. Overridable because port 8000 is
// popular — another project holding it shouldn't mean editing this file.
const apiTarget = process.env.API_TARGET ?? "http://127.0.0.1:8000";

// Build stamp for the console footer. The commit comes from whichever host
// is building (Vercel, Render, GitHub Actions); locally it's simply absent.
const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as { version: string };
const sha = (process.env.VERCEL_GIT_COMMIT_SHA ?? process.env.RENDER_GIT_COMMIT ?? process.env.GITHUB_SHA ?? "").slice(0, 7);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __BUILD_SHA__: JSON.stringify(sha),
    __BUILD_DATE__: JSON.stringify(new Date().toISOString().slice(0, 10)),
  },
  server: {
    port: 5173,
    proxy: {
      // Both the REST API and the WebSockets (the live feed, and the mic
      // call) go to the FastAPI process in dev, so the frontend code can use
      // same-origin paths and needs no separate config for production, where
      // FastAPI serves dist/.
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
