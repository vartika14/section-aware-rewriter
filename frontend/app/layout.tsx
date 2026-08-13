import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Section-aware rewrite agent",
  description: "Rewrite one section without breaking the rest of the document.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
