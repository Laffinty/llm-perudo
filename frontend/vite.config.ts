import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      "/matches": { target: "http://127.0.0.1:8900", ws: true },
      "/api": { target: "http://127.0.0.1:8900" },
    },
  },
  build: { outDir: "dist" },
});
