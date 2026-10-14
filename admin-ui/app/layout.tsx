import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import AppShell from "@/components/AppShell";
import { AdminAuthGate } from "@/components/auth/AdminAuthGate";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

// Runs before paint so the stored theme never flashes. Falls back to the chat-ui choice, then dark.
const themeInit = `
  try {
    var s = localStorage.getItem('aion-admin-theme') || localStorage.getItem('aion-chat-theme');
    document.documentElement.setAttribute('data-theme', s === 'light' ? 'light' : 'dark');
  } catch (e) {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
`;

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
    <html lang="en" data-theme="dark" suppressHydrationWarning className={inter.variable}>
      <head>
        <script id="aion-admin-theme-init" dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body className="h-[100dvh] overflow-hidden">
        <AdminAuthGate>
          <AppShell>{children}</AppShell>
        </AdminAuthGate>
      </body>
    </html>
  );
}
