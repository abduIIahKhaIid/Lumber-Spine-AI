import type { Metadata } from "next";
import ScanStudio from "@/features/scans/scan-studio";

export const metadata: Metadata = { title: "Full series" };

export default function MultiScanPage() {
  return <ScanStudio mode="multi" />;
}
