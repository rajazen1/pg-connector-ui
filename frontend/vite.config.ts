import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During dev the React app runs on :5173 and proxies /api to the FastAPI
// backend on :8000, so there are no CORS surprises.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
