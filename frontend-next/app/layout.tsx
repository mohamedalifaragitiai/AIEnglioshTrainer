import type { Metadata } from "next";
import "./globals.css";
import { UserProvider } from "./user-context";
import { Header } from "@/components/Header";

export const metadata: Metadata = {
  title: "AI English Coach",
  description: "Offline AI English speaking & listening coach dashboard.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <UserProvider>
          <Header />
          <main className="max-w-6xl mx-auto px-6 py-6">{children}</main>
          <footer className="text-center text-dim text-xs px-6 pt-6 pb-9">
            © {new Date().getFullYear()} <b>Abu Ali</b> · AI English Coach — fully offline,
            self-hosted.
          </footer>
        </UserProvider>
      </body>
    </html>
  );
}
