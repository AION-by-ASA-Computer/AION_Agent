import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import "katex/dist/katex.min.css";
import { AuthGate } from "@/components/auth/AuthGate";
import { LanguageSync } from "@/components/i18n/LanguageSync";
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "AION Chat", template: "%s · AION Chat" },
  description: "Agent chat UI",
  icons: {
    icon: [{ url: "/favicon.ico", sizes: "any" }],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
};

const themeInit = `
  try {
    var k = 'aion-chat-theme';
    var s = localStorage.getItem(k);
    if (s === 'light' || s === 'dark') {
      document.documentElement.setAttribute('data-theme', s);
    } else {
      document.documentElement.setAttribute('data-theme', 'dark');
    }
  } catch (e) {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
`;

const langInit = `
  try {
    var k = 'aion_chat_language';
    var s = localStorage.getItem(k);
    var supported = ['it','en','es','fr','de'];
    if (s && supported.indexOf(s) !== -1) {
      document.documentElement.lang = s;
    } else {
      var nav = (navigator.language || 'en').split('-')[0];
      document.documentElement.lang = supported.indexOf(nav) !== -1 ? nav : 'en';
    }
  } catch (e) {
    document.documentElement.lang = 'en';
  }
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="it" data-theme="dark" suppressHydrationWarning className={inter.variable}>
      <head>
        <script
          id="aion-chat-theme-init"
          dangerouslySetInnerHTML={{ __html: themeInit }}
        />
        <script
          id="aion-chat-lang-init"
          dangerouslySetInnerHTML={{ __html: langInit }}
        />
      </head>
      <body className="min-h-screen">
        <LanguageSync />
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}
