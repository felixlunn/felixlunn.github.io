import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Each build stamps its data URLs (?v=...), so a browser never pairs new page code with a cached older data.json:
// GitHub Pages lets browsers reuse files for 10 minutes, and the data and code are always deployed together.
const BUILD_ID = Date.now().toString(36);

// base "./" makes the build work from any path (GitHub Pages project sites, subfolders, file servers).
export default defineConfig({
  base: "./",
  plugins: [react(), { name: "build-id", transformIndexHtml: (html: string) => html.split("__BUILD_ID__").join(BUILD_ID) }],
  define: { "import.meta.env.VITE_BUILD_ID": JSON.stringify(BUILD_ID) },
  build: {
    target: "es2020",
    chunkSizeWarningLimit: 900, // maplibre-gl is ~800 kB on its own and loads in parallel
    rollupOptions: {
      output: {
        manualChunks: { maplibre: ["maplibre-gl"] },
      },
    },
  },
});
