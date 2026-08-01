"use client";

import { useEffect, useState } from "react";

/**
 * Dark/light switch.
 *
 * The initial value is written by an inline script in <head> (see layout.tsx),
 * not here: a React effect runs after first paint, which is exactly when the
 * white flash on reload happens. This component only reads what is already on
 * the element and lets you change it.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    const current = document.documentElement.dataset.theme;
    setTheme(current === "light" ? "light" : "dark");
  }, []);

  const toggle = () => {
    const next = theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    setTheme(next);
    try {
      localStorage.setItem("coach.theme", next);
    } catch {}
  };

  return (
    <button className="btn" onClick={toggle} title="Switch between dark and light">
      {theme === "light" ? "☀️" : "🌙"}
    </button>
  );
}
