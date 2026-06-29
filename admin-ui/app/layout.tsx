import type { Metadata } from "next";
import "./globals.css";
import AppShell from "@/components/AppShell";
import { AdminAuthGate } from "@/components/auth/AdminAuthGate";

export const metadata: Metadata = {
  title: "AION Agent | Admin Panel",
  description: "Advanced agentic management platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="flex h-screen overflow-hidden">
        <AdminAuthGate>
          <AppShell>{children}</AppShell>
        </AdminAuthGate>
      </body>
    </html>
  );
}
