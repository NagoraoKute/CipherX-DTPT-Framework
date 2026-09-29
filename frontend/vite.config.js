import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 3000, strictPort: true },
  build: {
    chunkSizeWarningLimit: 600, // recharts is ~530 kB min / ~160 kB gzip on its own
    rollupOptions: {
      output: {
        // Keep the chart library in its own cacheable chunk.
        manualChunks: { react: ["react", "react-dom"], charts: ["recharts"], http: ["axios"] },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.js",
  },
});
