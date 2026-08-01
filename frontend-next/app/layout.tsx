import type { Metadata } from "next";
import "./globals.css";
import { UserProvider } from "./user-context";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { LevelGate } from "@/components/LevelGate";

export const metadata: Metadata = {
  title: "AI English Coach",
  description: "Offline AI English speaking & listening coach dashboard.",
};

// Runs before first paint, ahead of React hydrating. Setting the theme from an
// effect instead would paint the default palette first — that flash of the wrong
// theme on every reload is the whole reason this is inline in <head>.
const THEME_BOOT = `try{var t=localStorage.getItem('coach.theme');
if(!t)t=window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';
document.documentElement.dataset.theme=t;}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        <UserProvider>
          <Header />
          <LevelGate />
          <main className="max-w-6xl mx-auto px-6 py-6">{children}</main>
          <Footer />
        </UserProvider>
      </body>
    </html>
  );
}
