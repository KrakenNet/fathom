import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      "/v1": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // vite 8 deprecated the esbuild transformer and no longer installs
    // esbuild; oxc is its built-in replacement. This also drops esbuild from
    // the dependency tree entirely (GHSA-g7r4-m6w7-qqqr).
    minify: "oxc",
    rollupOptions: {
      output: {
        // Function form, not the `{ vendor: [...] }` object: vite 8 bundles
        // with rolldown, which only accepts a callback here and fails the
        // build with "manualChunks is not a function" on the object form.
        manualChunks(id: string) {
          if (id.includes("node_modules/react")) {
            return "vendor";
          }
          return undefined;
        },
      },
    },
  },
});
