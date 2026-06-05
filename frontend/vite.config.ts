import { execSync } from "node:child_process";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import packageJson from "./package.json";

function resolveGitCommit(): string {
  const fromEnv = process.env.VITE_APP_GIT_COMMIT?.trim();
  if (fromEnv) {
    return fromEnv;
  }

  try {
    return execSync("git rev-parse --short HEAD", { encoding: "utf8" }).trim();
  } catch {
    return "";
  }
}

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(packageJson.version),
    __APP_GIT_COMMIT__: JSON.stringify(resolveGitCommit()),
  },
  server: {
    port: 5173,
    host: "0.0.0.0"
  }
});
