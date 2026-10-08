import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

/**
 * Self-hosted at build time, as in the console: no visitor's browser asks a font
 * CDN for anything. The public site makes no external request at all (ADR-0051 §3).
 */
const sans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "NEURA by FiveNeurals", template: "%s · NEURA by FiveNeurals" },
  description:
    "NEURA-CARE answers your shoppers' questions from your own shop. NEURA-SELL helps them choose.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body className="min-h-dvh">{children}</body>
    </html>
  );
}
