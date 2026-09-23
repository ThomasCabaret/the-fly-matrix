import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, "../../reports/generated/wiring-map"),
    emptyOutDir: true,
    sourcemap: true,
  },
});
