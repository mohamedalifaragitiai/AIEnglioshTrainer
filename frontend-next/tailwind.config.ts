import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Every colour resolves through a CSS variable defined in globals.css, so
      // the light theme is a change of values at runtime rather than a second
      // set of classes. `<alpha-value>` is what keeps bg-accent/10 working.
      // Kept in step with the :root block in frontend/index.html — the two
      // front-ends are the same product and should not look like two.
      colors: {
        bg: "rgb(var(--c-bg) / <alpha-value>)",
        fg: "rgb(var(--c-text) / <alpha-value>)",
        panel: "rgb(var(--c-panel) / <alpha-value>)",
        panel2: "rgb(var(--c-panel2) / <alpha-value>)",
        panel3: "rgb(var(--c-panel3) / <alpha-value>)",
        line: "rgb(var(--c-line) / <alpha-value>)",
        muted: "rgb(var(--c-muted) / <alpha-value>)",
        dim: "rgb(var(--c-dim) / <alpha-value>)",
        accent: "rgb(var(--c-accent) / <alpha-value>)",
        accent2: "rgb(var(--c-accent2) / <alpha-value>)",
        good: "rgb(var(--c-good) / <alpha-value>)",
        warn: "rgb(var(--c-warn) / <alpha-value>)",
        bad: "rgb(var(--c-bad) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};
export default config;
