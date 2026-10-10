import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Explainable News Verifier",
  description:
    "Evidence-driven claim verification with source provenance, cross-source corroboration, and explainable AI.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
