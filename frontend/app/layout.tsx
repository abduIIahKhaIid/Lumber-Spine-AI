import type { Metadata, Viewport } from "next";
import "./globals.css";
import AppShell from "@/components/app-shell";

export const metadata: Metadata = {
  title: { default: "SpineScope · Lumbar MRI grading", template: "%s · SpineScope" },
  description:
    "Grade spinal canal, foraminal and subarticular stenosis on lumbar MRI, review the evidence and discuss it with an assistant.",
};

export const viewport: Viewport = { themeColor: "#eef1f4" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
