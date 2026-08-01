"use client";

import { useUser } from "@/app/user-context";

export function Footer() {
  const { isAdmin, authRequired } = useUser();
  // Same rule as the header chrome: deployment trivia is for whoever runs the
  // box. A learner gets the credit line and nothing else.
  const operator = isAdmin || !authRequired;

  return (
    <footer className="text-center text-dim text-xs px-[clamp(14px,2.2vw,34px)] pt-6 pb-9">
      © {new Date().getFullYear()} <b>Abu Ali</b> · AI English Coach
      {operator && <> — fully offline, self-hosted.</>}
    </footer>
  );
}
