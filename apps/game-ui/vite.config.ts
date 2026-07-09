import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built client is served by the FastAPI server from ../game-ui/dist, so the
// client always talks to its own origin. In dev, proxy the API/WS to the server
// (default port 8020) so `npm run dev` + `LTG-Game --dev` work together.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8020", changeOrigin: true },
      "/art": { target: "http://localhost:8020", changeOrigin: true },
      "/ws": { target: "ws://localhost:8020", ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
