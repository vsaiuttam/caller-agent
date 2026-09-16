import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Where the FastAPI process is listening. Overridable because port 8000 is
// popular — another project holding it shouldn't mean editing this file.
const apiTarget = process.env.API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
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
