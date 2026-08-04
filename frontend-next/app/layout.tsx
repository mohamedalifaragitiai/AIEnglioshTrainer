import type { Metadata, Viewport } from "next";
import "./globals.css";
import { UserProvider } from "./user-context";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { Sidebar } from "@/components/Sidebar";
import { LevelGate } from "@/components/LevelGate";

export const metadata: Metadata = {
  title: "AI English Coach",
  description: "Offline AI English speaking & listening coach dashboard.",
  // The brand mark, inline rather than a file: one fewer request and it cannot
  // go missing. Same glyph as the served UI's tab icon, so the two front-ends
  // look like one product in a row of browser tabs.
  icons: {
    icon: [
      {
        url:
          "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E" +
          "%3Crect width='64' height='64' rx='16' fill='%237c6cf6'/%3E" +
          "%3Cpath d='M20 44V20h6l6 12 6-12h6v24h-6V31l-6 11-6-11v13z' fill='white'/%3E%3C/svg%3E",
        type: "image/svg+xml",
      },
    ],
  },
};

// The phone's browser chrome takes these: on Android the address bar becomes
// part of the app rather than a grey frame around it.
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#080b16" },
    { media: "(prefers-color-scheme: light)", color: "#f4f5fb" },
  ],
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
          {/* Rail beside the content on desktop, bottom bar on phones. The
              padding-bottom is for that bar: without it the last card sits
              underneath the nav and looks cut off. */}
          <div className="mx-auto w-full max-w-[1680px] flex">
            <Sidebar />
            <main className="flex-1 min-w-0 px-[clamp(14px,2.2vw,34px)] py-6 pb-24 lg:pb-6">
              {children}
            </main>
          </div>
          <Footer />
        </UserProvider>
      </body>
    </html>
  );
}
