import type { Metadata } from "next";
import ScanStudio from "@/features/scans/scan-studio";

export const metadata: Metadata = { title: "Single slice" };

export default function SingleScanPage() {
  return <ScanStudio mode="single" />;
}
