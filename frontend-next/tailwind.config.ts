import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Kept in step with the :root variables in frontend/index.html — the two
      // front-ends are the same product and should not look like two.
      colors: {
        bg: "#080d1a",
        panel: "#141d31",
        panel2: "#1b2740",
        line: "#2a3a5c",
        muted: "#9db0d0",
        dim: "#68799e",
        accent: "#2dd4bf",
        accent2: "#a5b4fc",
      },
    },
  },
  plugins: [],
};
export default config;
