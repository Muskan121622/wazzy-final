import type { Metadata } from "next";
import { Inter, Sora } from "next/font/google";
import { Geist_Mono } from "next/font/google";
import "./globals.css";
import FluidCursor from "@/components/FluidCursor";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const sora = Sora({
  variable: "--font-sora",
  subsets: ["latin"],
  weight: ["400", "600", "700", "800"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Wayzyy TripOS — AI Travel Operating System",
  description: "Your living itinerary adapts as reality changes. Powered by GIS, real-time weather, and AI.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${sora.variable} ${geistMono.variable} h-full antialiased`}
      style={{ background: '#050B14' }}
    >
      <body className="min-h-full flex flex-col bg-[#050B14]">
        <FluidCursor />
        {children}
      </body>
    </html>
  );
}
