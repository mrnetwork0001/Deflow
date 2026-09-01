import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Deflow — Autonomous Options Desk",
  description:
    "Autonomous multi-agent options trading desk on Alpaca paper trading, with a zero-LLM deterministic risk gate.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-mono antialiased">{children}</body>
    </html>
  );
}
