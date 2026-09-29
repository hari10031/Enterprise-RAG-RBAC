import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // The API sets its session cookie on /api, so the dev server proxies it to keep one origin.
    proxy: { "/api": "http://localhost:8000" },
  },
});
