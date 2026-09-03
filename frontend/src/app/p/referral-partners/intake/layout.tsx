import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Referral partner profile",
  description: "Securely submit your referral partner business profile and customer offer.",
  robots: { index: false, follow: false, nocache: true },
  referrer: "no-referrer",
};

export default function ReferralPartnerIntakeLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
