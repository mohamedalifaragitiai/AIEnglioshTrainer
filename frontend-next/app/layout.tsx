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
        </UserProvider>
      </body>
    </html>
  );
}
