import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API base defaults to the local backend; override with VITE_API_BASE.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
