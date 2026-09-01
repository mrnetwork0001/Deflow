import type { Metadata } from "next";

// app/dashboard/page.tsx is a client component and so cannot export metadata
// of its own; this route layout supplies it.
export const metadata: Metadata = {
  title: "Deflow — Live Desk",
  description: "Live regime read, open structures, decision stream and risk-gate state.",
};

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
