import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

/**
 * Loaded through `next/font`, which self-hosts the files at build time. No
 * request ever leaves the merchant's browser for a font CDN — which keeps a
 * third party out of the page and keeps the console usable inside a sovereign
 * deployment that has no route to the public internet (ADR-0026).
 */
const sans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "FiveNeurals Console",
  description: "Manage your FiveNeurals AI agents — conversations, reviews, and your shop.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // The font variables go on <html>, not <body>: `globals.css` applies
    // `font-sans` at the `html` element, and a variable declared one level below
    // is invisible to it — the page renders in the browser's serif default and
    // nothing errors.
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <body className="min-h-dvh bg-background text-foreground antialiased">
        {children}
        <Toaster position="top-center" />
      </body>
    </html>
  );
}
