import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { compactPublicDataPlugin } from "./build/compact-public-data.mjs";

export default defineConfig(({mode}) => {
  const env = {...loadEnv(mode, process.cwd(), "VITE_"), ...process.env};
  const separateData = Boolean(env.VITE_DATA_BASE_URL?.trim());
  if (separateData) {
    const target = new URL(env.VITE_DATA_BASE_URL!.trim());
    if (target.protocol !== "https:" || target.username || target.password || target.search || target.hash) {
      throw new Error("Production static data base must be an HTTPS URL without credentials or query parameters");
    }
  }
  return {
    cacheDir: ".vite-refactor",
    base: env.VITE_BASE_PATH || "/",
    publicDir: separateData ? false : "public",
    plugins: [react(), ...(separateData ? [] : [compactPublicDataPlugin()])]
  };
});
