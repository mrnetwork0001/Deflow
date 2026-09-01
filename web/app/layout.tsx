import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Deflow — an options desk where the AI is the least-trusted component",
  description:
    "Autonomous multi-agent options desk on Alpaca paper trading. Four agents propose, "
    + "twelve deterministic circuit breakers decide, and no model ever produces a number "
    + "that reaches the broker.",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/icon-192.png", type: "image/png", sizes: "192x192" },
      { url: "/icon-512.png", type: "image/png", sizes: "512x512" },
    ],
    apple: "/apple-touch-icon.png",
  },
  // Link previews get the full lockup rather than the bare mark.
  openGraph: {
    images: [{ url: "/deflow-header@2x.png", width: 1002, height: 192,
               alt: "Deflow — autonomy, with limits." }],
    title: "Deflow — an options desk where the AI is the least-trusted component",
    description:
      "Defined-risk option spreads on Alpaca, harvesting the variance risk premium behind "
      + "a zero-LLM deterministic risk gate.",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Deflow — an options desk where the AI is the least-trusted component",
    images: ["/deflow-header@2x.png"],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-mono antialiased">{children}</body>
    </html>
  );
}
