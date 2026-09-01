import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Deflow — Documentation",
  description:
    "What Deflow is, how the four-agent desk decides, what the deterministic "
    + "risk gate enforces, and how to run it yourself.",
};

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
