import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Deflow — an options desk where the AI is the least-trusted component",
  description:
    "Autonomous multi-agent options desk on Alpaca paper trading. Four agents propose, "
    + "twelve deterministic circuit breakers decide, and no model ever produces a number "
    + "that reaches the broker.",
  openGraph: {
    title: "Deflow — an options desk where the AI is the least-trusted component",
    description:
      "Defined-risk option spreads on Alpaca, harvesting the variance risk premium behind "
      + "a zero-LLM deterministic risk gate.",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-mono antialiased">{children}</body>
    </html>
  );
}
