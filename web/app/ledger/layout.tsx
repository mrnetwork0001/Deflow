import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Deflow - Decision Ledger",
  description:
    "Every decision the desk has made, hash-chained and tamper-evident. "
    + "Each entry carries the SHA-256 of the one before it.",
};

export default function LedgerLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
