import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#101820",
        mint: "#54f2c3",
        sand: "#f5f2e8",
        amber: "#ffb347"
      },
      fontFamily: {
        display: ["Ubuntu", "Segoe UI", "sans-serif"],
        body: ["Manrope", "Segoe UI", "sans-serif"]
      }
    }
  },
  plugins: []
};

export default config;
