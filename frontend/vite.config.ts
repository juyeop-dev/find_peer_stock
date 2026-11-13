import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { compactPublicDataPlugin } from "./build/compact-public-data.mjs";

export default defineConfig({
  base: process.env.VITE_BASE_PATH || "/",
  plugins: [react(), compactPublicDataPlugin()]
});
