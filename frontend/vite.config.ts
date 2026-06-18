import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: process.env.VITE_OUT_DIR ||
      fileURLToPath(new URL("../src/yey/boats/simulator/web/static", import.meta.url)),
    emptyOutDir: true,
  },
  server: { proxy: { "/api": "http://127.0.0.1:8080" } },
});
