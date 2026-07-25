import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0f172a",
        panel: "#1e293b",
        panel2: "#273449",
        line: "#334155",
        muted: "#94a3b8",
        accent: "#2dd4bf",
        accent2: "#818cf8",
      },
    },
  },
  plugins: [],
};
export default config;
